import SwiftUI

/// Wizard for the valve zero point: close to the end stop, open step by step while listening
/// at the pipe, and store the position where water starts to flow as the new zero.
struct ZeroCalibrationView: View {
    @Environment(ControllerStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var started = false
    @State private var confirmSet = false
    @State private var result: String?

    private var status: ControllerStatus? { store.status }
    private var calibration: ZeroCalibration? { status?.zeroCalibration }

    var body: some View {
        NavigationStack {
            Form {
                Group {
                    if let result {
                        doneSection(result)
                    } else if let calibration {
                        if calibration.stage == "closing" {
                            closingSection
                        } else {
                            jogSection(calibration)
                        }
                    } else {
                        introSection
                    }
                    if let error = store.lastError {
                        Section { Text(error).foregroundStyle(Theme.danger) }
                    }
                }
                .listRowBackground(Theme.row)
            }
            .techList()
            .navigationTitle("设置阀门零点")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    if calibration != nil && result == nil {
                        Button("取消") { Task { await store.cancelZeroCalibration() } }
                    } else {
                        Button("关闭") { dismiss() }
                    }
                }
            }
            .interactiveDismissDisabled(calibration != nil && result == nil)
            .task {
                // Faster updates than the dashboard so the step counter follows each tap.
                while !Task.isCancelled {
                    await store.refresh()
                    try? await Task.sleep(for: .seconds(1))
                }
            }
            .onChange(of: calibration == nil) { _, finished in
                guard finished, started, result == nil, let valve = status?.valve else { return }
                result = "零点：离完全关闭 \(valve.zeroOffset) 步"
            }
            .confirmationDialog("把当前位置设为零点？", isPresented: $confirmSet, titleVisibility: .visible) {
                Button("设为零点（\(calibration?.target ?? 0) 步）") {
                    Task { await store.setZeroPoint() }
                }
            } message: {
                Text("以后「0」就表示刚有水流通过；自动控制的开度范围会跟着这个零点。")
            }
        }
    }

    private var introSection: some View {
        Section {
            if let valve = status?.valve {
                LabeledContent("当前零点", value: "离完全关闭 \(valve.zeroOffset) 步")
            }
            Text("""
                1. 阀门先完全关到底（约 1 分钟）。
                2. 用 +5 / +1 慢慢打开，同时在阀门旁听水声或摸管子。
                3. 刚有水流通过时，点「设为零点」。

                期间自动控制暂停；取消或 30 分钟没有完成时，零点保持不变并恢复原来的模式。
                """)
                .font(.callout)
            Button("开始：把阀门关到底") {
                started = true
                Task { await store.startZeroCalibration() }
            }
            .disabled(status == nil || store.isSending)
        }
    }

    private var closingSection: some View {
        Section {
            HStack(spacing: 12) {
                ProgressView()
                VStack(alignment: .leading) {
                    Text("正在把阀门关到底…")
                    Text("约 1 分钟，完成后开始点动").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .onAppear { started = true }
    }

    private func jogSection(_ calibration: ZeroCalibration) -> some View {
        Group {
            Section {
                VStack(spacing: 4) {
                    Text("\(calibration.target)")
                        .font(Theme.bigNumber(72, weight: .thin))
                        .contentTransition(.numericText())
                        .shadow(color: Theme.accent.opacity(0.5), radius: 14)
                    Text("离完全关闭的步数（1 步 = 0.5 秒）")
                        .font(.caption).foregroundStyle(.secondary)
                    // Always laid out (just hidden) so the buttons below never jump while tapping.
                    Text("阀门转动中…（当前 \(calibration.absolute)）")
                        .font(.caption).foregroundStyle(Color.accentColor)
                        .opacity(calibration.absolute != calibration.target || status?.valve.moving != nil ? 1 : 0)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
                HStack {
                    jogButton(-1, "−1", disabled: calibration.target <= 0)
                    Spacer()
                    jogButton(1, "+1", disabled: calibration.target >= calibration.maxOffset)
                    jogButton(5, "+5", disabled: calibration.target >= calibration.maxOffset)
                }
                .buttonStyle(ChipButtonStyle())
                .padding(.vertical, 4)
            } footer: {
                Text("一边点 +5 / +1，一边听阀门处的水声或摸管子。最多可设到 \(calibration.maxOffset) 步。")
            }
            Section {
                Button { confirmSet = true } label: {
                    Text("刚有水流：设为零点").frame(maxWidth: .infinity)
                }
                    .buttonStyle(ChipButtonStyle(prominent: true))
                    .disabled(store.isSending || calibration.absolute != calibration.target)
            }
            .onAppear { started = true }
        }
    }

    private func jogButton(_ steps: Int, _ title: String, disabled: Bool) -> some View {
        // Not disabled while a request is in flight: every tap must count.
        Button(title) { Task { await store.zeroJog(steps) } }
            .monospacedDigit()
            .disabled(disabled)
    }

    private func doneSection(_ text: String) -> some View {
        Section {
            Label(text, systemImage: "checkmark.circle.fill").foregroundStyle(Theme.ok)
            Text("阀门已回到当前模式对应的位置。").font(.caption).foregroundStyle(.secondary)
            Button("完成") { dismiss() }
        }
    }
}
