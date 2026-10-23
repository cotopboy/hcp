import SwiftUI

struct DashboardView: View {
    @Environment(ControllerStore.self) private var store
    @Environment(\.scenePhase) private var scenePhase
    @State private var showConnection = false

    var body: some View {
        NavigationStack {
            List {
                if let error = store.lastError {
                    Section {
                        Label(error, systemImage: "wifi.exclamationmark")
                            .foregroundStyle(.red)
                    }
                }
                if let status = store.status {
                    StatusHeader(status: status, stale: store.isStale)
                    if !status.alarms.isEmpty {
                        Section("提醒") {
                            ForEach(status.alarms) { AlarmRow(alarm: $0) }
                        }
                    }
                    TemperatureSection(status: status)
                    ModeSection(status: status)
                    if status.mode == .auto {
                        TargetSection(status: status)
                    }
                    ValveSection(status: status)
                    Section {
                        NavigationLink {
                            HistoryView()
                        } label: {
                            Label("温度曲线", systemImage: "chart.xyaxis.line")
                        }
                        NavigationLink {
                            EventsView()
                        } label: {
                            Label("事件记录", systemImage: "list.bullet.rectangle")
                        }
                    }
                } else if store.baseURL == nil {
                    ContentUnavailableView {
                        Label("还没有连接控制器", systemImage: "antenna.radiowaves.left.and.right")
                    } description: {
                        Text("手机需要和树莓派在同一个局域网。")
                    } actions: {
                        Button("连接控制器") { showConnection = true }
                            .buttonStyle(.borderedProminent)
                    }
                } else {
                    HStack {
                        ProgressView()
                        Text("正在连接 \(store.baseURL?.host() ?? "")…")
                    }
                }
            }
            .navigationTitle("暖气")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showConnection = true
                    } label: {
                        Image(systemName: "gearshape")
                    }
                    .accessibilityLabel("连接设置")
                }
            }
            .refreshable { await store.refresh() }
            .sheet(isPresented: $showConnection) {
                ConnectionView()
            }
            .task(id: scenePhase) {
                if scenePhase == .active { await store.poll() }
            }
            .onAppear {
                if store.baseURL == nil { showConnection = true }
            }
        }
    }
}

private struct StatusHeader: View {
    let status: ControllerStatus
    let stale: Bool

    var body: some View {
        Section {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.title2)
                    .foregroundStyle(status.phaseIsProblem ? .red : .accentColor)
                VStack(alignment: .leading, spacing: 2) {
                    Text(status.phaseTitle).font(.headline)
                    if let busy = status.busy {
                        Text(busyTitle(busy)).font(.subheadline).foregroundStyle(.secondary)
                    } else if let d = status.lastDecision, status.mode == .auto {
                        Text("上次判断：\(d.summary)")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if status.busy != nil || status.valve.moving != nil {
                    ProgressView()
                }
            }
            if stale {
                Label("数据可能已过时", systemImage: "clock.badge.exclamationmark")
                    .font(.caption).foregroundStyle(.orange)
            }
        }
    }

    private var icon: String {
        switch status.phase {
        case "idle": "power"
        case "manual": "hand.raised"
        case "overheat": "thermometer.sun.fill"
        case "water_tank": "drop.fill"
        case "sensor_fault", "relay_fault": "exclamationmark.triangle.fill"
        default: "flame"
        }
    }

    private func busyTitle(_ busy: String) -> String {
        switch busy {
        case "calibrating": "正在校准阀门（完全关闭后重新计数，约 1 分钟）"
        case "closing": "正在关闭阀门"
        case "opening to ready position": "正在打开到起始开度"
        case "overheat protection": "过热保护：正在关小阀门"
        default: busy
        }
    }
}

private struct AlarmRow: View {
    let alarm: Alarm

    var body: some View {
        Label {
            VStack(alignment: .leading) {
                Text(alarm.title)
                if alarm.code == "relay_fault" || alarm.code == "sensor_fault" {
                    Text(alarm.message).font(.caption).foregroundStyle(.secondary)
                }
            }
        } icon: {
            Image(systemName: alarm.level == "info" ? "info.circle" : "exclamationmark.triangle.fill")
                .foregroundStyle(color)
        }
    }

    private var color: Color {
        switch alarm.level {
        case "critical": .red
        case "warning": .orange
        default: .blue
        }
    }
}

#Preview {
    DashboardView().environment(ControllerStore())
}
