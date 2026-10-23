import Charts
import SwiftUI

private func rangeOptions(_ hours: [Double]) -> [SegmentOption<Double>] {
    hours.map { SegmentOption(value: $0, title: "\(Int($0))H") }
}

/// Temperature curve shown directly on the dashboard; reloads every minute.
struct TemperatureChartSection: View {
    @Environment(ControllerStore.self) private var store
    private let roles: [SensorRole] = [.mainReturn, .heatingInlet, .mainInlet]

    var body: some View {
        @Bindable var store = store
        VStack(alignment: .leading, spacing: 12) {
            CardHeader(title: "温度曲线", tag: "TREND", icon: "waveform.path.ecg")
            TechSegmented(options: rangeOptions([1, 6, 24]), selection: $store.historyHours, compact: true)
            if let error = store.historyError {
                Text(error).font(.caption).foregroundStyle(Theme.danger)
            }
            TemperatureChart(points: store.history, visible: Set(roles),
                             target: store.status?.targetTemperature)
                .frame(height: 220)
                .overlay {
                    if store.history.isEmpty && store.historyError == nil { ProgressView() }
                }
            NavigationLink {
                HistoryView()
            } label: {
                LinkRow(title: "更多曲线（全部传感器、48 小时）", icon: "chart.xyaxis.line")
            }
            .buttonStyle(.plain)
        }
        .techCard()
        .task(id: store.historyHours) { await store.pollHistory() }
    }
}

/// Shared look for chart axes on the dark background.
private struct TechAxes: ViewModifier {
    func body(content: Content) -> some View {
        content
            .chartXAxis {
                AxisMarks(values: .automatic(desiredCount: 4)) {
                    AxisGridLine().foregroundStyle(Color.white.opacity(0.06))
                    AxisValueLabel().foregroundStyle(Color.secondary).font(.caption2.monospacedDigit())
                }
            }
            .chartYAxis {
                AxisMarks(position: .leading, values: .automatic(desiredCount: 4)) {
                    AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5, dash: [2, 3]))
                        .foregroundStyle(Color.white.opacity(0.1))
                    AxisValueLabel().foregroundStyle(Color.secondary).font(.caption2.monospacedDigit())
                }
            }
    }
}

struct ValveChart: View {
    let points: [HistoryPoint]

    var body: some View {
        Chart(points, id: \.t) { p in
            AreaMark(x: .value("时间", p.date), y: .value("步", p.valve))
                .interpolationMethod(.stepEnd)
                .foregroundStyle(LinearGradient(colors: [Theme.accent.opacity(0.35), Theme.accent.opacity(0)],
                                                startPoint: .top, endPoint: .bottom))
            LineMark(x: .value("时间", p.date), y: .value("步", p.valve))
                .interpolationMethod(.stepEnd)
                .foregroundStyle(Theme.accent)
                .lineStyle(StrokeStyle(lineWidth: 1.5))
        }
        .modifier(TechAxes())
    }
}

struct TemperatureChart: View {
    let points: [HistoryPoint]
    let visible: Set<SensorRole>
    let target: Int?
    var showLegend = true

    private var roles: [SensorRole] { SensorRole.allCases.filter(visible.contains) }

    /// Explicit y domain so the area under 主管回水 can start at the bottom of the plot.
    private var domain: ClosedRange<Double> {
        var values = roles.flatMap { role in points.compactMap { $0.value(role) } }
        if let target, visible.contains(.mainReturn) { values.append(Double(target)) }
        guard let lo = values.min(), let hi = values.max() else { return 0...1 }
        let pad = Swift.max(1, (hi - lo) * 0.1)
        return (lo - pad).rounded(.down)...(hi + pad).rounded(.up)
    }

    var body: some View {
        let domain = domain
        Chart {
            if visible.contains(.mainReturn) {
                ForEach(points, id: \.t) { p in
                    if let v = p.value(.mainReturn) {
                        AreaMark(x: .value("时间", p.date), yStart: .value("°C", domain.lowerBound), yEnd: .value("°C", v))
                            .interpolationMethod(.monotone)
                            .foregroundStyle(LinearGradient(colors: [SensorRole.mainReturn.color.opacity(0.28),
                                                                     SensorRole.mainReturn.color.opacity(0)],
                                                            startPoint: .top, endPoint: .bottom))
                    }
                }
            }
            ForEach(roles) { role in
                ForEach(points, id: \.t) { p in
                    if let v = p.value(role) {
                        LineMark(x: .value("时间", p.date), y: .value("°C", v),
                                 series: .value("传感器", role.title))
                            .foregroundStyle(by: .value("传感器", role.title))
                            .interpolationMethod(.monotone)
                            .lineStyle(StrokeStyle(lineWidth: role == .mainReturn ? 2.2 : 1.5, lineCap: .round))
                    }
                }
            }
            if let target, visible.contains(.mainReturn) {
                RuleMark(y: .value("目标", target))
                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
                    .foregroundStyle(Theme.ok.opacity(0.8))
                    .annotation(position: .top, alignment: .trailing) {
                        Text("目标 \(target)°").font(.caption2.monospacedDigit()).foregroundStyle(Theme.ok)
                    }
            }
        }
        .chartForegroundStyleScale(domain: roles.map(\.title), range: roles.map(\.color))
        .chartYScale(domain: domain)
        .chartLegend(showLegend ? .visible : .hidden)
        .chartLegend(position: .bottom, spacing: 10)
        .modifier(TechAxes())
    }
}

struct HistoryView: View {
    @Environment(ControllerStore.self) private var store
    @State private var hours: Double = 6
    @State private var points: [HistoryPoint] = []
    @State private var error: String?
    @State private var visible: Set<SensorRole> = [.mainReturn, .heatingInlet, .mainInlet]

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                TechSegmented(options: rangeOptions([1, 6, 24, 48]), selection: $hours, compact: true)
                if let error {
                    Text(error).font(.subheadline).foregroundStyle(Theme.danger)
                        .techCard(glow: Theme.danger)
                }
                VStack(alignment: .leading, spacing: 12) {
                    CardHeader(title: "温度", tag: "°C", icon: "thermometer.medium")
                    TemperatureChart(points: points, visible: visible, target: store.status?.targetTemperature,
                                     showLegend: false)
                        .frame(height: 280)
                    FlowChips(visible: $visible)
                }
                .techCard()
                VStack(alignment: .leading, spacing: 12) {
                    CardHeader(title: "阀门开度", tag: "STEPS", icon: "dial.medium")
                    ValveChart(points: points)
                        .frame(height: 150)
                }
                .techCard()
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 24)
        }
        .background(TechBackground())
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

/// Tappable sensor chips that toggle chart series.
private struct FlowChips: View {
    @Binding var visible: Set<SensorRole>

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 96), spacing: 8)], alignment: .leading, spacing: 8) {
            ForEach(SensorRole.allCases) { role in
                let on = visible.contains(role)
                Button {
                    withAnimation(.snappy) {
                        if on { visible.remove(role) } else { visible.insert(role) }
                    }
                } label: {
                    HStack(spacing: 6) {
                        Circle().fill(on ? role.color : Color.clear)
                            .overlay(Circle().strokeBorder(role.color, lineWidth: 1.5))
                            .frame(width: 8, height: 8)
                        Text(role.title).font(.caption.weight(.medium))
                    }
                    .foregroundStyle(on ? Color.primary : Color.secondary)
                    .padding(.horizontal, 10).padding(.vertical, 7)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(on ? role.color.opacity(0.14) : Theme.well, in: Capsule())
                    .overlay(Capsule().strokeBorder(on ? role.color.opacity(0.5) : Theme.stroke, lineWidth: 1))
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(on ? .isSelected : [])
            }
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
                Text(error).foregroundStyle(Theme.danger)
                    .listRowBackground(Theme.row)
            }
            ForEach(events) { e in
                HStack(alignment: .top, spacing: 12) {
                    Capsule().fill(color(e.level))
                        .frame(width: 3)
                        .shadow(color: color(e.level).opacity(0.7), radius: 3)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(e.message)
                            .font(.subheadline)
                            .foregroundStyle(e.level == "critical" || e.level == "warning" ? color(e.level) : Color.primary)
                        Text(e.date, format: .dateTime.month().day().hour().minute().second())
                            .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 2)
                .listRowBackground(Theme.row)
            }
        }
        .techList()
        .overlay {
            if events.isEmpty && error == nil { ContentUnavailableView("暂无事件", systemImage: "tray") }
        }
        .navigationTitle("事件记录")
        .task { await load() }
        .refreshable { await load() }
    }

    private func color(_ level: String) -> Color {
        switch level {
        case "critical": Theme.danger
        case "warning": Theme.warning
        default: Theme.accent
        }
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
