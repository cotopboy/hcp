import Charts
import SwiftUI

struct HistoryView: View {
    @Environment(ControllerStore.self) private var store
    @State private var hours: Double = 6
    @State private var points: [HistoryPoint] = []
    @State private var error: String?
    @State private var visible: Set<SensorRole> = [.mainReturn, .heatingInlet, .mainInlet]

    var body: some View {
        List {
            Section {
                Picker("时间范围", selection: $hours) {
                    Text("1 小时").tag(1.0)
                    Text("6 小时").tag(6.0)
                    Text("24 小时").tag(24.0)
                    Text("48 小时").tag(48.0)
                }
                .pickerStyle(.segmented)
            }
            if let error {
                Text(error).foregroundStyle(.red)
            }
            Section("温度 °C") {
                Chart {
                    ForEach(SensorRole.allCases.filter(visible.contains)) { role in
                        ForEach(points, id: \.t) { p in
                            if let v = p.value(role) {
                                LineMark(x: .value("时间", p.date), y: .value("°C", v),
                                         series: .value("传感器", role.title))
                                    .foregroundStyle(by: .value("传感器", role.title))
                            }
                        }
                    }
                    if let target = store.status?.targetTemperature, visible.contains(.mainReturn) {
                        RuleMark(y: .value("目标", target))
                            .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
                            .foregroundStyle(.secondary)
                    }
                }
                .chartYScale(domain: .automatic(includesZero: false))
                .frame(height: 260)
                ForEach(SensorRole.allCases) { role in
                    Toggle(role.title, isOn: Binding(
                        get: { visible.contains(role) },
                        set: { on in if on { visible.insert(role) } else { visible.remove(role) } }))
                }
            }
            Section("阀门开度（步）") {
                Chart(points, id: \.t) { p in
                    LineMark(x: .value("时间", p.date), y: .value("步", p.valve))
                        .interpolationMethod(.stepEnd)
                }
                .frame(height: 140)
            }
        }
        .navigationTitle("温度曲线")
        .task(id: hours) { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        guard let client = store.client else { return }
        do {
            points = try await client.history(hours: hours).points
            error = nil
        } catch is CancellationError {
        } catch {
            self.error = error.localizedDescription
        }
    }
}

struct EventsView: View {
    @Environment(ControllerStore.self) private var store
    @State private var events: [ControllerEvent] = []
    @State private var error: String?

    var body: some View {
        List {
            if let error {
                Text(error).foregroundStyle(.red)
            }
            ForEach(events) { e in
                VStack(alignment: .leading, spacing: 2) {
                    Text(e.message)
                        .foregroundStyle(e.level == "critical" ? .red : e.level == "warning" ? .orange : .primary)
                    Text(e.date, format: .dateTime.month().day().hour().minute().second())
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .overlay {
            if events.isEmpty && error == nil { ContentUnavailableView("暂无事件", systemImage: "tray") }
        }
        .navigationTitle("事件记录")
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        guard let client = store.client else { return }
        do {
            events = try await client.events().events
            error = nil
        } catch is CancellationError {
        } catch {
            self.error = error.localizedDescription
        }
    }
}
