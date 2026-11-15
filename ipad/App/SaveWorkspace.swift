import CoreFoundation
import Foundation

enum SaveFile: String, CaseIterable, Identifiable {
    case player = "sasquatch.stuff"
    case variables = "variables.stuff"
    case equipment = "equipment.stuff"
    case achievements = "achievements.stuff"
    case birds = "birds.stuff"
    case buildings = "bldg.stuff"
    case photos = "photos.stuff"

    var id: Self { self }

    var title: String {
        switch self {
        case .player: "Player & currencies"
        case .variables: "Progress & flags"
        case .equipment: "Vehicles & gear"
        case .achievements: "Achievements"
        case .birds: "Bird guide"
        case .buildings: "Buildings"
        case .photos: "Photo records"
        }
    }

    var symbol: String {
        switch self {
        case .player: "person.crop.circle"
        case .variables: "flag"
        case .equipment: "car"
        case .achievements: "medal"
        case .birds: "bird"
        case .buildings: "building.2"
        case .photos: "photo"
        }
    }

    private static let currencyLabels = [
        "coins": "Wallet coins", "bankcoin": "Bank coins", "ptkt": "Arcade tickets",
        "lumber": "Lumber", "cf": "Camera film", "pap": "Photo album pages",
        "pb": "Poop bags", "tb": "Tennis balls", "st": "Underwater trash",
        "hwcd": "Halloween candy", "xmcc": "Christmas candy canes", "4o": "Raccoon Club badges",
    ]

    func label(for key: String) -> String {
        switch self {
        case .player:
            Self.currencyLabels[key] ?? [
                "current_map": "Current map", "day": "Game day",
                "togtool": "Equipment toggles", "map_locations": "Map locations",
            ][key] ?? key
        case .variables:
            ["flags": "Progress flags", "sM": "Firefighter funding", "Og": "Firefighter rank",
             "sR": "Doctor rank", "nt": "Bird sanctuary funding", "Rk": "Bird sanctuary level"][key] ?? key
        case .equipment: ["vehicles": "Owned vehicles", "equipment": "Owned gear"][key] ?? key
        case .achievements: ["eb": "Earned badges", "qb": "Queued badges"][key] ?? key
        case .birds: key == "bs" ? "Bird sightings" : key
        case .buildings: key == "b" ? "Building records" : key
        case .photos: key == "photos" ? "Album photos" : key
        }
    }

    init(filename: String) throws {
        let original = filename.hasPrefix("edited-") ? String(filename.dropFirst(7)) : filename
        guard let file = Self(rawValue: original.lowercased()) else {
            throw SaveError.unsupportedFile(filename)
        }
        self = file
    }

    fileprivate func validate(_ fields: [String: Any]) throws {
        if let version = fields["VERSION"] {
            let supported = integer(version).map { self == .player ? (1...2).contains($0) : $0 == 1 }
            guard supported == true else { throw SaveError.invalidStructure(rawValue) }
        }

        switch self {
        case .player:
            guard fields["VERSION"] != nil,
                  fields["coins"] != nil || (fields["current_map"] is String && fields["map_locations"] is [String: Any]),
                  fields["togtool"].map({ $0 is [String: Any] }) ?? true else {
                throw SaveError.invalidStructure(rawValue)
            }
            let maximum: Int64 = 2_000_000_000
            for key in Self.currencyLabels.keys {
                if let value = fields[key] {
                    guard let balance = integer(value), (-maximum...maximum).contains(balance) else {
                        throw SaveError.invalidBalance
                    }
                }
            }
            let total = (integer(fields["coins"]) ?? 0) + (integer(fields["bankcoin"]) ?? 0)
            guard (-maximum...maximum).contains(total) else { throw SaveError.invalidBalance }
        case .variables:
            guard fields["flags"] is [String: Any] else { throw SaveError.invalidStructure(rawValue) }
        case .equipment:
            guard let vehicles = fields["vehicles"] as? [[String: Any]],
                  vehicles.allSatisfy({ $0["id"] is String }),
                  fields["equipment"].map({ $0 is [Any] }) ?? true else {
                throw SaveError.invalidStructure(rawValue)
            }
        case .achievements:
            try validateTypes(fields, keys: ["eb", "qb"], type: [Any].self)
        case .birds:
            try validateTypes(fields, keys: ["bs"], type: [String: Any].self)
        case .buildings:
            try validateTypes(fields, keys: ["b"], type: [Any].self)
        case .photos:
            try validateTypes(fields, keys: ["photos"], type: [Any].self)
        }
    }

    private func validateTypes<Value>(_ fields: [String: Any], keys: [String], type: Value.Type) throws {
        for key in keys {
            guard fields[key] is Value else { throw SaveError.invalidStructure(rawValue) }
        }
    }

    private func integer(_ value: Any?) -> Int64? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              let integer = Int64(number.stringValue) else { return nil }
        return integer
    }
}

enum SaveError: LocalizedError {
    case unsupportedFile(String)
    case invalidStructure(String)
    case invalidJSON
    case invalidKey
    case duplicateFile(SaveFile)
    case missingFile
    case typeMismatch
    case invalidBalance
    case tooLarge

    var errorDescription: String? {
        switch self {
        case .unsupportedFile(let name): "“\(name)” is not a supported save file."
        case .invalidStructure(let name): "“\(name)” doesn’t match a supported save format."
        case .invalidJSON: "Enter valid JSON. Use double quotes around text."
        case .invalidKey: "Enter a nonempty field key other than VERSION."
        case .duplicateFile(let file): "Choose one copy of \(file.rawValue) at a time."
        case .missingFile: "Open a save file first."
        case .typeMismatch: "Use the same JSON type as the existing field."
        case .invalidBalance: "Each balance and the wallet plus bank must be whole numbers within ±2 billion."
        case .tooLarge: "Save files must be 10 MB or smaller."
        }
    }
}

struct SaveDocument {
    static let maximumBytes = 10 * 1024 * 1024

    let file: SaveFile
    private(set) var data: Data
    private var fields: [String: Any]

    var keys: [String] {
        fields.keys.filter { $0 != "VERSION" }.sorted {
            let lhs = file.label(for: $0)
            let rhs = file.label(for: $1)
            if lhs == rhs { return $0 < $1 }
            return lhs.localizedStandardCompare(rhs) == .orderedAscending
        }
    }

    init(file: SaveFile, data: Data) throws {
        guard data.count <= Self.maximumBytes else { throw SaveError.tooLarge }
        guard let fields = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw SaveError.invalidStructure(file.rawValue)
        }
        try file.validate(fields)
        self.file = file
        self.data = data
        self.fields = fields
    }

    func value(for key: String) -> String? {
        guard let value = fields[key], let encoded = try? Self.encode(value) else { return nil }
        return String(decoding: encoded, as: UTF8.self)
    }

    mutating func setField(_ key: String, json: String) throws -> Bool {
        guard !key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, key != "VERSION" else {
            throw SaveError.invalidKey
        }
        let input = Data(json.utf8)
        guard input.count <= Self.maximumBytes else { throw SaveError.tooLarge }
        guard let value = try? JSONSerialization.jsonObject(with: input, options: [.fragmentsAllowed]) else {
            throw SaveError.invalidJSON
        }
        if let existing = fields[key], !(existing is NSNull), !Self.sameType(existing, value) {
            throw SaveError.typeMismatch
        }
        let encodedValue = try Self.encode(value)
        if encodedValue == fields[key].flatMap({ try? Self.encode($0) }) { return false }

        var updated = fields
        updated[key] = value
        try file.validate(updated)
        let encoded = try Self.encode(updated) + Data([10])
        guard encoded.count <= Self.maximumBytes else { throw SaveError.tooLarge }
        data = encoded
        fields = updated
        return true
    }

    private static func encode(_ value: Any) throws -> Data {
        try JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys, .fragmentsAllowed, .withoutEscapingSlashes])
    }

    private static func sameType(_ lhs: Any, _ rhs: Any) -> Bool {
        if let left = lhs as? NSNumber {
            guard let right = rhs as? NSNumber else { return false }
            return (CFGetTypeID(left) == CFBooleanGetTypeID()) == (CFGetTypeID(right) == CFBooleanGetTypeID())
        }
        if lhs is String { return rhs is String }
        if lhs is [String: Any] { return rhs is [String: Any] }
        return lhs is [Any] && rhs is [Any]
    }
}

struct SaveWorkspace {
    private struct Edit {
        let before: SaveDocument
        let key: String
    }

    private(set) var documents: [SaveFile: SaveDocument] = [:]
    private(set) var isDemo = false
    private var history: [Edit] = []
    private var originalData: [SaveFile: Data] = [:]
    private let undoLimit = 20

    var canUndo: Bool { !history.isEmpty }
    var hasChanges: Bool { documents.contains { originalData[$0.key] != $0.value.data } }

    mutating func replace(with documents: [SaveDocument], demo: Bool = false) throws {
        var imported: [SaveFile: SaveDocument] = [:]
        for document in documents {
            guard imported.updateValue(document, forKey: document.file) == nil else {
                throw SaveError.duplicateFile(document.file)
            }
        }
        self.documents = imported
        originalData = imported.mapValues(\.data)
        isDemo = demo
        history = []
    }

    mutating func apply(file: SaveFile, key: String, json: String) throws -> Bool {
        guard let original = documents[file] else { throw SaveError.missingFile }
        var updated = original
        guard try updated.setField(key, json: json) else { return false }
        documents[file] = updated
        history.append(Edit(before: original, key: key))
        if history.count > undoLimit { history.removeFirst() }
        return true
    }

    mutating func undo() -> (file: SaveFile, key: String)? {
        guard let edit = history.popLast() else { return nil }
        documents[edit.before.file] = edit.before
        return (edit.before.file, edit.key)
    }

    static func demoDocuments() throws -> [SaveDocument] {
        let values: [SaveFile: String] = [
            .player: #"{"VERSION":2,"coins":1250,"bankcoin":5000,"ptkt":250,"lumber":24,"day":16,"togtool":{"runshoes":1}}"#,
            .variables: #"{"VERSION":1,"flags":{"BZ":1},"sM":25000,"sR":1,"nt":3000,"Rk":2}"#,
            .equipment: #"{"VERSION":1,"vehicles":[{"id":"sportscar","lvl":1}],"equipment":[{"type":2524}]}"#,
            .achievements: #"{"VERSION":1,"eb":["0M"],"qb":[]}"#,
            .birds: #"{"VERSION":1,"bs":{}}"#,
            .buildings: #"{"VERSION":1,"b":[]}"#,
            .photos: #"{"VERSION":1,"photos":[]}"#,
        ]
        return try SaveFile.allCases.map { file in
            try SaveDocument(file: file, data: Data(values[file, default: ""].utf8))
        }
    }
}
