import SwiftUI

@main
struct SasquatchSaveStudioApp: App {
    var body: some Scene {
        WindowGroup {
            StudioView()
                .tint(Color("StudioAccent"))
        }
    }
}
