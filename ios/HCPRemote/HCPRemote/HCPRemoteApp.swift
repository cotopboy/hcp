import SwiftUI

@main
struct HCPRemoteApp: App {
    @State private var store = ControllerStore()

    var body: some Scene {
        WindowGroup {
            DashboardView()
                .environment(store)
                .preferredColorScheme(.dark)
                .tint(Theme.accent)
        }
    }
}
