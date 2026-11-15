import XCTest

final class StudioLaunchTests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testLaunchDemoEditAndUndo() {
        let app = XCUIApplication()
        app.launch()

        XCTAssertTrue(app.staticTexts["Sasquatch Save Studio"].waitForExistence(timeout: 10))
        app.buttons.matching(NSPredicate(format: "label == %@", "Try Demo")).firstMatch.tap()

        let wallet = app.descendants(matching: .any)["field-coins"].firstMatch
        XCTAssertTrue(wallet.waitForExistence(timeout: 6))
        wallet.tap()

        let field = app.textViews["field-json"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        XCTAssertEqual(field.value as? String, "1250")
        field.tap()
        field.typeKey("a", modifierFlags: .command)
        field.typeText("9300")
        app.buttons["apply-field"].tap()

        XCTAssertTrue(app.staticTexts["Updated Wallet coins. Export a copy to keep it."].waitForExistence(timeout: 5))
        XCTAssertEqual(field.value as? String, "9300")
        app.buttons["undo-edit"].tap()
        XCTAssertEqual(field.value as? String, "1250")
        XCTAssertTrue(app.buttons["export-copy"].exists)
    }
}
