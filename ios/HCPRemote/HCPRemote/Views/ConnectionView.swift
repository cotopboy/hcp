import SwiftUI

struct ConnectionView: View {
    @Environment(ControllerStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var discovery = ServiceDiscovery()
    @State private var address = ""
    @State private var checking = false
    @State private var message: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    if discovery.services.isEmpty {
                        HStack {
                            ProgressView()
                            Text("正在局域网中搜索控制器…").foregroundStyle(.secondary)
                        }
                    }
                    ForEach(discovery.services) { service in
                        Button {
                            Task { await use(service) }
                        } label: {
                            Label(service.name, systemImage: "thermometer.medium")
                        }
                    }
                    if let error = discovery.error {
                        Text(error).font(.caption).foregroundStyle(.orange)
                    }
                } header: {
                    Text("自动发现")
                }

                Section {
                    TextField("例如 192.168.178.34:8080", text: $address)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button("连接") {
                        Task { await use(text: address) }
                    }
                    .disabled(address.trimmingCharacters(in: .whitespaces).isEmpty || checking)
                } header: {
                    Text("手动输入地址")
                } footer: {
                    Text("端口默认 8080。当前：\(store.baseURL?.absoluteString ?? "未设置")")
                }

                if checking || message != nil {
                    Section {
                        if checking {
                            HStack { ProgressView(); Text("正在测试连接…") }
                        }
                        if let message { Text(message).foregroundStyle(.red) }
                    }
                }
            }
            .navigationTitle("连接控制器")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("完成") { dismiss() }
                }
            }
            .onAppear {
                address = store.baseURL.map { "\($0.host() ?? ""):\($0.port ?? 8080)" } ?? ""
                discovery.start()
            }
            .onDisappear { discovery.stop() }
        }
    }

    private func use(_ service: ServiceDiscovery.Service) async {
        checking = true
        message = nil
        do {
            let url = try await ServiceDiscovery.resolve(service)
            await connect(url)
        } catch {
            checking = false
            message = error.localizedDescription
        }
    }

    private func use(text: String) async {
        guard let url = HCPClient.url(from: text) else {
            message = HCPError.invalidURL.localizedDescription
            return
        }
        checking = true
        message = nil
        await connect(url)
    }

    private func connect(_ url: URL) async {
        do {
            _ = try await HCPClient(baseURL: url).status()
            store.baseURL = url
            await store.refresh()
            checking = false
            dismiss()
        } catch {
            checking = false
            message = error.localizedDescription
        }
    }
}
