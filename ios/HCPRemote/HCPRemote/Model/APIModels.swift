import Foundation

/// Mirrors the JSON of the controller API (docs/API.md).
enum ControlMode: String, Codable, CaseIterable, Identifiable {
    case off, auto, manual

    var id: String { rawValue }

    var title: String {
        switch self {
        case .off: "关闭"
        case .auto: "自动"
        case .manual: "手动"
        }
    }
}

enum SensorRole: String, CaseIterable, Identifiable {
    case mainInlet, mainReturn, heatingInlet, heatingReturn, waterInlet

    var id: String { rawValue }

    var title: String {
        switch self {
        case .mainInlet: "主管进水"
        case .mainReturn: "主管回水"
        case .heatingInlet: "暖气进水"
        case .heatingReturn: "暖气回水"
        case .waterInlet: "热水箱进水"
        }
    }
}

struct ControllerStatus: Decodable {
    let time: Double
    let uptimeSeconds: Int
    let mode: ControlMode
    let phase: String
    let busy: String?
    let targetTemperature: Int
    let targetRange: TargetRange
    let temperatures: [String: SensorReading]
    let valve: ValveStatus
    let lastDecision: Decision?
    let alarms: [Alarm]

    func reading(_ role: SensorRole) -> SensorReading? { temperatures[role.rawValue] }

    var phaseTitle: String {
        switch phase {
        case "idle": "已关闭"
        case "manual": "手动控制"
        case "normal": "自动调节中"
        case "water_tank": "热水箱加热中，自动暂停"
        case "no_consumption": "无热量消耗，阀门已关小"
        case "overheat": "暖气过热保护"
        case "sensor_fault": "传感器故障，阀门保持不动"
        case "relay_fault": "继电器故障"
        default: phase
        }
    }

    var phaseIsProblem: Bool {
        ["overheat", "sensor_fault", "relay_fault"].contains(phase)
    }
}

struct TargetRange: Decodable {
    let min: Int
    let max: Int
    let upperBand: Int
}

struct SensorReading: Decodable {
    let value: Double?
    let ok: Bool
    let updatedAt: Double?
    let error: String?
}

struct ValveStatus: Decodable {
    let position: Int
    let max: Int
    let percent: Int
    let autoMin: Int
    let autoMax: Int
    let reduced: Int
    let manualTarget: Int?
    let moving: String?
    let calibrated: Bool
}

struct Decision: Decodable {
    let op: String
    let rule: String
    let reason: String
    let moved: Bool
    let atLimit: Bool
    let at: Double

    var summary: String {
        let action = switch op {
        case "up": "开大"
        case "down": "关小"
        default: "保持"
        }
        let why = switch rule {
        case "heating_inlet_low": "暖气进水低于 30 °C"
        case "sum_low": "暖气进水 + 主管回水偏低"
        case "below_target": "主管回水低于目标"
        case "sum_high": "暖气进水 + 主管回水偏高"
        case "above_target": "主管回水高于目标上限"
        case "in_range": "温度在目标范围内"
        default: reason
        }
        return "\(action)：\(why)" + (atLimit ? "（阀门已到自动范围极限）" : "")
    }
}

struct Alarm: Decodable, Identifiable {
    let code: String
    let level: String
    let message: String
    let sensor: String?

    var id: String { code + (sensor ?? "") }

    var title: String {
        switch code {
        case "relay_fault": "继电器故障"
        case "overheat": "暖气过热，阀门保持在低开度"
        case "no_consumption": "主管无热量消耗"
        case "water_tank": "热水箱加热中，自动控制暂停"
        case "sensor_fault":
            "传感器无读数：" + (sensor.flatMap { SensorRole(rawValue: $0)?.title } ?? "?")
        case "uncalibrated": "阀门位置未校准"
        default: code
        }
    }
}

struct HistoryResponse: Decodable {
    let hours: Double
    let points: [HistoryPoint]
}

struct HistoryPoint: Decodable {
    let t: Double
    let mainInlet: Double?
    let mainReturn: Double?
    let heatingInlet: Double?
    let heatingReturn: Double?
    let waterInlet: Double?
    let valve: Int
    let mode: String

    var date: Date { Date(timeIntervalSince1970: t) }

    func value(_ role: SensorRole) -> Double? {
        switch role {
        case .mainInlet: mainInlet
        case .mainReturn: mainReturn
        case .heatingInlet: heatingInlet
        case .heatingReturn: heatingReturn
        case .waterInlet: waterInlet
        }
    }
}

struct EventsResponse: Decodable {
    let events: [ControllerEvent]
}

struct ControllerEvent: Decodable, Identifiable {
    let t: Double
    let kind: String
    let level: String
    let message: String

    var id: String { "\(t)-\(kind)" }
    var date: Date { Date(timeIntervalSince1970: t) }
}

struct APIErrorBody: Decodable {
    let error: String
}
