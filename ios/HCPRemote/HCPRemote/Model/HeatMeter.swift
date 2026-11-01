import Foundation
import SwiftData

/// One manual reading of the heating meter, stored only on this phone.
@Model
final class HeatMeterReading {
    var date: Date
    var kWh: Double
    var note: String

    init(date: Date, kWh: Double, note: String = "") {
        self.date = date
        self.kWh = kWh
        self.note = note
    }
}

/// The span between two consecutive readings.
struct MeterSegment: Identifiable {
    let start: Date
    let end: Date
    let consumption: Double

    var id: Date { start }
    var days: Double { end.timeIntervalSince(start) / 86_400 }
    var perDay: Double { consumption / days }
    /// A reading lower than the one before it: typo or meter swap. Such spans are left out of the usage.
    var isNegative: Bool { consumption < 0 }
}

struct DailyUsage: Identifiable {
    let day: Date
    let kWh: Double
    /// Part of the value is extrapolated past the last reading.
    let estimated: Bool

    var id: Date { day }
}

struct MonthlyUsage: Identifiable {
    let month: Date
    let kWh: Double
    let days: Int
    let estimated: Bool

    var id: Date { month }
    var perDay: Double { kWh / Double(days) }
}

/// Turns sparse readings into usage, assuming a constant rate between two readings.
enum HeatUsage {
    /// How far past the last reading the latest rate is carried forward.
    static let maxExtrapolationDays = 31

    static func segments(_ readings: [(date: Date, kWh: Double)]) -> [MeterSegment] {
        let sorted = readings.sorted { $0.date < $1.date }
        return zip(sorted, sorted.dropFirst()).compactMap { a, b in
            guard b.date > a.date else { return nil }
            return MeterSegment(start: a.date, end: b.date, consumption: b.kWh - a.kWh)
        }
    }

    /// Spreads each segment over calendar days by time overlap; a day that straddles a reading gets a share
    /// of both segments. The latest rate is extrapolated up to `now` (capped) and marked as estimated.
    static func daily(_ segments: [MeterSegment], now: Date = .now, calendar: Calendar = .current) -> [DailyUsage] {
        var real: [Date: Double] = [:]
        var estimate: [Date: Double] = [:]

        func spread(from a: Date, to b: Date, perSecond: Double, into bucket: inout [Date: Double]) {
            var dayStart = calendar.startOfDay(for: a)
            while dayStart < b {
                guard let next = calendar.date(byAdding: .day, value: 1, to: dayStart) else { return }
                let overlap = min(b, next).timeIntervalSince(max(a, dayStart))
                if overlap > 0 { bucket[dayStart, default: 0] += overlap * perSecond }
                dayStart = next
            }
        }

        for s in segments where !s.isNegative {
            spread(from: s.start, to: s.end, perSecond: s.consumption / s.end.timeIntervalSince(s.start), into: &real)
        }
        if let last = segments.last, !last.isNegative, now > last.end {
            let cap = last.end.addingTimeInterval(Double(maxExtrapolationDays) * 86_400)
            spread(from: last.end, to: min(now, cap), perSecond: last.perDay / 86_400, into: &estimate)
        }

        return Set(real.keys).union(estimate.keys).sorted().map { day in
            DailyUsage(day: day, kWh: real[day, default: 0] + estimate[day, default: 0], estimated: estimate[day] != nil)
        }
    }

    static func monthly(_ daily: [DailyUsage], calendar: Calendar = .current) -> [MonthlyUsage] {
        let groups = Dictionary(grouping: daily) { calendar.dateInterval(of: .month, for: $0.day)?.start ?? $0.day }
        return groups.map { month, days in
            MonthlyUsage(month: month, kWh: days.reduce(0) { $0 + $1.kWh }, days: days.count,
                         estimated: days.contains(where: \.estimated))
        }
        .sorted { $0.month > $1.month }
    }
}
