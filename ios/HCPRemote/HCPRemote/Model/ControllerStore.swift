import Foundation
import Observation

/// App state: the controller address, the latest status and the commands sent to it.
@MainActor
@Observable
final class ControllerStore {
    private static let urlKey = "hcp.baseURL"

    var baseURL: URL? {
        didSet {
            UserDefaults.standard.set(baseURL?.absoluteString, forKey: Self.urlKey)
            status = nil
            lastError = nil
        }
    }
    private(set) var status: ControllerStatus?
    private(set) var lastUpdated: Date?
    var lastError: String?
    private(set) var isSending = false

    init() {
        if let saved = UserDefaults.standard.string(forKey: Self.urlKey) {
            baseURL = URL(string: saved)
        }
    }

    var client: HCPClient? { baseURL.map(HCPClient.init) }

    /// True when the last poll failed or is older than three intervals.
    var isStale: Bool {
        guard let lastUpdated else { return true }
        return Date().timeIntervalSince(lastUpdated) > 10
    }

    func refresh() async {
        guard let client else { return }
        do {
            status = try await client.status()
            lastUpdated = Date()
            if !isSending { lastError = nil }
        } catch is CancellationError {
        } catch {
            lastError = error.localizedDescription
        }
    }

    /// Polls every 3 s until the calling task is cancelled (the view disappears or the app goes to background).
    func poll() async {
        while !Task.isCancelled {
            await refresh()
            try? await Task.sleep(for: .seconds(3))
        }
    }

    func perform(_ action: (HCPClient) async throws -> ControllerStatus) async {
        guard let client else { return }
        isSending = true
        defer { isSending = false }
        do {
            status = try await action(client)
            lastUpdated = Date()
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    func setMode(_ mode: ControlMode) async { await perform { try await $0.setMode(mode) } }
    func setTarget(_ t: Int) async { await perform { try await $0.setTarget(t) } }
    func moveValve(steps: Int) async { await perform { try await $0.moveValve(steps: steps) } }
    func moveValve(to position: Int) async { await perform { try await $0.moveValve(to: position) } }
    func calibrate() async { await perform { try await $0.calibrate() } }
}
