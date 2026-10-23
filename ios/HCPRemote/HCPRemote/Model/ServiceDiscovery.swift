import Foundation
import Network
import Observation

/// Finds controllers advertising `_hcp._tcp` via Bonjour (see deploy/hcp-avahi.service).
@MainActor
@Observable
final class ServiceDiscovery {
    struct Service: Identifiable, Hashable {
        let name: String
        let endpoint: NWEndpoint
        var id: String { name }
    }

    private(set) var services: [Service] = []
    private(set) var isSearching = false
    private(set) var error: String?
    private var browser: NWBrowser?

    func start() {
        stop()
        let browser = NWBrowser(for: .bonjour(type: "_hcp._tcp", domain: "local."), using: .tcp)
        browser.stateUpdateHandler = { [weak self] state in
            Task { @MainActor in
                switch state {
                case .failed(let e), .waiting(let e):
                    self?.error = "局域网搜索失败：\(e.localizedDescription)（请在系统设置中允许“本地网络”权限）"
                default:
                    break
                }
            }
        }
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            let found = results.compactMap { result -> Service? in
                guard case let .service(name, _, _, _) = result.endpoint else { return nil }
                return Service(name: name, endpoint: result.endpoint)
            }
            Task { @MainActor in self?.services = found.sorted { $0.name < $1.name } }
        }
        browser.start(queue: .main)
        self.browser = browser
        isSearching = true
        error = nil
    }

    func stop() {
        browser?.cancel()
        browser = nil
        isSearching = false
    }

    /// Resolves a Bonjour service to an http:// URL with its IPv4 address and port.
    nonisolated static func resolve(_ service: Service) async throws -> URL {
        let params = NWParameters.tcp
        if let ip = params.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options {
            ip.version = .v4
        }
        let connection = NWConnection(to: service.endpoint, using: params)
        return try await withCheckedThrowingContinuation { continuation in
            let once = ResumeOnce(continuation)
            connection.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    if case let .hostPort(host, port) = connection.currentPath?.remoteEndpoint {
                        var hostText = "\(host)"
                        if let zone = hostText.firstIndex(of: "%") { hostText = String(hostText[..<zone]) }
                        if let url = URL(string: "http://\(hostText):\(port.rawValue)") {
                            once.resume(.success(url))
                        } else {
                            once.resume(.failure(HCPError.invalidURL))
                        }
                    } else {
                        once.resume(.failure(HCPError.invalidURL))
                    }
                    connection.cancel()
                case .failed(let e), .waiting(let e):
                    once.resume(.failure(HCPError.network(e.localizedDescription)))
                    connection.cancel()
                default:
                    break
                }
            }
            connection.start(queue: .global())
            DispatchQueue.global().asyncAfter(deadline: .now() + 8) {
                once.resume(.failure(HCPError.network("解析超时")))
                connection.cancel()
            }
        }
    }
}

/// Guards a continuation against being resumed twice from Network callbacks.
private final class ResumeOnce: @unchecked Sendable {
    private var continuation: CheckedContinuation<URL, Error>?
    private let lock = NSLock()

    init(_ continuation: CheckedContinuation<URL, Error>) { self.continuation = continuation }

    func resume(_ result: Result<URL, Error>) {
        lock.lock()
        let c = continuation
        continuation = nil
        lock.unlock()
        c?.resume(with: result)
    }
}
