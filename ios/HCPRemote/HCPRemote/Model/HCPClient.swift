import Foundation

enum HCPError: LocalizedError {
    case invalidURL
    case server(Int, String)
    case network(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL: "控制器地址无效"
        case let .server(code, message): "控制器拒绝了请求（\(code)）：\(message)"
        case let .network(message): "连接不上控制器：\(message)"
        }
    }
}

/// Thin async wrapper around the controller's HTTP API.
struct HCPClient {
    let baseURL: URL

    private static let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 6
        config.waitsForConnectivity = false
        return URLSession(configuration: config)
    }()

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    /// Accepts "192.168.178.34", "192.168.178.34:8080", "hcp.local" or a full http:// URL.
    static func url(from text: String) -> URL? {
        var s = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !s.isEmpty else { return nil }
        if !s.contains("://") { s = "http://" + s }
        guard var comps = URLComponents(string: s), comps.host?.isEmpty == false else { return nil }
        if comps.port == nil { comps.port = 8080 }
        comps.path = ""
        return comps.url
    }

    func status() async throws -> ControllerStatus { try await send("GET", "/api/status") }
    func setMode(_ mode: ControlMode) async throws -> ControllerStatus {
        try await send("PUT", "/api/mode", body: ["mode": mode.rawValue])
    }
    func setTarget(_ temperature: Int) async throws -> ControllerStatus {
        try await send("PUT", "/api/target", body: ["temperature": temperature])
    }
    func setNightSaver(_ enabled: Bool) async throws -> ControllerStatus {
        try await send("PUT", "/api/night-saver", body: ["enabled": enabled])
    }
    func moveValve(steps: Int) async throws -> ControllerStatus {
        try await send("POST", "/api/valve/move", body: ["steps": steps])
    }
    func moveValve(to position: Int) async throws -> ControllerStatus {
        try await send("POST", "/api/valve/move", body: ["position": position])
    }
    func calibrate() async throws -> ControllerStatus {
        try await send("POST", "/api/valve/calibrate", body: [String: Int]())
    }
    func zeroCalibration(_ action: String) async throws -> ControllerStatus {
        try await send("POST", "/api/valve/zero/\(action)", body: [String: Int]())
    }
    func zeroJog(steps: Int) async throws -> ControllerStatus {
        try await send("POST", "/api/valve/zero/jog", body: ["steps": steps])
    }
    func history(hours: Double, maxPoints: Int = 400) async throws -> HistoryResponse {
        try await send("GET", "/api/history?hours=\(hours)&max_points=\(maxPoints)")
    }
    func events(limit: Int = 100) async throws -> EventsResponse {
        try await send("GET", "/api/events?limit=\(limit)")
    }

    private func send<T: Decodable>(_ method: String, _ path: String,
                                    body: [String: some Encodable] = [String: Int]()) async throws -> T {
        guard let url = URL(string: path, relativeTo: baseURL) else { throw HCPError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = method
        if method != "GET" {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(body)
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await Self.session.data(for: request)
        } catch {
            throw HCPError.network(error.localizedDescription)
        }
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let message = (try? Self.decoder.decode(APIErrorBody.self, from: data))?.error ?? "HTTP \(code)"
            throw HCPError.server(code, message)
        }
        return try Self.decoder.decode(T.self, from: data)
    }
}
