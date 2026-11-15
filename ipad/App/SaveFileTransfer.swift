import SwiftUI
import UniformTypeIdentifiers

extension UTType {
    static let sasquatchSave = UTType(importedAs: "io.github.yugthemaker.ssm.stuff", conformingTo: .data)
}

struct SaveFileTransfer: FileDocument {
    static var readableContentTypes: [UTType] { [.sasquatchSave] }

    let data: Data

    init(data: Data) {
        self.data = data
    }

    init(configuration: ReadConfiguration) throws {
        guard let data = configuration.file.regularFileContents else { throw CocoaError(.fileReadCorruptFile) }
        self.data = data
    }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: data)
    }

    static func read(_ url: URL) throws -> SaveDocument {
        let file = try SaveFile(filename: url.lastPathComponent)
        let canAccess = url.startAccessingSecurityScopedResource()
        defer { if canAccess { url.stopAccessingSecurityScopedResource() } }

        var coordinationError: NSError?
        var result: Result<SaveDocument, Error>?
        NSFileCoordinator().coordinate(readingItemAt: url, options: [], error: &coordinationError) { coordinatedURL in
            result = Result {
                let handle = try FileHandle(forReadingFrom: coordinatedURL)
                defer { try? handle.close() }
                let data = try handle.read(upToCount: SaveDocument.maximumBytes + 1) ?? Data()
                return try SaveDocument(file: file, data: data)
            }
        }
        if let coordinationError { throw coordinationError }
        guard let result else { throw CocoaError(.fileReadUnknown) }
        return try result.get()
    }
}
