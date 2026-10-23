import SwiftUI

@main
struct HCPRemoteApp: App {
    @State private var store = ControllerStore()

    var body: some Scene {
        WindowGroup {
            DashboardView()
                .environment(store)
        }
    }
}
