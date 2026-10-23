import SwiftUI

struct TemperatureSection: View {
    let status: ControllerStatus

    var body: some View {
        Section("温度") {
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                ForEach(SensorRole.allCases) { role in
                    TemperatureTile(role: role, reading: status.reading(role),
                                    highlight: role == .mainReturn && status.mode == .auto,
                                    target: status.targetTemperature,
                                    band: status.targetRange.upperBand)
                }
            }
            .padding(.vertical, 4)
        }
    }
}

private struct TemperatureTile: View {
    let role: SensorRole
    let reading: SensorReading?
    let highlight: Bool
    let target: Int
    let band: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(role.title).font(.caption).foregroundStyle(.secondary)
            if let value = reading?.value {
                Text(value, format: .number.precision(.fractionLength(1)))
                    .font(.title2.monospacedDigit().weight(.semibold))
                + Text(" °C").font(.caption).foregroundStyle(.secondary)
            } else {
                Text("--").font(.title2.weight(.semibold)).foregroundStyle(.red)
            }
            if highlight {
                Text("目标 \(target)–\(target + band) °C").font(.caption2).foregroundStyle(.secondary)
            } else if reading?.ok == false {
                Text("无读数").font(.caption2).foregroundStyle(.red)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(highlight ? Color.accentColor.opacity(0.12) : Color.secondary.opacity(0.08),
                    in: RoundedRectangle(cornerRadius: 10))
        .accessibilityElement(children: .combine)
    }
}

struct ModeSection: View {
    @Environment(ControllerStore.self) private var store
    let status: ControllerStatus
    @State private var confirmOff = false

    var body: some View {
        Section {
            Picker("模式", selection: Binding(
                get: { status.mode },
                set: { mode in
                    if mode == .off { confirmOff = true } else { Task { await store.setMode(mode) } }
                })) {
                ForEach(ControlMode.allCases) { Text($0.title).tag($0) }
            }
            .pickerStyle(.segmented)
            .disabled(store.isSending)
        } header: {
            Text("模式")
        } footer: {
            switch status.mode {
            case .off: Text("暖气关闭：阀门已完全关闭。")
            case .auto: Text("自动按主管回水温度调节阀门。")
            case .manual: Text("手动设定阀门开度；过热保护仍然有效。")
            }
        }
        .confirmationDialog("关闭暖气？", isPresented: $confirmOff, titleVisibility: .visible) {
            Button("关闭暖气（阀门完全关闭）", role: .destructive) {
                Task { await store.setMode(.off) }
            }
        }
    }
}

struct TargetSection: View {
    @Environment(ControllerStore.self) private var store
    let status: ControllerStatus
    @State private var pending: Int?
    @State private var sendTask: Task<Void, Never>?

    private var shown: Int { pending ?? status.targetTemperature }

    var body: some View {
        Section {
            HStack {
                Button { change(-1) } label: { Image(systemName: "minus.circle.fill") }
                    .disabled(shown <= status.targetRange.min)
                Spacer()
                VStack {
                    Text("\(shown) °C").font(.largeTitle.monospacedDigit().weight(.semibold))
                    Text(pending == nil ? "主管回水目标温度" : "正在发送…")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button { change(1) } label: { Image(systemName: "plus.circle.fill") }
                    .disabled(shown >= status.targetRange.max)
            }
            .font(.largeTitle)
            .buttonStyle(.borderless)
        } header: {
            Text("目标温度")
        } footer: {
            Text("温度越高暖气越热。范围 \(status.targetRange.min)–\(status.targetRange.max) °C。")
        }
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

struct ValveSection: View {
    @Environment(ControllerStore.self) private var store
    let status: ControllerStatus
    @State private var slider: Double?
    @State private var confirmCalibrate = false

    private var valve: ValveStatus { status.valve }

    var body: some View {
        Section {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("阀门开度")
                    Spacer()
                    Text("\(valve.percent)%").monospacedDigit().fontWeight(.semibold)
                    Text("(\(valve.position)/\(valve.max))").font(.caption).foregroundStyle(.secondary)
                    if let moving = valve.moving {
                        Image(systemName: moving == "up" ? "arrow.up" : "arrow.down")
                            .foregroundStyle(Color.accentColor)
                    }
                }
                ProgressView(value: Double(valve.position), total: Double(valve.max))
                if status.mode == .auto {
                    Text("自动范围 \(valve.autoMin)–\(valve.autoMax)").font(.caption).foregroundStyle(.secondary)
                }
                if let target = valve.manualTarget, target != valve.position {
                    Text("正在移动到 \(target)").font(.caption).foregroundStyle(.secondary)
                }
            }
            if status.mode == .manual {
                HStack {
                    stepButton(-10, "−10")
                    stepButton(-1, "−1")
                    Spacer()
                    stepButton(1, "+1")
                    stepButton(10, "+10")
                }
                .buttonStyle(.bordered)
                positionSlider
                if let slider {
                    Text("松手后移动到 \(Int(slider))").font(.caption).foregroundStyle(.secondary)
                }
            }
            Button("校准阀门…") { confirmCalibrate = true }
                .disabled(status.busy != nil)
        } header: {
            Text("阀门")
        } footer: {
            Text("1 步 = 继电器通电 0.5 秒。校准会先把阀门完全关闭再重新计数，约需 1 分钟。")
        }
        .confirmationDialog("校准阀门？", isPresented: $confirmCalibrate, titleVisibility: .visible) {
            Button("校准（暂时完全关闭）") { Task { await store.calibrate() } }
        } message: {
            Text("阀门会先完全关闭，然后恢复当前模式。")
        }
    }

    private var sliderBinding: Binding<Double> {
        let current = Double(valve.manualTarget ?? valve.position)
        return Binding(get: { slider ?? current }, set: { slider = $0 })
    }

    private var positionSlider: some View {
        Slider(value: sliderBinding, in: 0...Double(valve.max), step: 1) {
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
    }

    private func stepButton(_ steps: Int, _ title: String) -> some View {
        Button(title) { Task { await store.moveValve(steps: steps) } }
            .monospacedDigit()
    }
}
