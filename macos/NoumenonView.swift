// Noumenon: exact compound SVG fills in a native ScreenSaverView.
// Reference sequence: 56 shapes plus one blank; original catalog: 192 shapes.
// Live glyphs from the feed folder that `python -m live` writes join the
// original family while the saver runs.
import AppKit
import ScreenSaver

private struct Catalog {
    let commands: [[[Double]]]
    let paths: [CGPath]
    let speeds: [Double]
    let trails: [Int]
    let ids: [String]
    let catalogHash: String
    let referenceHash: String
    let originalHash: String
    let originalShare: Double
    let liveSpeed: Double
    let liveTrail: Int
    static let glyphCount = 249
    static let referenceCount = 57
    static let originalOffset = 57
    static let originalCount = 192
    static let blankIndex = 4

    static func load() -> Catalog? {
        let bundle = Bundle(for: NoumenonView.self)
        guard let url = bundle.url(forResource: "glyphs", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let commands = root["commands"] as? [[[Double]]], commands.count == 249,
              let canvas = root["canvas"] as? [Double], canvas == [100, 100],
              let speeds = root["speeds"] as? [Double], speeds.count == 249,
              let trails = root["trails"] as? [Int], trails.count == 249,
              let ids = root["glyph_ids"] as? [String], ids.count == 249, Set(ids).count == 249,
              let catalogHash = root["catalog_sha256"] as? String,
              let referenceHash = root["reference_sha256"] as? String,
              let originalHash = root["original_sha256"] as? String,
              let share = root["original_share"] as? Double, share == 0.1,
              root["fill_rule"] as? String == "nonzero",
              root["reference_count"] as? Int == referenceCount,
              root["reference_visible_count"] as? Int == 56,
              root["original_count"] as? Int == originalCount,
              root["original_offset"] as? Int == originalOffset,
              root["blank_index"] as? Int == blankIndex,
              commands[blankIndex].isEmpty,
              speeds.allSatisfy({ $0.isFinite && $0 > 0 }),
              trails.allSatisfy({ $0 > 0 }) else { return nil }
        let paths = commands.compactMap { makePath($0) }
        guard paths.count == 249 else { return nil }
        // Live glyphs move at the approved originals' median speed and trail.
        let originals = originalOffset..<(originalOffset + originalCount)
        let liveSpeed = median(Array(speeds[originals]))
        let liveTrail = Int((median(trails[originals].map { Double($0) }) + 0.5).rounded(.down))
        return Catalog(commands: commands, paths: paths, speeds: speeds, trails: trails,
                       ids: ids, catalogHash: catalogHash, referenceHash: referenceHash,
                       originalHash: originalHash, originalShare: share,
                       liveSpeed: liveSpeed, liveTrail: liveTrail)
    }

    static func median(_ values: [Double]) -> Double {
        let sorted = values.sorted(), middle = sorted.count / 2
        return sorted.count % 2 == 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
    }

    // Glyphs at or above glyphCount are live slots.
    func speed(_ glyph: Int) -> Double { glyph < Catalog.glyphCount ? speeds[glyph] : liveSpeed }
    func trail(_ glyph: Int) -> Int { glyph < Catalog.glyphCount ? trails[glyph] : liveTrail }
    func path(_ glyph: Int) -> CGPath? {
        glyph < Catalog.glyphCount ? paths[glyph] : LiveFeed.shared.path(glyph - Catalog.glyphCount)
    }

    static func makePath(_ commands: [[Double]]) -> CGPath? {
        let path = CGMutablePath()
        var open = false
        for c in commands {
            guard let op = c.first, op.isFinite, op.rounded() == op, (0...3).contains(op),
                  c.count == (op == 2 ? 7 : op == 3 ? 1 : 3), c.allSatisfy({ $0.isFinite }) else { return nil }
            if op == 0 {
                guard !open else { return nil }
                path.move(to: CGPoint(x: c[1], y: c[2])); open = true
            } else {
                guard open else { return nil }
                if op == 1 { path.addLine(to: CGPoint(x: c[1], y: c[2])) }
                else if op == 2 {
                    path.addCurve(to: CGPoint(x: c[5], y: c[6]),
                                  control1: CGPoint(x: c[1], y: c[2]),
                                  control2: CGPoint(x: c[3], y: c[4]))
                } else { path.closeSubpath(); open = false }
            }
        }
        return open ? nil : path.copy()
    }

    static func mix(_ input: UInt32) -> UInt32 {
        var value = input
        value ^= value >> 16; value = value &* 0x7feb352d
        value ^= value >> 15; value = value &* 0x846ca68b
        return value ^ (value >> 16)
    }

    func select(seed: UInt32, row: Int, epoch: Int) -> Int {
        let hash = Catalog.mix(seed ^ (UInt32(truncatingIfNeeded: row) &* 0x9e3779b9)
                              ^ (UInt32(truncatingIfNeeded: epoch) &* 0x85ebca6b))
        let index = Catalog.mix(hash ^ 0xa511e9b3)
        return hash % 10000 < UInt32(originalShare * 10000)
            ? LiveFeed.shared.original(index)
            : Int(index % UInt32(Catalog.referenceCount))
    }
}

/// Live glyphs: the newest SVGs that `python -m live` writes to the feed folder
/// join the original family while the saver runs. As in the web explorer they
/// fill the pool beside the 192 approved originals and then replace them one by
/// one, so up to 256 originals are in play and the newest are always among
/// them. Every native port reads a feed with the same rules and describes it
/// with the same report.
final class LiveFeed {
    static let shared = LiveFeed()
    static let maximum = 256, pool = 256, fileBytes = 262_144, maxCommands = 16_000
    static let nameLimit = 96, listed = 65_536
    static let scanInterval: TimeInterval = 2
    private static let nameCharacters = Set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_.".utf8)
    private static let numberCharacters = Set("0123456789.+-eE".utf8)
    private static let separators: Set<UInt8> = [32, 44, 9, 10, 13]

    private struct Entry {
        let name: String
        let commands: [[Double]]?
        let path: CGPath?
        let generation: Int
    }
    private var slots = [Entry?](repeating: nil, count: LiveFeed.maximum)
    private var order: [Int] = []
    private var generations = 0, files = 0, considered = 0
    private var nextScan = Date.distantPast
    private var folder: String?
    private(set) var configured = false

    var count: Int { order.count }
    var approvedInPool: Int {
        count < LiveFeed.pool - Catalog.originalCount ? Catalog.originalCount : LiveFeed.pool - count
    }

    /// The newest live glyphs first, then the approved originals that remain.
    func original(_ index: UInt32) -> Int {
        let approved = approvedInPool
        let position = Int(index % UInt32(count + approved))
        if position < count { return Catalog.glyphCount + order[position] }
        return Catalog.originalOffset + Catalog.originalCount - approved + (position - count)
    }
    func path(_ slot: Int) -> CGPath? { slots[slot]?.path }
    func generation(_ slot: Int) -> Int { slots[slot]?.generation ?? 0 }
    func slot(atPosition position: Int) -> Int { order[position] }

    /// The per-user folder the generator writes by default. Inside the screen
    /// saver sandbox the home folder is the legacyScreenSaver container.
    static func defaultFolder() -> String {
        if let chosen = ProcessInfo.processInfo.environment["NOUMENON_LIVE_FEED"], !chosen.isEmpty {
            return (chosen as NSString).expandingTildeInPath
        }
        let home = NSHomeDirectory() as NSString
        let container = home.appendingPathComponent(
            "Library/Containers/com.apple.ScreenSaver.Engine.legacyScreenSaver/Data")
        let base = FileManager.default.fileExists(atPath: container) ? container : home as String
        return (base as NSString).appendingPathComponent("Library/Application Support/Noumenon/live-feed")
    }

    /// Read live glyphs from this folder from now on; nil shows none.
    func use(_ folder: String?) {
        slots = [Entry?](repeating: nil, count: LiveFeed.maximum)
        order = []
        files = 0
        considered = 0
        self.folder = folder
        configured = true
        nextScan = Date().addingTimeInterval(LiveFeed.scanInterval)
        scan()
    }

    func poll() {
        guard folder != nil, Date() >= nextScan else { return }
        nextScan = Date().addingTimeInterval(LiveFeed.scanInterval)
        scan()
    }

    private static func newer(_ a: String, _ b: String) -> Bool {
        Array(b.utf8).lexicographicallyPrecedes(Array(a.utf8))
    }

    /// Bring the live set up to date with the newest files in the feed. A glyph
    /// is read once, while its file stays among the newest; a file that fails
    /// validation is skipped. Returns true when the set changed.
    @discardableResult func scan() -> Bool {
        guard let folder = folder,
              let entries = try? FileManager.default.contentsOfDirectory(atPath: folder) else { return false }
        var names = Array(entries.filter { LiveFeed.validName($0) }.prefix(LiveFeed.listed))
        names.sort(by: LiveFeed.newer)
        let window = Array(names.prefix(LiveFeed.maximum))
        let wanted = Set(window)
        var known = Set<String>()
        var changed = false
        for slot in slots.indices {
            guard let entry = slots[slot] else { continue }
            if wanted.contains(entry.name) { known.insert(entry.name) } else { slots[slot] = nil; changed = true }
        }
        for name in window where !known.contains(name) {
            guard let slot = slots.firstIndex(where: { $0 == nil }) else { break }
            let commands = LiveFeed.read((folder as NSString).appendingPathComponent(name))
            generations += 1
            slots[slot] = Entry(name: name, commands: commands,
                                path: commands.flatMap { Catalog.makePath($0) }, generation: generations)
            changed = true
        }
        files = names.count
        considered = window.count
        order = slots.indices.filter { slots[$0]?.path != nil }
            .sorted { LiveFeed.newer(slots[$0]!.name, slots[$1]!.name) }
        return changed
    }

    /// Feed names sort in arrival order; anything else in the folder is ignored.
    static func validName(_ name: String) -> Bool {
        let bytes = Array(name.utf8)
        return bytes.count >= 5 && bytes.count < nameLimit && bytes[0] != UInt8(ascii: ".")
            && bytes.suffix(4).elementsEqual(".svg".utf8) && bytes.allSatisfy { nameCharacters.contains($0) }
    }

    private static func read(_ path: String) -> [[Double]]? {
        // Regular files only: never follow a link or open a pipe.
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: path),
              (attributes[.type] as? FileAttributeType) == .typeRegular,
              let size = (attributes[.size] as? NSNumber)?.intValue, size > 0, size <= fileBytes,
              let data = FileManager.default.contents(atPath: path), data.count == size else { return nil }
        return parse(data)
    }

    /// The generator's format: 100-unit SVGs whose black nonzero paths are closed
    /// polygons in absolute M, L and Z commands, every point inside the canvas.
    static func parse(_ data: Data) -> [[Double]]? {
        guard !data.isEmpty, data.count <= fileBytes else { return nil }
        var raw = [UInt8](data)
        if let end = raw.firstIndex(of: 0) { raw.removeSubrange(end...) }
        let text = raw
        func find(_ needle: String, _ from: Int) -> Int? {
            let pattern = Array(needle.utf8)
            var index = from
            while index + pattern.count <= text.count {
                if text[index] == pattern[0] && text[index..<(index + pattern.count)].elementsEqual(pattern) {
                    return index
                }
                index += 1
            }
            return nil
        }
        let move = UInt8(ascii: "M"), line = UInt8(ascii: "L"), close = UInt8(ascii: "Z")
        guard text.starts(with: "<svg".utf8), find("<!", 0) == nil, find("<?", 0) == nil,
              find(" viewBox=\"0 0 100 100\"", 0) != nil, find("evenodd", 0) == nil else { return nil }
        var commands: [[Double]] = []
        var contours = 0, cursor = 0
        while let start = find("<path", cursor) {
            guard let end = find(">", start), let at = find(" d=\"", start), at < end,
                  let stop = find("\"", at + 4), stop < end else { return nil }
            var open = false, points = 0, command: UInt8 = 0
            var pending: [Double] = []
            var p = at + 4
            while p < stop {
                let c = text[p]
                if separators.contains(c) { p += 1; continue }
                if c == move || c == line || c == close {
                    guard pending.isEmpty else { return nil }  // a coordinate needs both of its numbers
                    if c == close {
                        guard open, points >= 3, commands.count < maxCommands else { return nil }
                        commands.append([3])
                        open = false; points = 0; command = 0; contours += 1
                    } else { command = c }
                    p += 1
                    continue
                }
                // A number is a whole run of number characters.
                var span = p
                while span < stop && numberCharacters.contains(text[span]) { span += 1 }
                guard span > p, let value = Double(String(decoding: text[p..<span], as: UTF8.self)),
                      value.isFinite, value >= 0, value <= 100 else { return nil }
                p = span
                pending.append(value)
                if pending.count < 2 { continue }
                let x = pending[0], y = pending[1]
                pending = []
                guard commands.count < maxCommands else { return nil }
                if command == move && !open {
                    commands.append([0, x, y]); open = true; points = 1; command = line
                } else if command == line && open {
                    commands.append([1, x, y]); points += 1
                } else { return nil }
            }
            guard pending.isEmpty, !open else { return nil }
            cursor = end
        }
        return contours > 0 ? commands : nil
    }

    /// A JSON-ready account of the feed, for tests and for checking a feed folder.
    func report(speed: Double, trail: Int) -> NSDictionary {
        let rejected = slots.compactMap { $0 }.filter { $0.path == nil }.map { $0.name }.sorted(by: LiveFeed.newer)
        let glyphs = order.map { slot -> [String: Any] in
            ["name": slots[slot]!.name, "commands": slots[slot]!.commands!.count]
        }
        return ["version": "native-live-feed-v1", "files": files, "considered": considered, "live": count,
                "approved_in_pool": approvedInPool, "pool": count + approvedInPool, "speed": speed,
                "trail": trail, "rejected": rejected, "glyphs": glyphs]
    }
}

private final class Column {
    var x: CGFloat = 0
    var y: CGFloat = 0
    var glyph = 0
    var phase = 0
    var seed: UInt32 = 0
    var rate: CGFloat = 0
    var accumulator: CGFloat = 0
    var burst: CGFloat = 0
}

private final class Layer {
    let trailSprites: [NSImage]
    let headSprites: [NSImage]
    let cell: CGFloat
    let level: CGFloat
    let pad: CGFloat
    let step: CGFloat
    let speed: CGFloat
    var columns: [Column] = []
    var drawnReference = 0
    var drawnOriginal = 0
    var drawnBlank = 0
    var drawnLive = 0
    private var liveSprites: [Int: (generation: Int, trail: NSImage, head: NSImage)] = [:]

    init(catalog: Catalog, cell: CGFloat, spacing: CGFloat, speed: CGFloat,
         level: CGFloat, width: CGFloat, height: CGFloat) {
        self.cell = cell
        self.level = level
        self.speed = speed
        pad = max(3, cell / 2)
        trailSprites = catalog.paths.map { Layer.sprite(path: $0, cell: cell, pad: max(3, cell / 2), level: level, head: false) }
        headSprites = catalog.paths.map { Layer.sprite(path: $0, cell: cell, pad: max(3, cell / 2), level: level, head: true) }
        step = max(3, cell * 1.04)
        let lane = max(3, cell * spacing)
        let count = Int((width / lane).rounded(.up) + 1)
        for index in 0..<count {
            let column = Column()
            column.x = CGFloat(index) * lane + CGFloat.random(in: -3...3)
            reset(column, catalog: catalog, initial: true)
            column.y = CGFloat.random(in: 0...1) * (height + CGFloat(catalog.trail(column.glyph)) * step)
            columns.append(column)
        }
    }

    func reset(_ column: Column, catalog: Catalog, initial: Bool) {
        column.seed = UInt32.random(in: 0...UInt32.max)
        column.glyph = catalog.select(seed: column.seed, row: 0, epoch: 0)
        column.phase = Int.random(in: 0..<1000)
        column.rate = CGFloat(catalog.speed(column.glyph)) * 5.6 * speed
        column.accumulator = CGFloat.random(in: 0...1)
        column.burst = !initial && Double.random(in: 0...1) < 0.06 ? 1.6 : 0
        if !initial { column.y = -step * CGFloat(Int.random(in: 0..<7)) }
    }

    /// A live slot's sprites are drawn the first time it appears and redrawn
    /// whenever the slot receives a newer glyph.
    func sprite(_ glyph: Int, head: Bool, catalog: Catalog) -> NSImage? {
        if glyph < Catalog.glyphCount { return head ? headSprites[glyph] : trailSprites[glyph] }
        let slot = glyph - Catalog.glyphCount, generation = LiveFeed.shared.generation(slot)
        if let cached = liveSprites[slot], cached.generation == generation { return head ? cached.head : cached.trail }
        guard let path = catalog.path(glyph) else { return nil }
        let entry = (generation: generation,
                     trail: Layer.sprite(path: path, cell: cell, pad: pad, level: level, head: false),
                     head: Layer.sprite(path: path, cell: cell, pad: pad, level: level, head: true))
        liveSprites[slot] = entry
        return head ? entry.head : entry.trail
    }

    static func sprite(path: CGPath, cell: CGFloat,
                       pad: CGFloat, level: CGFloat, head: Bool, glow: Bool = true) -> NSImage {
        let size = cell + pad * 2
        let image = NSImage(size: NSSize(width: size, height: size))
        image.lockFocus()
        if let context = NSGraphicsContext.current?.cgContext {
            context.translateBy(x: 0, y: size)
            context.scaleBy(x: 1, y: -1)
            if glow {
                context.setShadow(offset: .zero, blur: cell * (head ? 0.14 : 0.08),
                                  color: CGColor(red: 117 / 255, green: 240 / 255, blue: 152 / 255,
                                                 alpha: (head ? 0.5 : 0.24) * level))
            }
            let lightness = 0.7 * level
            let chroma = (1 - abs(2 * lightness - 1)) * 0.8
            let hue: CGFloat = 137.0 / 60
            let secondary = chroma * (1 - abs(hue.truncatingRemainder(dividingBy: 2) - 1))
            let m = lightness - chroma / 2
            context.setFillColor(head
                ? CGColor(red: 162 / 255 * level, green: level, blue: 216 / 255 * level, alpha: 1)
                : CGColor(red: m, green: chroma + m, blue: secondary + m, alpha: 1))
            if !glow { context.setFillColor(CGColor(gray: 1, alpha: 1)) }
            context.translateBy(x: pad, y: pad)
            context.scaleBy(x: cell / 100, y: cell / 100)
            context.addPath(path)
            // Preserve every contour and its authored direction. Even-odd or
            // one-fill-per-contour would change holes and overlapping shapes.
            context.fillPath(using: .winding)
        }
        image.unlockFocus()
        return image
    }
}

@objc(NoumenonView)
public final class NoumenonView: ScreenSaverView {
    private var catalog: Catalog?
    private var layers: [Layer] = []
    private var buffer: NSImage?
    private var lastTick = Date()

    public override init?(frame: NSRect, isPreview: Bool) {
        super.init(frame: frame, isPreview: isPreview)
        animationTimeInterval = 1.0 / 40.0
    }
    public required init?(coder: NSCoder) {
        super.init(coder: coder)
        animationTimeInterval = 1.0 / 40.0
    }
    public override func startAnimation() {
        super.startAnimation()
        if !LiveFeed.shared.configured { LiveFeed.shared.use(LiveFeed.defaultFolder()) }
        buildScene()
    }
    public override func setFrameSize(_ newSize: NSSize) {
        super.setFrameSize(newSize)
        if catalog != nil { buildScene() }
    }
    private func buildScene() {
        guard let catalog = catalog ?? Catalog.load() else { return }
        self.catalog = catalog
        let width = bounds.width, height = bounds.height
        guard width > 0, height > 0 else { return }
        let scale = max(0.5, min(1.5, height / 720))
        layers = [
            Layer(catalog: catalog, cell: 11 * scale, spacing: 1.20, speed: 0.62, level: 0.48, width: width, height: height),
            Layer(catalog: catalog, cell: 20 * scale, spacing: 1.35, speed: 0.80, level: 0.75, width: width, height: height),
            Layer(catalog: catalog, cell: 36 * scale, spacing: 2.50, speed: 1.00, level: 1.00, width: width, height: height)
        ]
        let image = NSImage(size: bounds.size)
        buffer = image
        drawFrame(catalog: catalog, buffer: image, dt: 0)
        lastTick = Date()
    }
    public override func animateOneFrame() {
        guard let catalog = catalog, let buffer = buffer else { buildScene(); needsDisplay = true; return }
        let now = Date()
        let dt = CGFloat(min(0.05, now.timeIntervalSince(lastTick)))
        lastTick = now
        LiveFeed.shared.poll()
        drawFrame(catalog: catalog, buffer: buffer, dt: dt)
        needsDisplay = true
    }
    private func drawFrame(catalog: Catalog, buffer: NSImage, dt: CGFloat) {
        let height = bounds.height
        buffer.lockFocus()
        NSColor.black.setFill(); bounds.fill(using: .copy)
        for layer in layers {
            for column in layer.columns {
                column.accumulator += dt * column.rate * (column.burst > 0 ? 1.9 : 1)
                if column.burst > 0 { column.burst -= dt }
                while column.accumulator >= 1 {
                    column.accumulator -= 1; column.y += layer.step; column.phase += 1
                    if column.y - CGFloat(catalog.trail(column.glyph)) * layer.step * 1.15 > height,
                       Double.random(in: 0...1) < 0.6 { layer.reset(column, catalog: catalog, initial: false) }
                }
                let length = Int((Double(catalog.trail(column.glyph)) * 1.15).rounded())
                for tail in stride(from: length, through: 0, by: -1) {
                    let y = column.y - CGFloat(tail) * layer.step
                    if y < -layer.step || y > height + layer.step { continue }
                    let glyph = catalog.select(seed: column.seed, row: Int(y / layer.step), epoch: column.phase / 6)
                    if glyph == Catalog.blankIndex { layer.drawnBlank += 1; continue }
                    if glyph < Catalog.originalOffset { layer.drawnReference += 1 } else { layer.drawnOriginal += 1 }
                    if glyph >= Catalog.glyphCount { layer.drawnLive += 1 }
                    let near = 1 - CGFloat(tail) / CGFloat(length)
                    let shimmer = 0.75 + CGFloat(glyph % 5) * 0.0625
                    let alpha: CGFloat = tail == 0 ? 1 : (0.25 + 0.75 * sqrt(near)) * shimmer
                    guard let sprite = layer.sprite(glyph, head: tail == 0, catalog: catalog) else { continue }
                    sprite.draw(at: NSPoint(x: column.x - layer.pad, y: height - y + layer.pad - sprite.size.height),
                                from: .zero, operation: .sourceOver, fraction: alpha)
                }
            }
        }
        buffer.unlockFocus()
    }
    public override func draw(_ rect: NSRect) {
        NSColor.black.setFill(); rect.fill()
        buffer?.draw(in: bounds, from: .zero, operation: .sourceOver, fraction: 1)
    }
    public override var hasConfigureSheet: Bool { false }
    public override var configureSheet: NSWindow? { nil }

    // These selectors are exercised by the independent compiled Objective-C
    // smoke host, after loading the packaged .saver through NSBundle.
    @objc public func catalogUsage() -> NSDictionary {
        return ["reference": layers.reduce(0) { $0 + $1.drawnReference },
                "original": layers.reduce(0) { $0 + $1.drawnOriginal },
                "blank": layers.reduce(0) { $0 + $1.drawnBlank },
                "live": layers.reduce(0) { $0 + $1.drawnLive }]
    }
    @objc public func useLiveFeed(_ folder: String?) { LiveFeed.shared.use(folder) }
    @objc public func liveReport(_ folder: String) -> NSDictionary {
        guard let catalog = catalog ?? Catalog.load() else { return ["status": "failed"] }
        LiveFeed.shared.use(folder)
        return LiveFeed.shared.report(speed: catalog.liveSpeed, trail: catalog.liveTrail)
    }
    @objc public func liveAtlas() -> NSImage? {
        let feed = LiveFeed.shared, columns = 16, cell = 64, rows = LiveFeed.maximum / 16
        let image = NSImage(size: NSSize(width: CGFloat(columns * cell), height: CGFloat(rows * cell)))
        image.lockFocus(); NSColor.black.setFill(); NSRect(origin: .zero, size: image.size).fill()
        for position in 0..<feed.count {
            guard let path = feed.path(feed.slot(atPosition: position)) else { continue }
            let sprite = Layer.sprite(path: path, cell: CGFloat(cell), pad: 0, level: 1, head: false, glow: false)
            sprite.draw(at: NSPoint(x: CGFloat(position % columns * cell), y: CGFloat((rows - 1 - position / columns) * cell)),
                        from: .zero, operation: .sourceOver, fraction: 1)
        }
        image.unlockFocus(); return image
    }
    @objc public func catalogDiagnostics() -> NSDictionary {
        guard let catalog = catalog ?? Catalog.load() else { return ["status": "failed"] }
        var visible = 0, referenceCounters = 0, originalCounters = 0, curves = 0
        for index in catalog.paths.indices {
            curves += catalog.commands[index].filter { $0[0] == 2 }.count
            guard let metrics = NoumenonView.maskMetrics(catalog.paths[index]) else { return ["status": "failed"] }
            if index == Catalog.blankIndex {
                if metrics.ink != 0 { return ["status": "failed"] }
            } else {
                if metrics.ink == 0 { return ["status": "failed"] }
                visible += 1
                if metrics.holes > 0 {
                    if index < Catalog.originalOffset { referenceCounters += 1 } else { originalCounters += 1 }
                }
            }
        }
        var originalSelections = 0, blankSelections = 0
        for row in 0..<100000 {
            let glyph = catalog.select(seed: 7319, row: row, epoch: 0)
            if glyph >= Catalog.originalOffset { originalSelections += 1 }
            if glyph == Catalog.blankIndex { blankSelections += 1 }
        }
        let passed = visible == 248 && referenceCounters > 0 && originalCounters > 0 && curves > 0
            && (9500...10500).contains(originalSelections) && blankSelections > 0
        return ["status": passed ? "passed" : "failed", "count": 249, "visible_count": visible,
                "reference_sequence_count": 57, "original_count": 192, "blank_index": 4,
                "first_original_id": catalog.ids[57], "fill_rule": "nonzero", "cubic_commands": curves,
                "reference_glyphs_with_counters_at_64px": referenceCounters,
                "original_glyphs_with_counters_at_64px": originalCounters,
                "selection_samples": 100000, "original_selections": originalSelections,
                "blank_selections": blankSelections, "catalog_sha256": catalog.catalogHash,
                "reference_sha256": catalog.referenceHash, "original_sha256": catalog.originalHash]
    }
    @objc public func catalogAtlas() -> NSImage? {
        guard let catalog = catalog ?? Catalog.load() else { return nil }
        let columns = 16, cell = 64
        let rows = (catalog.paths.count + columns - 1) / columns
        let image = NSImage(size: NSSize(width: CGFloat(columns * cell), height: CGFloat(rows * cell)))
        image.lockFocus(); NSColor.black.setFill(); NSRect(origin: .zero, size: image.size).fill()
        for index in catalog.paths.indices {
            let sprite = Layer.sprite(path: catalog.paths[index], cell: CGFloat(cell), pad: 0, level: 1, head: false, glow: false)
            sprite.draw(at: NSPoint(x: CGFloat(index % columns * cell), y: CGFloat((rows - 1 - index / columns) * cell)),
                        from: .zero, operation: .sourceOver, fraction: 1)
        }
        image.unlockFocus(); return image
    }
    private static func maskMetrics(_ path: CGPath) -> (ink: Int, holes: Int)? {
        let side = 64, count = side * side
        var pixels = [UInt8](repeating: 0, count: count * 4)
        let drawn = pixels.withUnsafeMutableBytes { memory -> Bool in
            guard let context = CGContext(data: memory.baseAddress, width: side, height: side,
                bitsPerComponent: 8, bytesPerRow: side * 4, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
            context.scaleBy(x: CGFloat(side) / 100, y: CGFloat(side) / 100)
            context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
            context.addPath(path); context.fillPath(using: .winding)
            return true
        }
        guard drawn else { return nil }
        let filled = (0..<count).map { pixels[$0 * 4 + 3] >= 128 }
        var visited = [Bool](repeating: false, count: count), holes = 0
        for start in 0..<count where !filled[start] && !visited[start] {
            var queue = [start], cursor = 0, edge = false
            visited[start] = true
            while cursor < queue.count {
                let p = queue[cursor], x = p % side, y = p / side
                cursor += 1
                if x == 0 || y == 0 || x == side - 1 || y == side - 1 { edge = true }
                let neighbors = [x > 0 ? p - 1 : -1, x < side - 1 ? p + 1 : -1,
                                 y > 0 ? p - side : -1, y < side - 1 ? p + side : -1]
                for n in neighbors where n >= 0 && !filled[n] && !visited[n] {
                    visited[n] = true; queue.append(n)
                }
            }
            if !edge && queue.count >= 4 { holes += 1 }
        }
        return (filled.filter { $0 }.count, holes)
    }
}
