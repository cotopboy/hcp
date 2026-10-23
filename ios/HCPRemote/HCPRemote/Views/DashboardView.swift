import SwiftUI

struct DashboardView: View {
    @Environment(ControllerStore.self) private var store
    @Environment(\.scenePhase) private var scenePhase
    @State private var showConnection = false
    @State private var showZeroCalibration = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 14) {
                    if let error = store.lastError {
                        Label(error, systemImage: "wifi.exclamationmark")
                            .font(.subheadline)
                            .foregroundStyle(Theme.danger)
                            .techCard(glow: Theme.danger)
                    }
                    if let status = store.status {
                        StatusHeader(status: status, stale: store.isStale)
                        ModeSection(status: status)
                        if !status.alarms.isEmpty {
                            VStack(alignment: .leading, spacing: 12) {
                                CardHeader(title: "提醒", tag: "ALERTS", icon: "bell.badge", tint: Theme.warning)
                                ForEach(status.alarms) { AlarmRow(alarm: $0) }
                            }
                            .techCard(glow: Theme.warning)
                        }
                        TemperatureSection(status: status)
                        if status.mode == .auto {
                            TargetSection(status: status)
                        }
                        TemperatureChartSection()
                        ValveSection(status: status, showZeroCalibration: $showZeroCalibration)
                        NavigationLink {
                            EventsView()
                        } label: {
                            LinkRow(title: "事件记录", icon: "list.bullet.rectangle")
                        }
                        .buttonStyle(.plain)
                        .techCard(padding: 12)
                    } else if store.baseURL == nil {
                        ContentUnavailableView {
                            Label("还没有连接控制器", systemImage: "antenna.radiowaves.left.and.right")
                        } description: {
                            Text("手机需要和树莓派在同一个局域网。")
                        } actions: {
                            Button("连接控制器") { showConnection = true }
                                .buttonStyle(ChipButtonStyle(prominent: true))
                        }
                        .techCard()
                    } else {
                        HStack(spacing: 12) {
                            ProgressView()
                            Text("正在连接 \(store.baseURL?.host() ?? "")…")
                                .font(.subheadline).foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity)
                        .techCard()
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 24)
                .animation(.smooth, value: store.status?.mode)
            }
            .background(TechBackground())
            .navigationTitle("HCP 智控")
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
            .sheet(isPresented: $showZeroCalibration) {
                ZeroCalibrationView()
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

    private var tint: Color {
        if status.phaseIsProblem { return Theme.danger }
        return switch status.mode {
        case .off: Theme.idle
        case .auto: Theme.accent
        case .manual: Theme.heat
        }
    }

    private var lightColor: Color {
        if status.phaseIsProblem { return Theme.danger }
        return stale ? Theme.warning : Theme.ok
    }

    var body: some View {
        let mainReturn = status.reading(.mainReturn)?.value
        let target = Double(status.targetTemperature)
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                PulseDot(color: lightColor, animated: !stale)
                Text(stale ? "OFFLINE?" : "LIVE")
                    .font(Theme.tag).tracking(1.6)
                    .foregroundStyle(lightColor)
                Spacer()
                if status.busy != nil || status.valve.moving != nil {
                    ProgressView().controlSize(.small).tint(tint)
                }
                Label(status.mode.title, systemImage: status.mode.icon)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(status.mode.tint)
                    .padding(.horizontal, 10).padding(.vertical, 5)
                    .background(status.mode.tint.opacity(0.14), in: Capsule())
            }

            HStack(spacing: 16) {
                RingGauge(value: mainReturn,
                          range: Double(status.targetRange.min - 10)...Double(status.targetRange.max + 15),
                          band: status.mode == .auto ? target...(target + Double(status.targetRange.upperBand)) : nil,
                          tint: tint) {
                    VStack(spacing: 0) {
                        if let mainReturn {
                            Text(mainReturn, format: .number.precision(.fractionLength(1)))
                                .font(Theme.bigNumber(34))
                                .contentTransition(.numericText())
                        } else {
                            Text("--").font(Theme.bigNumber(34)).foregroundStyle(Theme.danger)
                        }
                        Text("°C 主管回水").font(.caption2).foregroundStyle(.secondary)
                    }
                }
                .frame(width: 140, height: 140)

                VStack(alignment: .leading, spacing: 10) {
                    Image(systemName: icon)
                        .font(.title3)
                        .foregroundStyle(tint)
                        .shadow(color: tint.opacity(0.7), radius: 8)
                    Text(status.phaseTitle)
                        .font(.headline)
                        .fixedSize(horizontal: false, vertical: true)
                    if status.mode == .auto {
                        stat("目标", "\(status.targetTemperature)–\(status.targetTemperature + status.targetRange.upperBand) °C")
                    }
                    stat("阀门", status.waterTank != nil ? "接管" : "\(status.valve.percent)%")
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            if let detail {
                Text(detail)
                    .font(.footnote).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Theme.well, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            if stale {
                Label("数据可能已过时", systemImage: "clock.badge.exclamationmark")
                    .font(.caption).foregroundStyle(Theme.warning)
            }
        }
        .techCard(glow: tint)
    }

    private var detail: String? {
        if let tank = status.waterTank {
            return "已持续 \(tank.minutes()) 分钟（最长 \(Int(tank.timeoutMinutes)) 分钟）。结束后阀门先关到底重新计数，再恢复「\(status.mode.title)」。"
        } else if let busy = status.busy {
            return busyTitle(busy)
        } else if let d = status.lastDecision, status.mode == .auto {
            return "上次判断：\(d.summary)"
        }
        return nil
    }

    private func stat(_ label: String, _ value: String) -> some View {
        HStack(spacing: 6) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.caption.weight(.semibold).monospacedDigit())
        }
    }

    private var icon: String {
        switch status.phase {
        case "idle": "power"
        case "manual": "hand.raised"
        case "overheat": "thermometer.sun.fill"
        case "water_tank": "drop.fill"
        case "zero_calibration": "scope"
        case "sensor_fault", "relay_fault": "exclamationmark.triangle.fill"
        default: "flame"
        }
    }

    private func busyTitle(_ busy: String) -> String {
        switch busy {
        case "calibrating": "正在校准阀门（完全关闭后重新计数，约 1 分钟）"
        case "closing": "正在关闭阀门"
        case "opening to ready position": "正在打开到起始开度"
        case "closing to end stop": "正在把阀门关到底（约 1 分钟）"
        case "overheat protection": "过热保护：正在关小阀门"
        default: busy
        }
    }
}

private struct AlarmRow: View {
    let alarm: Alarm

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: alarm.level == "info" ? "info.circle" : "exclamationmark.triangle.fill")
                .foregroundStyle(color)
                .shadow(color: color.opacity(0.6), radius: 4)
            VStack(alignment: .leading, spacing: 2) {
                Text(alarm.title).font(.subheadline)
                if alarm.code == "relay_fault" || alarm.code == "sensor_fault" {
                    Text(alarm.message).font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(10)
        .background(color.opacity(0.08), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(alignment: .leading) {
            Capsule().fill(color).frame(width: 3).padding(.vertical, 8)
        }
        .accessibilityElement(children: .combine)
    }

    private var color: Color {
        switch alarm.level {
        case "critical": Theme.danger
        case "warning": Theme.warning
        default: Theme.accent
        }
    }
}

#Preview {
    DashboardView().environment(ControllerStore())
}
