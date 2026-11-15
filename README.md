# Sneaky Sasquatch Save Studio

A save editor with a macOS browser app and a native iPad app. On Mac, pick a slot and use the dashboard for currencies, vehicles and garage levels, shoes, firefighter and doctor careers, seasonal events, Raccoon Club badges, the bird sanctuary, and album photos. On iPad, open and edit copies of supported save files using Files.

## Release downloads

The current release lists separate downloads for macOS, iPad, and Xcode. The macOS `.dmg` includes an app with its own Python runtime. The iPad Simulator `.app.zip` contains a runnable simulator build. The unsigned device `.ipa` is for development and requires Apple signing before installation on an iPad. Use the Xcode project download to build and sign for your own iPad.

## iPad app

Open [SasquatchSaveStudio.xcodeproj](ipad/SasquatchSaveStudio.xcodeproj) in Xcode and run the shared **SasquatchSaveStudio** scheme on an iPad simulator. The app supports iPadOS 17 and later. For a physical iPad, select your development team under **Signing & Capabilities**, select the connected iPad as the run destination, and press **Run**. See the [iPad setup and file workflow](ipad/README.md).

## Get started on Mac

Open the disk image from GitHub Releases, then copy **Sasquatch Save Studio.app** into Applications. The bundle supports Apple silicon and Intel Macs running macOS 13 or later. In the app, select **Try Demo** to use sample saves or **Open Save Editor** to use your local saves. App backups are stored in `~/Library/Application Support/Sasquatch Save Studio/console-backups/`. GitHub builds are locally signed and lack Apple notarization.

### Run from source

1. Download the repository using **Code → Download ZIP**, or clone it with Git. Unzip a downloaded copy before running it.
2. Install Python 3.10 or newer if `python3 --version` does not show a supported version. The editor has no third-party Python dependencies.
3. Open Terminal in the project folder and run one of these commands.

   ```sh
   ./ss web --demo --open   # Practice with temporary sample saves
   ./ss web --open          # Open the editor for your local game saves
   ```

You can also double-click `Save Studio.command` to open the local editor. Use the URL printed in Terminal to open the editor in Chrome. It normally starts at `http://127.0.0.1:6789`. Keep Terminal running while you edit and press Control+C to stop the server.

For real saves, create a slot in the game and quit with Command+Q. Select that slot in the browser, make a change, and open the same slot in the game to verify it. Demo mode starts with three sample slots and discards them on exit.

## Edit individual save fields

Use **Save fields** to search by key or add a key in an existing supported file. The editor accepts JSON values, including numbers, strings in double quotes, booleans, arrays, and nested objects. It checks the file revision before applying an edit, so reload the file if another edit changed it.

| Save file | Data |
| --- | --- |
| `sasquatch.stuff` | Player state and currencies |
| `variables.stuff` | Progress and flags |
| `equipment.stuff` | Vehicles and equipment |
| `achievements.stuff` | Achievement records |
| `birds.stuff` | Bird guide records |
| `bldg.stuff` | Building records |
| `photos.stuff` | Photo records |

Available files depend on the selected slot. The editor covers supported local JSON save data. Game rules, code, assets, and runtime behavior are outside its scope. The dashboard is the best starting point for operations that coordinate multiple save files.

## Backups and compatibility

The editor listens on loopback and checks that the game is closed before writing. Each file edit backs up the selected slot in `console-backups/`. **Undo Last Edit** restores the most recent edited file if its contents still match the edit. A dashboard action touching several files can require several undos. The backups can include game progress and photos, so keep them private.

The original save mappings were inspected against Sneaky Sasquatch 2.2 build 993. Some advanced fields and garage levels 4–5 have only been verified at the file level, and iCloud can replace local changes.

## Modify the app

- `web/index.html` contains the dashboard and styles.
- `web/save-fields.js` handles field search and editing.
- `tools/ss_web.py` serves the app and dispatches edit requests.
- `tools/slot3_mod.py` handles save reading, validation, backup, and undo.
- `./ss s 1` starts the terminal save editor for slot 1. Use 2 or 3 for other slots.
- `macos/StudioApp.swift` hosts the web editor in a native Mac window. Build the Mac bundle with Xcode tools and a universal framework installer from python.org.

```sh
python3 macos/build.py --python /usr/local/bin/python3 --output /tmp/ssm-build
```

Run the tests from the project folder. The HTTP tests use temporary saves on localhost.

```sh
python3 -m unittest discover -s tests -v
```

This is an unofficial community project. The editor source is available under the MIT License.
