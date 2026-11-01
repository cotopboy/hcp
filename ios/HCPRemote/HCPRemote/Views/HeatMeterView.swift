import Charts
import SwiftData
import SwiftUI

private let kWhFormat = FloatingPointFormatStyle<Double>.number.precision(.fractionLength(0...2))
private let rateFormat = FloatingPointFormatStyle<Double>.number.precision(.fractionLength(1))

/// Heating meter log: manual readings kept on the phone, turned into daily and monthly usage.
struct HeatMeterView: View {
    @Environment(\.modelContext) private var context
    @Query(sort: \HeatMeterReading.date, order: .reverse) private var readings: [HeatMeterReading]
    @State private var editing: HeatMeterReading?
    @State private var adding = false
    @State private var chartDays = 30

    private var segments: [MeterSegment] { HeatUsage.segments(readings.map { ($0.date, $0.kWh) }) }

    var body: some View {
        let segments = segments
        let daily = HeatUsage.daily(segments)
        let monthly = HeatUsage.monthly(daily)
        List {
            Section {
                SummaryCard(latest: readings.first, segments: segments, monthly: monthly) { adding = true }
                    .cardRow()
                if !daily.isEmpty {
                    DailyChartCard(daily: daily, days: $chartDays)
                        .cardRow()
                }
            }
            if !monthly.isEmpty {
                Section("按月") {
                    ForEach(monthly) { MonthRow(month: $0) }
                }
            }
            if !segments.isEmpty {
                Section("分段") {
                    ForEach(segments.reversed()) { SegmentRow(segment: $0) }
                }
            }
            if !readings.isEmpty {
                Section {
                    ForEach(readings) { r in
                        Button { editing = r } label: { ReadingRow(reading: r) }
                            .buttonStyle(.plain)
                            .listRowBackground(Theme.row)
                            .swipeActions {
                                Button(role: .destructive) { context.delete(r) } label: {
                                    Label("删除", systemImage: "trash")
                                }
                            }
                    }
                } header: {
                    Text("读数记录")
                } footer: {
                    Text("左滑删除，点一下修改。数据只保存在这台手机上。")
                }
            }
        }
        .techList()
        .navigationTitle("暖气表读数")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { adding = true } label: { Image(systemName: "plus") }
                    .accessibilityLabel("登记读数")
            }
        }
        .sheet(isPresented: $adding) { ReadingForm(reading: nil, all: readings) }
        .sheet(item: $editing) { ReadingForm(reading: $0, all: readings) }
    }
}

private extension View {
    func cardRow() -> some View {
        listRowBackground(Color.clear)
            .listRowInsets(EdgeInsets(top: 7, leading: 0, bottom: 7, trailing: 0))
            .listRowSeparator(.hidden)
    }
}

// MARK: - Cards

private struct SummaryCard: View {
    let latest: HeatMeterReading?
    let segments: [MeterSegment]
    let monthly: [MonthlyUsage]
    let onAdd: () -> Void

    private var thisMonth: MonthlyUsage? {
        monthly.first { Calendar.current.isDate($0.month, equalTo: .now, toGranularity: .month) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            CardHeader(title: "暖气表", tag: "kWh", icon: "flame", tint: Theme.heat)
            if let latest {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(latest.kWh, format: kWhFormat).font(Theme.bigNumber(40))
                        Text("kWh").font(.subheadline).foregroundStyle(.secondary)
                    }
                    Text("最新读数 · \(latest.date.formatted(.dateTime.month().day().hour().minute()))（\(latest.date.formatted(.relative(presentation: .named)))）")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let last = segments.last {
                    HStack(spacing: 10) {
                        stat("最近日均", last.isNegative ? "--" : last.perDay.formatted(rateFormat), "kWh/天")
                        stat(thisMonth?.estimated == true ? "本月（含估算）" : "本月", thisMonth?.kWh.formatted(rateFormat) ?? "--", "kWh")
                    }
                } else {
                    Label("再登记一次读数，就能算出用量。", systemImage: "info.circle")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            } else {
                Text("不用每天读表，想起来就看一眼登记一下，两次读数之间的用量会按天平均算出来。")
                    .font(.footnote).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Button(action: onAdd) {
                Label("登记读数", systemImage: "square.and.pencil").frame(maxWidth: .infinity)
            }
            .buttonStyle(ChipButtonStyle(tint: Theme.heat, prominent: true))
        }
        .techCard(glow: Theme.heat)
    }

    private func stat(_ label: String, _ value: String, _ unit: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(value).font(Theme.bigNumber(22, weight: .regular))
                Text(unit).font(.caption2).foregroundStyle(.secondary)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.well, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

private struct DailyChartCard: View {
    let daily: [DailyUsage]
    @Binding var days: Int

    private var shown: [DailyUsage] {
        guard days > 0, let start = Calendar.current.date(byAdding: .day, value: -days, to: .now) else { return daily }
        return daily.filter { $0.day >= Calendar.current.startOfDay(for: start) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHeader(title: "每日用量", tag: "kWh/DAY", icon: "chart.bar.xaxis", tint: Theme.heat)
            TechSegmented(options: [SegmentOption(value: 30, title: "30天"),
                                    SegmentOption(value: 90, title: "90天"),
                                    SegmentOption(value: 0, title: "全部")],
                          selection: $days, compact: true)
            Chart(shown) { d in
                BarMark(x: .value("日期", d.day, unit: .day), y: .value("kWh", d.kWh))
                    .foregroundStyle(d.estimated ? Theme.heat.opacity(0.35) : Theme.heat)
            }
            .chartXAxis {
                AxisMarks(values: .automatic(desiredCount: 4)) {
                    AxisGridLine().foregroundStyle(Color.white.opacity(0.06))
                    AxisValueLabel(format: .dateTime.month(.defaultDigits).day())
                        .foregroundStyle(Color.secondary).font(.caption2.monospacedDigit())
                }
            }
            .chartYAxis {
                AxisMarks(position: .leading, values: .automatic(desiredCount: 4)) {
                    AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5, dash: [2, 3]))
                        .foregroundStyle(Color.white.opacity(0.1))
                    AxisValueLabel().foregroundStyle(Color.secondary).font(.caption2.monospacedDigit())
                }
            }
            .frame(height: 200)
            if daily.contains(where: \.estimated) {
                Label("浅色柱子是按最近日均估算的（最后一次读数之后）。", systemImage: "info.circle")
                    .font(.caption2).foregroundStyle(.secondary)
            }
        }
        .techCard()
    }
}

// MARK: - Rows

private struct MonthRow: View {
    let month: MonthlyUsage

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(month.month, format: .dateTime.year().month(.wide)).font(.subheadline)
                Text("\(month.days) 天有数据 · 日均 \(month.perDay.formatted(rateFormat)) kWh")
                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            }
            Spacer()
            if month.estimated {
                Text("估算").font(Theme.tag).foregroundStyle(Theme.warning)
                    .padding(.horizontal, 6).padding(.vertical, 3)
                    .background(Theme.warning.opacity(0.14), in: Capsule())
            }
            Text("\(month.kWh.formatted(rateFormat)) kWh").font(.subheadline.weight(.semibold).monospacedDigit())
        }
        .listRowBackground(Theme.row)
    }
}

private struct SegmentRow: View {
    let segment: MeterSegment

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("\(segment.start.formatted(.dateTime.month(.defaultDigits).day())) → \(segment.end.formatted(.dateTime.month(.defaultDigits).day()))")
                    .font(.subheadline.monospacedDigit())
                Text("\(segment.days.formatted(rateFormat)) 天 · 共 \(segment.consumption.formatted(kWhFormat)) kWh")
                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            }
            Spacer()
            if segment.isNegative {
                Label("读数变小了", systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(Theme.danger)
            } else {
                Text("\(segment.perDay.formatted(rateFormat)) kWh/天")
                    .font(.subheadline.weight(.semibold).monospacedDigit()).foregroundStyle(Theme.heat)
            }
        }
        .listRowBackground(Theme.row)
    }
}

private struct ReadingRow: View {
    let reading: HeatMeterReading

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(reading.date, format: .dateTime.year().month().day().hour().minute())
                    .font(.subheadline.monospacedDigit())
                if !reading.note.isEmpty {
                    Text(reading.note).font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer()
            Text("\(reading.kWh.formatted(kWhFormat)) kWh").font(.subheadline.monospacedDigit())
        }
        .contentShape(Rectangle())
    }
}

// MARK: - Form

private struct ReadingForm: View {
    let reading: HeatMeterReading?
    let all: [HeatMeterReading]
    @Environment(\.modelContext) private var context
    @Environment(\.dismiss) private var dismiss
    @State private var date = Date.now
    @State private var text = ""
    @State private var note = ""
    @FocusState private var valueFocused: Bool

    /// Accepts both "1234.5" and "1234,5".
    private var value: Double? {
        Double(text.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: ",", with: "."))
    }

    private var warning: String? {
        guard let value else { return nil }
        let others = all.filter { $0 !== reading }
        if let before = others.filter({ $0.date < date }).max(by: { $0.date < $1.date }), value < before.kWh {
            return "比之前的读数 \(before.kWh.formatted(kWhFormat)) kWh 还小，是不是输错了？"
        }
        if let after = others.filter({ $0.date > date }).min(by: { $0.date < $1.date }), value > after.kWh {
            return "比之后的读数 \(after.kWh.formatted(kWhFormat)) kWh 还大，是不是输错了？"
        }
        return nil
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack {
                        TextField("读数", text: $text)
                            .keyboardType(.decimalPad)
                            .font(Theme.bigNumber(28, weight: .regular))
                            .focused($valueFocused)
                        Text("kWh").foregroundStyle(.secondary)
                    }
                    if let warning {
                        Label(warning, systemImage: "exclamationmark.triangle.fill")
                            .font(.footnote).foregroundStyle(Theme.warning)
                    }
                }
                .listRowBackground(Theme.row)
                Section {
                    DatePicker("读数时间", selection: $date, in: ...Date.now)
                    TextField("备注（可不填）", text: $note)
                }
                .listRowBackground(Theme.row)
            }
            .techList()
            .navigationTitle(reading == nil ? "登记读数" : "修改读数")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存", action: save).disabled(value == nil)
                }
            }
            .onAppear {
                if let reading {
                    date = reading.date
                    text = reading.kWh.formatted(.number.grouping(.never).precision(.fractionLength(0...3)))
                    note = reading.note
                } else {
                    valueFocused = true
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func save() {
        guard let value else { return }
        let trimmed = note.trimmingCharacters(in: .whitespaces)
        if let reading {
            reading.date = date
            reading.kWh = value
            reading.note = trimmed
        } else {
            context.insert(HeatMeterReading(date: date, kWh: value, note: trimmed))
        }
        dismiss()
    }
}

#Preview {
    NavigationStack { HeatMeterView() }
        .modelContainer(for: HeatMeterReading.self, inMemory: true)
        .preferredColorScheme(.dark)
}
