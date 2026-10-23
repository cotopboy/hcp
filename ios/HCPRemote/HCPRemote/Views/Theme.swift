import SwiftUI

/// Dark "control panel" look shared by all screens: glass cards on a deep navy grid, cyan accent.
enum Theme {
    static let accent = Color(red: 0.26, green: 0.86, blue: 1.0)
    static let heat = Color(red: 1.0, green: 0.56, blue: 0.24)
    static let ok = Color(red: 0.32, green: 0.95, blue: 0.62)
    static let warning = Color(red: 1.0, green: 0.76, blue: 0.30)
    static let danger = Color(red: 1.0, green: 0.34, blue: 0.40)
    static let idle = Color(white: 0.62)

    static let bgTop = Color(red: 0.04, green: 0.06, blue: 0.12)
    static let bgBottom = Color(red: 0.01, green: 0.02, blue: 0.05)
    static let cardFill = Color(red: 0.07, green: 0.09, blue: 0.15).opacity(0.82)
    static let stroke = Color.white.opacity(0.09)
    static let well = Color.white.opacity(0.05)
    /// Row background for the remaining List/Form screens.
    static let row = Color.white.opacity(0.06)

    static func bigNumber(_ size: CGFloat, weight: Font.Weight = .light) -> Font {
        .system(size: size, weight: weight, design: .rounded).monospacedDigit()
    }

    static let tag = Font.system(size: 10, weight: .semibold, design: .monospaced)
}

extension SensorRole {
    var color: Color {
        switch self {
        case .mainInlet: Theme.heat
        case .mainReturn: Theme.accent
        case .heatingInlet: Color(red: 1.0, green: 0.38, blue: 0.58)
        case .heatingReturn: Color(red: 0.66, green: 0.52, blue: 1.0)
        case .waterInlet: Color(red: 0.36, green: 0.58, blue: 1.0)
        }
    }
}

extension ControlMode {
    var icon: String {
        switch self {
        case .off: "power"
        case .auto: "cpu"
        case .manual: "hand.point.up.left"
        }
    }

    var tint: Color {
        switch self {
        case .off: Theme.idle
        case .auto: Theme.accent
        case .manual: Theme.heat
        }
    }
}

// MARK: - Background

struct TechBackground: View {
    var body: some View {
        ZStack {
            LinearGradient(colors: [Theme.bgTop, Theme.bgBottom], startPoint: .top, endPoint: .bottom)
            RadialGradient(colors: [Theme.accent.opacity(0.16), .clear],
                           center: .topLeading, startRadius: 0, endRadius: 460)
            RadialGradient(colors: [Theme.heat.opacity(0.09), .clear],
                           center: .bottomTrailing, startRadius: 0, endRadius: 520)
            GridPattern(spacing: 26)
                .stroke(Color.white.opacity(0.03), lineWidth: 0.5)
        }
        .ignoresSafeArea()
    }
}

private struct GridPattern: Shape {
    let spacing: CGFloat

    func path(in rect: CGRect) -> Path {
        var path = Path()
        stride(from: rect.minX, through: rect.maxX, by: spacing).forEach { x in
            path.move(to: CGPoint(x: x, y: rect.minY))
            path.addLine(to: CGPoint(x: x, y: rect.maxY))
        }
        stride(from: rect.minY, through: rect.maxY, by: spacing).forEach { y in
            path.move(to: CGPoint(x: rect.minX, y: y))
            path.addLine(to: CGPoint(x: rect.maxX, y: y))
        }
        return path
    }
}

extension View {
    /// Card-style container; `glow` tints the border and shadow.
    func techCard(glow: Color? = nil, padding: CGFloat = 16) -> some View {
        modifier(TechCard(glow: glow, padding: padding))
    }

    /// Restyles a List/Form to sit on the tech background.
    func techList() -> some View {
        scrollContentBackground(.hidden)
            .background(TechBackground())
    }
}

private struct TechCard: ViewModifier {
    let glow: Color?
    let padding: CGFloat

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: 22, style: .continuous)
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background {
                shape.fill(Theme.cardFill)
                    .overlay(shape.fill(LinearGradient(colors: [.white.opacity(0.06), .white.opacity(0.0)],
                                                       startPoint: .top, endPoint: .bottom)))
            }
            .overlay {
                shape.strokeBorder(LinearGradient(colors: [(glow ?? .white).opacity(glow == nil ? 0.16 : 0.5),
                                                           .white.opacity(0.03)],
                                                  startPoint: .topLeading, endPoint: .bottomTrailing),
                                   lineWidth: 1)
            }
            .shadow(color: (glow ?? .black).opacity(glow == nil ? 0.35 : 0.22), radius: 18, y: 8)
    }
}

// MARK: - Building blocks

struct CardHeader<Trailing: View>: View {
    let title: String
    let tag: String
    let icon: String
    var tint: Color = Theme.accent
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.caption.weight(.bold))
                .foregroundStyle(tint)
                .frame(width: 24, height: 24)
                .background(tint.opacity(0.14), in: RoundedRectangle(cornerRadius: 7, style: .continuous))
            Text(title).font(.subheadline.weight(.semibold))
            Text(tag).font(Theme.tag).tracking(1.4).foregroundStyle(.tertiary)
            Spacer(minLength: 4)
            trailing
        }
    }
}

extension CardHeader where Trailing == EmptyView {
    init(title: String, tag: String, icon: String, tint: Color = Theme.accent) {
        self.init(title: title, tag: tag, icon: icon, tint: tint) { EmptyView() }
    }
}

struct SegmentOption<Value: Hashable>: Identifiable {
    let value: Value
    let title: String
    var icon: String?
    var tint: Color = Theme.accent

    var id: Value { value }
}

/// Segmented control with a glowing sliding selection.
struct TechSegmented<Value: Hashable>: View {
    let options: [SegmentOption<Value>]
    @Binding var selection: Value
    var compact = false
    @Namespace private var namespace

    var body: some View {
        HStack(spacing: 4) {
            ForEach(options) { option in
                let selected = option.value == selection
                Button {
                    withAnimation(.snappy(duration: 0.25)) { selection = option.value }
                } label: {
                    HStack(spacing: 6) {
                        if let icon = option.icon { Image(systemName: icon) }
                        Text(option.title)
                    }
                    .font(compact ? .caption.weight(.semibold) : .subheadline.weight(.semibold))
                    .foregroundStyle(selected ? option.tint : .secondary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, compact ? 7 : 12)
                    .background {
                        if selected {
                            RoundedRectangle(cornerRadius: compact ? 9 : 12, style: .continuous)
                                .fill(option.tint.opacity(0.16))
                                .overlay(RoundedRectangle(cornerRadius: compact ? 9 : 12, style: .continuous)
                                    .strokeBorder(option.tint.opacity(0.55), lineWidth: 1))
                                .shadow(color: option.tint.opacity(0.45), radius: 10)
                                .matchedGeometryEffect(id: "selection", in: namespace)
                        }
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(selected ? .isSelected : [])
            }
        }
        .padding(4)
        .background(Theme.well, in: RoundedRectangle(cornerRadius: compact ? 12 : 15, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: compact ? 12 : 15, style: .continuous)
            .strokeBorder(Theme.stroke, lineWidth: 1))
    }
}

/// Outlined, tinted button used for step controls.
struct ChipButtonStyle: ButtonStyle {
    var tint: Color = Theme.accent
    var prominent = false

    func makeBody(configuration: Configuration) -> some View {
        ChipBody(configuration: configuration, tint: tint, prominent: prominent)
    }

    private struct ChipBody: View {
        let configuration: Configuration
        let tint: Color
        let prominent: Bool
        @Environment(\.isEnabled) private var isEnabled

        var body: some View {
            let shape = RoundedRectangle(cornerRadius: 12, style: .continuous)
            configuration.label
                .font(.subheadline.weight(.semibold).monospacedDigit())
                .foregroundStyle(prominent ? Color.black : tint)
                .padding(.horizontal, 14)
                .padding(.vertical, prominent ? 13 : 10)
                .frame(minWidth: 54)
                .background {
                    if prominent {
                        shape.fill(LinearGradient(colors: [tint, tint.opacity(0.75)], startPoint: .top, endPoint: .bottom))
                    } else {
                        shape.fill(tint.opacity(configuration.isPressed ? 0.28 : 0.12))
                    }
                }
                .overlay(shape.strokeBorder(tint.opacity(prominent ? 0 : 0.35), lineWidth: 1))
                .shadow(color: tint.opacity(prominent && isEnabled ? 0.45 : 0), radius: 12)
                .opacity(isEnabled ? (configuration.isPressed && prominent ? 0.8 : 1) : 0.3)
                .scaleEffect(configuration.isPressed ? 0.96 : 1)
                .animation(.snappy(duration: 0.15), value: configuration.isPressed)
        }
    }
}

/// Row inside a card that pushes another screen.
struct LinkRow: View {
    let title: String
    let icon: String
    var tint: Color = Theme.accent

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.footnote.weight(.semibold))
                .foregroundStyle(tint)
                .frame(width: 30, height: 30)
                .background(tint.opacity(0.13), in: RoundedRectangle(cornerRadius: 9, style: .continuous))
            Text(title).font(.subheadline)
            Spacer()
            Image(systemName: "chevron.right")
                .font(.caption.weight(.bold))
                .foregroundStyle(.tertiary)
        }
        .padding(.vertical, 6)
        .contentShape(Rectangle())
    }
}

/// Small blinking status light.
struct PulseDot: View {
    let color: Color
    var animated = true
    @State private var pulse = false

    var body: some View {
        Circle()
            .fill(color)
            .frame(width: 7, height: 7)
            .background {
                Circle()
                    .fill(color.opacity(0.5))
                    .scaleEffect(pulse ? 2.6 : 1)
                    .opacity(pulse ? 0 : 0.8)
            }
            .shadow(color: color, radius: 4)
            .onAppear {
                guard animated else { return }
                withAnimation(.easeOut(duration: 1.6).repeatForever(autoreverses: false)) { pulse = true }
            }
    }
}

/// Horizontal meter made of lit segments.
struct SegmentMeter: View {
    /// 0...1
    let fraction: Double
    var segments = 24
    var tint: Color = Theme.accent
    var height: CGFloat = 14

    var body: some View {
        let lit = Int((fraction * Double(segments)).rounded())
        HStack(spacing: 3) {
            ForEach(0..<segments, id: \.self) { i in
                RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .fill(i < lit ? AnyShapeStyle(tint.opacity(0.45 + 0.55 * Double(i + 1) / Double(segments)))
                                  : AnyShapeStyle(Color.white.opacity(0.07)))
                    .shadow(color: i < lit ? tint.opacity(0.6) : .clear, radius: 3)
            }
        }
        .frame(height: height)
        .animation(.snappy, value: lit)
    }
}

/// 270° ring gauge with an optional highlighted band (e.g. target range).
struct RingGauge<Center: View>: View {
    let value: Double?
    let range: ClosedRange<Double>
    var band: ClosedRange<Double>?
    var tint: Color = Theme.accent
    var lineWidth: CGFloat = 11
    @ViewBuilder var center: Center

    private let span = 0.75

    private func fraction(_ v: Double) -> Double {
        min(1, max(0, (v - range.lowerBound) / (range.upperBound - range.lowerBound)))
    }

    var body: some View {
        GeometryReader { geo in
            let size = min(geo.size.width, geo.size.height)
            ZStack {
                ForEach(0...30, id: \.self) { i in
                    Capsule()
                        .fill(Color.white.opacity(i % 5 == 0 ? 0.35 : 0.12))
                        .frame(width: 1.5, height: i % 5 == 0 ? 7 : 4)
                        .offset(y: -(size / 2 - lineWidth - 9))
                        .rotationEffect(.degrees(-135 + Double(i) * 270 / 30))
                }
                Group {
                    Circle()
                        .trim(from: 0, to: span)
                        .stroke(Color.white.opacity(0.07), style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                    if let band {
                        Circle()
                            .trim(from: fraction(band.lowerBound) * span, to: fraction(band.upperBound) * span)
                            .stroke(Theme.ok.opacity(0.4), style: StrokeStyle(lineWidth: lineWidth + 6, lineCap: .butt))
                            .blur(radius: 0.3)
                    }
                    if let value {
                        let f = fraction(value)
                        Circle()
                            .trim(from: 0, to: max(0.001, f * span))
                            .stroke(AngularGradient(colors: [tint.opacity(0.25), tint],
                                                    center: .center,
                                                    startAngle: .degrees(0),
                                                    endAngle: .degrees(max(1, 360 * span * f))),
                                    style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                            .shadow(color: tint.opacity(0.7), radius: 8)
                    }
                }
                .rotationEffect(.degrees(135))
                .padding(lineWidth / 2)
                center
            }
            .frame(width: size, height: size)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .animation(.smooth, value: value)
    }
}
