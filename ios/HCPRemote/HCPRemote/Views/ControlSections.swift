import SwiftUI

struct TemperatureSection: View {
    let status: ControllerStatus

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHeader(title: "温度", tag: "SENSORS", icon: "thermometer.medium")
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
                ForEach(SensorRole.allCases) { role in
                    TemperatureTile(role: role, reading: status.reading(role),
                                    highlight: role == .mainReturn && status.mode == .auto,
                                    target: status.targetTemperature,
                                    band: status.targetRange.upperBand)
                }
            }
        }
        .techCard()
    }
}

private struct TemperatureTile: View {
    let role: SensorRole
    let reading: SensorReading?
    let highlight: Bool
    let target: Int
    let band: Int

    /// Rough scale for the mini meter under each value.
    private let scale = 10.0...80.0

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 14, style: .continuous)
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Circle().fill(role.color).frame(width: 6, height: 6)
                    .shadow(color: role.color, radius: 3)
                Text(role.title).font(.caption).foregroundStyle(.secondary)
            }
            if let value = reading?.value {
                HStack(alignment: .firstTextBaseline, spacing: 2) {
                    Text(value, format: .number.precision(.fractionLength(1)))
                        .font(Theme.bigNumber(26, weight: .regular))
                        .contentTransition(.numericText())
                    Text("°C").font(.caption2).foregroundStyle(.secondary)
                }
                GeometryReader { geo in
                    let f = min(1, max(0, (value - scale.lowerBound) / (scale.upperBound - scale.lowerBound)))
                    ZStack(alignment: .leading) {
                        Capsule().fill(Color.white.opacity(0.07))
                        Capsule()
                            .fill(LinearGradient(colors: [role.color.opacity(0.35), role.color],
                                                 startPoint: .leading, endPoint: .trailing))
                            .frame(width: max(4, geo.size.width * f))
                            .shadow(color: role.color.opacity(0.6), radius: 3)
                    }
                }
                .frame(height: 3)
            } else {
                Text("--").font(Theme.bigNumber(26, weight: .regular)).foregroundStyle(Theme.danger)
            }
            if highlight {
                Text("目标 \(target)–\(target + band) °C").font(.caption2).foregroundStyle(role.color)
            } else if reading?.ok == false {
                Text("无读数").font(.caption2).foregroundStyle(Theme.danger)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(highlight ? role.color.opacity(0.10) : Theme.well, in: shape)
        .overlay(shape.strokeBorder(highlight ? role.color.opacity(0.45) : Theme.stroke, lineWidth: 1))
        .accessibilityElement(children: .combine)
    }
}

struct ModeSection: View {
    @Environment(ControllerStore.self) private var store
    let status: ControllerStatus
    @State private var confirmOff = false
    @State private var confirmOn: ControlMode?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHeader(title: "模式", tag: "MODE", icon: "slider.horizontal.3")
            TechSegmented(options: ControlMode.allCases.map {
                SegmentOption(value: $0, title: $0.title, icon: $0.icon, tint: $0.tint)
            }, selection: Binding(
                get: { status.mode },
                set: { mode in
                    guard mode != status.mode else { return }
                    if mode == .off {
                        confirmOff = true
                    } else if status.mode == .off {
                        confirmOn = mode
                    } else {
                        Task { await store.setMode(mode) }
                    }
                }))
            .disabled(store.isSending)
            if let night = status.nightSaver {
                NightSaverRow(night: night, mode: status.mode)
            }
            Group {
                if status.waterTank != nil {
                    Text("热水箱加热期间阀门由热水控制器控制，切换的模式在加热结束后生效。")
                } else {
                    modeFooter
                }
            }
            .font(.caption).foregroundStyle(.secondary)
        }
        .techCard()
        .confirmationDialog("关闭暖气？", isPresented: $confirmOff, titleVisibility: .visible) {
            Button("关闭暖气（阀门完全关闭）", role: .destructive) {
                Task { await store.setMode(.off) }
            }
        }
        .alert("打开暖气？", isPresented: Binding(
            get: { confirmOn != nil },
            set: { if !$0 { confirmOn = nil } }), presenting: confirmOn) { mode in
            Button("取消", role: .cancel) {}
            Button("切换到「\(mode.title)」") {
                Task { await store.setMode(mode) }
            }
        } message: { mode in
            switch mode {
            case .auto: Text("阀门会打开到起始开度，之后按主管回水温度自动调节。")
            case .manual: Text("切换后阀门将按你设定的开度打开，过热保护仍然有效。")
            case .off: Text("")
            }
        }
    }

    @ViewBuilder private var modeFooter: some View {
        switch status.mode {
        case .off: Text("暖气关闭：阀门已完全关闭。")
        case .auto: Text("自动按主管回水温度调节阀门。")
        case .manual: Text("手动设定阀门开度；过热保护仍然有效。")
        }
    }
}

private struct NightSaverRow: View {
    @Environment(ControllerStore.self) private var store
    let night: NightSaver
    let mode: ControlMode

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 14, style: .continuous)
        VStack(alignment: .leading, spacing: 6) {
            Toggle(isOn: Binding(
                get: { night.enabled },
                set: { on in Task { await store.setNightSaver(on) } })) {
                Label("夜间节能", systemImage: night.active ? "moon.zzz.fill" : "moon.fill")
                    .font(.subheadline.weight(.semibold))
            }
            .tint(Theme.accent)
            .disabled(store.isSending)
            Text(footer).font(.caption).foregroundStyle(night.active && mode != .off ? Theme.accent : .secondary)
        }
        .padding(12)
        .background(Theme.well, in: shape)
        .overlay(shape.strokeBorder(Theme.stroke, lineWidth: 1))
    }

    private var footer: String {
        if !night.enabled { return "开启后每天 \(night.start)–\(night.end) 自动关闭暖气。" }
        if night.active && mode != .off { return "夜间节能中：暖气已关闭，\(night.end) 自动恢复「\(mode.title)」。" }
        return "每天 \(night.start)–\(night.end) 自动关闭暖气，之后恢复当前模式。"
    }
}

struct TargetSection: View {
    @Environment(ControllerStore.self) private var store
    let status: ControllerStatus
    @State private var pending: Int?
    @State private var sendTask: Task<Void, Never>?

    private var shown: Int { pending ?? status.targetTemperature }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHeader(title: "目标温度", tag: "SETPOINT", icon: "scope")
            HStack {
                roundButton("minus") { change(-1) }
                    .disabled(shown <= status.targetRange.min)
                Spacer()
                VStack(spacing: 2) {
                    HStack(alignment: .firstTextBaseline, spacing: 2) {
                        Text("\(shown)")
                            .font(Theme.bigNumber(56, weight: .thin))
                            .contentTransition(.numericText(value: Double(shown)))
                            .shadow(color: Theme.accent.opacity(0.5), radius: 12)
                        Text("°C").font(.title3.weight(.light)).foregroundStyle(.secondary)
                    }
                    Text(pending == nil ? "主管回水目标温度" : "正在发送…")
                        .font(.caption).foregroundStyle(pending == nil ? Color.secondary : Theme.accent)
                }
                .animation(.snappy, value: shown)
                Spacer()
                roundButton("plus") { change(1) }
                    .disabled(shown >= status.targetRange.max)
            }
            SegmentMeter(fraction: Double(shown - status.targetRange.min)
                            / Double(max(1, status.targetRange.max - status.targetRange.min)),
                         segments: status.targetRange.max - status.targetRange.min + 1, height: 6)
            Text("温度越高暖气越热。范围 \(status.targetRange.min)–\(status.targetRange.max) °C。")
                .font(.caption).foregroundStyle(.secondary)
        }
        .techCard()
    }

    private func roundButton(_ icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.title3.weight(.semibold))
                .frame(width: 52, height: 52)
        }
        .buttonStyle(RoundButtonStyle())
    }

    /// Collects quick taps and sends only the final value.
    private func change(_ delta: Int) {
        let value = min(status.targetRange.max, max(status.targetRange.min, shown + delta))
        pending = value
        sendTask?.cancel()
        sendTask = Task {
            try? await Task.sleep(for: .milliseconds(700))
            guard !Task.isCancelled else { return }
            await store.setTarget(value)
            if pending == value { pending = nil }  // a newer tap may be waiting to be sent
        }
    }
}

private struct RoundButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        RoundBody(configuration: configuration)
    }

    private struct RoundBody: View {
        let configuration: Configuration
        @Environment(\.isEnabled) private var isEnabled

        var body: some View {
            configuration.label
                .foregroundStyle(Theme.accent)
                .background(Circle().fill(Theme.accent.opacity(configuration.isPressed ? 0.3 : 0.12)))
                .overlay(Circle().strokeBorder(Theme.accent.opacity(0.4), lineWidth: 1))
                .shadow(color: Theme.accent.opacity(configuration.isPressed ? 0.6 : 0.2), radius: 10)
                .scaleEffect(configuration.isPressed ? 0.92 : 1)
                .opacity(isEnabled ? 1 : 0.3)
                .animation(.snappy(duration: 0.15), value: configuration.isPressed)
        }
    }
}

struct ValveSection: View {
    @Environment(ControllerStore.self) private var store
    let status: ControllerStatus
    @State private var slider: Double?
    @Binding var showZeroCalibration: Bool

    private var valve: ValveStatus { status.valve }
    private var takenOver: Bool { status.waterTank != nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            CardHeader(title: "阀门", tag: "VALVE", icon: "dial.medium") {
                if let moving = valve.moving, !takenOver {
                    Label(moving == "up" ? "开大中" : "关小中",
                          systemImage: moving == "up" ? "arrow.up" : "arrow.down")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Theme.accent)
                        .symbolEffect(.pulse)
                }
            }
            if takenOver {
                takenOverRow
            } else {
                positionRow
            }
            if status.mode == .manual && !takenOver && status.phase != "night_saver" {
                HStack(spacing: 8) {
                    stepButton(-10, "−10")
                    stepButton(-1, "−1")
                    Spacer()
                    stepButton(1, "+1")
                    stepButton(10, "+10")
                }
                positionSlider
                if let slider {
                    Text("松手后移动到 \(Int(slider))").font(.caption).foregroundStyle(Theme.heat)
                }
            }
            if !store.history.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("开度变化（步）").font(.caption).foregroundStyle(.secondary)
                    ValveChart(points: store.history)
                        .frame(height: 110)
                }
            }
            VStack(spacing: 0) {
                if status.zeroCalibration != nil {
                    Button { showZeroCalibration = true } label: {
                        LinkRow(title: "继续设置零点…", icon: "scope", tint: Theme.warning)
                    }
                    .buttonStyle(.plain)
                    Divider().overlay(Theme.stroke)
                }
                NavigationLink {
                    ValveMaintenanceView(showZeroCalibration: $showZeroCalibration)
                } label: {
                    LinkRow(title: "零点与重新计数", icon: "wrench.and.screwdriver")
                }
                .buttonStyle(.plain)
            }
        }
        .techCard()
    }

    private var takenOverRow: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("热水控制器接管", systemImage: "drop.fill")
                .font(.headline)
                .foregroundStyle(Theme.accent)
            Text("热水箱加热时阀门被开满，实际位置未知。本控制器暂停操作阀门，手动、设置零点和重新计数暂不可用。")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    private var positionRow: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 2) {
                Text("\(valve.percent)")
                    .font(Theme.bigNumber(44, weight: .thin))
                    .contentTransition(.numericText(value: Double(valve.percent)))
                Text("%").font(.title3.weight(.light)).foregroundStyle(.secondary)
                Spacer()
                VStack(alignment: .trailing, spacing: 2) {
                    Text("\(valve.position) / \(valve.max)")
                        .font(.subheadline.weight(.semibold).monospacedDigit())
                    Text("STEPS").font(Theme.tag).tracking(1.4).foregroundStyle(.tertiary)
                }
            }
            SegmentMeter(fraction: Double(Swift.max(0, valve.position)) / Double(Swift.max(1, valve.max)),
                         tint: status.mode == .manual ? Theme.heat : Theme.accent)
            Group {
                if valve.position < 0 {
                    Text("低于零点 \(-valve.position) 步：无水流")
                }
                if status.mode == .auto {
                    Text("自动范围 \(valve.autoMin)–\(valve.autoMax)")
                }
                if let target = valve.manualTarget, target != valve.position {
                    Text("正在移动到 \(target)").foregroundStyle(Theme.accent)
                }
            }
            .font(.caption).foregroundStyle(.secondary)
        }
    }

    private var sliderBinding: Binding<Double> {
        let current = Double(valve.manualTarget ?? valve.position)
        return Binding(get: { slider ?? current }, set: { slider = $0 })
    }

    private var positionSlider: some View {
        Slider(value: sliderBinding, in: Double(valve.min)...Double(valve.max), step: 1) {
            Text("阀门位置")
        } minimumValueLabel: {
            Image(systemName: "drop")
        } maximumValueLabel: {
            Image(systemName: "drop.fill")
        } onEditingChanged: { editing in
            guard !editing, let value = slider else { return }
            Task {
                await store.moveValve(to: Int(value))
                slider = nil
            }
        }
        .tint(Theme.heat)
    }

    private func stepButton(_ steps: Int, _ title: String) -> some View {
        Button(title) { Task { await store.moveValve(steps: steps) } }
            .buttonStyle(ChipButtonStyle(tint: Theme.heat))
    }
}

/// Rarely used valve maintenance: zero point and recount, kept off the dashboard.
struct ValveMaintenanceView: View {
    @Environment(ControllerStore.self) private var store
    @State private var confirmCalibrate = false
    @Binding var showZeroCalibration: Bool

    var body: some View {
        List {
            if let status = store.status {
                let takenOver = status.waterTank != nil
                Section {
                    LabeledContent("零点") {
                        Text("离完全关闭 \(status.valve.zeroOffset) 步").monospacedDigit()
                    }
                    Button(status.zeroCalibration == nil ? "设置零点（刚有水流的位置）…" : "继续设置零点…") {
                        showZeroCalibration = true
                    }
                    .disabled(status.phase == "relay_fault" || takenOver)
                } footer: {
                    Text("开度从零点（刚有水流通过）算起，1 步 = 继电器通电 0.5 秒。")
                }
                .listRowBackground(Theme.row)
                Section {
                    Button("重新计数（关到底）…") { confirmCalibrate = true }
                        .disabled(status.busy != nil || status.zeroCalibration != nil || takenOver)
                } footer: {
                    Text("「重新计数」把阀门关到底消除累计误差，零点不变，约 1 分钟。")
                }
                .listRowBackground(Theme.row)
                if takenOver {
                    Text("热水箱加热期间暂不可用。").font(.caption).foregroundStyle(.secondary)
                        .listRowBackground(Theme.row)
                }
            }
        }
        .techList()
        .navigationTitle("阀门维护")
        .confirmationDialog("重新计数？", isPresented: $confirmCalibrate, titleVisibility: .visible) {
            Button("重新计数（暂时完全关闭）") { Task { await store.calibrate() } }
        } message: {
            Text("阀门会先完全关闭，然后恢复当前模式。")
        }
    }
}
