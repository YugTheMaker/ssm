import Foundation
import XCTest
@testable import SasquatchSaveStudio

final class SaveWorkspaceTests: XCTestCase {
    func testDemoEditsUndoAndSourceIsolation() throws {
        let samples = try SaveWorkspace.demoDocuments()
        var workspace = SaveWorkspace()
        try workspace.replace(with: samples, demo: true)

        XCTAssertTrue(workspace.isDemo)
        XCTAssertEqual(workspace.documents.count, 7)
        XCTAssertEqual(workspace.documents[.player]?.value(for: "coins"), "1250")
        XCTAssertTrue(try workspace.apply(file: .player, key: "coins", json: "9300"))
        XCTAssertTrue(workspace.hasChanges)
        XCTAssertFalse(try workspace.apply(file: .player, key: "coins", json: "9300"))
        XCTAssertEqual(workspace.documents[.player]?.value(for: "coins"), "9300")
        XCTAssertEqual(samples.first?.value(for: "coins"), "1250")
        XCTAssertEqual(workspace.documents[.variables]?.value(for: "sM"), "25000")
        XCTAssertEqual(workspace.undo()?.key, "coins")
        XCTAssertFalse(workspace.hasChanges)
        XCTAssertEqual(workspace.documents[.player]?.data, samples.first?.data)
        XCTAssertNil(workspace.undo())
    }

    func testRejectsInvalidEditsWithoutChangingDocument() throws {
        let data = Data(#"{"VERSION":2,"coins":1000,"bankcoin":500,"label":"Optional","flag":true}"#.utf8)
        var document = try SaveDocument(file: .player, data: data)

        for (key, json) in [
            ("coins", "2000000000"), ("coins", "{"), ("coins", "true"), ("coins", "1000.5"),
            ("flag", "0"), ("label", "false"), ("VERSION", "1"), ("", "3"),
        ] {
            XCTAssertThrowsError(try document.setField(key, json: json))
            XCTAssertEqual(document.data, data)
        }
        XCTAssertFalse(document.keys.contains("VERSION"))
    }

    func testReadsAFileAndRoundTripsEditedCopy() throws {
        XCTAssertEqual(SaveFileTransfer.readableContentTypes.first?.preferredFilenameExtension, "stuff")
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let original = directory.appendingPathComponent(SaveFile.variables.rawValue)
        let source = Data(#"{"VERSION":1,"flags":{"BZ":1},"sM":25000,"large":9223372036854775807}"#.utf8)
        try source.write(to: original)
        var document = try SaveFileTransfer.read(original)
        XCTAssertTrue(try document.setField("flags", json: #"{"BZ":1,"demo":true}"#))
        XCTAssertTrue(try document.setField("new_key", json: "[9, null]"))

        let exported = directory.appendingPathComponent("edited-variables.stuff")
        try document.data.write(to: exported)
        let reread = try SaveFileTransfer.read(exported)

        XCTAssertEqual(reread.file, .variables)
        XCTAssertEqual(reread.value(for: "new_key"), document.value(for: "new_key"))
        XCTAssertEqual(reread.value(for: "large"), "9223372036854775807")
        XCTAssertEqual(try Data(contentsOf: original), source)
    }

    func testRejectsDuplicateFilesAndLeavesOldSessionUsable() throws {
        let samples = try SaveWorkspace.demoDocuments()
        let sample = try XCTUnwrap(samples.first)
        var workspace = SaveWorkspace()
        try workspace.replace(with: samples)

        XCTAssertThrowsError(try workspace.replace(with: [sample, sample]))
        XCTAssertEqual(workspace.documents.count, 7)
        XCTAssertThrowsError(try SaveFile(filename: "user.stuff"))
        XCTAssertThrowsError(try SaveDocument(file: .equipment, data: Data(#"{"vehicles":[{"lvl":1}]}"#.utf8)))
    }
}
