# Sasquatch Save Studio for iPhone and iPad

## Build and launch

1. Download and unzip the named `.xcodeproj.zip` release asset, or clone the repository.
2. Open `ipad/SasquatchSaveStudio.xcodeproj` in Xcode 16 or newer.
3. Select the **SasquatchSaveStudio** scheme and an iPhone or iPad simulator. Press **Run** (⌘R). The deployment target is iOS/iPadOS 17.

For a physical iPhone or iPad, connect and select the device in Xcode. In the app target’s **Signing & Capabilities**, choose your development team. If Xcode reports that the bundle ID is already in use, set a unique bundle ID under your team. Follow Xcode’s device setup prompts if needed, then press **Run**. Installing on hardware requires a build signed by your team. The unsigned device IPA in Releases is a development artifact.

To use the prebuilt simulator app, unzip the **iPadOS Simulator** download and drag `SasquatchSaveStudio.app` onto a booted iPad Simulator window in Xcode.

## Work with save copies

1. Tap **Try Demo** to see all seven file types with sample data. Tap **Open Save Copies** to choose your `.stuff` files from Files. You can select several files from the same slot, one copy of each file type.
2. Pick a document and search by the field name or its save key. Select a field to edit its JSON value, or use **Add Field** to add an entry. Tap **Apply Change** to update the working copy, and **Undo** to revert a recent change.
3. Tap **Export Copy** and choose a location in Files. The suggested name begins with `edited-` so you can distinguish it from the source. You can reopen that exported copy in the studio. Export each file you want to keep before leaving the session.

Supported files are `sasquatch.stuff`, `variables.stuff`, `equipment.stuff`, `achievements.stuff`, `birds.stuff`, `bldg.stuff`, and `photos.stuff`. Files can come from a Mac save backup that you copied into Files with AirDrop, iCloud Drive, or an external drive.

iPadOS keeps the installed game’s private saves and resources in its own sandbox. The studio reads files you select and exports separate copies. Gameplay and the installed game are unaffected by using the iPad editor. The iPad workflow does not install an edited save back into the game.

## Run tests

Press **Test** (⌘U) with an iPad simulator selected. XCTest covers the file and edit model, and the simulator launch test covers the demo editing and undo workflow.
