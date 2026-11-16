import AppKit
import SwiftUI
import WebKit
import UniformTypeIdentifiers

@main
struct StudioApp: App {
    @NSApplicationDelegateAdaptor(StudioDelegate.self) private var delegate

    var body: some Scene {
        WindowGroup("Sasquatch Save Studio") {
            StudioWindow(server: delegate.server)
        }
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Close Editor Session") { delegate.server.stop() }
            }
        }
    }
}

@MainActor
final class StudioDelegate: NSObject, NSApplicationDelegate {
    let server = StudioServer()

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        server.stop()
    }
}

private struct StudioWindow: View {
    @ObservedObject var server: StudioServer
    @State private var launched = false
    @State private var showIsolationInfo = false

    var body: some View {
        Group {
            if let url = server.url {
                VStack(spacing: 0) {
                    HStack {
                        Text(server.isDemo ? "Demo · sample saves only" : "Editing real game saves")
                        Spacer()
                        Button("Back") { server.stop() }
                        if !server.isDemo {
                            Button("Done & Launch Sneaky Sasquatch") { server.launchGame() }
                                .buttonStyle(.borderedProminent)
                                .disabled(server.isLaunching)
                        }
                    }.padding(12)
                    Divider()
                    EditorWebView(url: url).id(url)
                }
            } else {
                VStack(alignment: .leading, spacing: 18) {
                    Image(systemName: "slider.horizontal.3")
                        .font(.system(size: 32, weight: .medium))
                        .foregroundStyle(Color(red: 0.25, green: 0.55, blue: 0.41))
                        .accessibilityHidden(true)
                    Text("Sasquatch Save Studio")
                        .font(.largeTitle.bold())
                    Text("Edit Sneaky Sasquatch saves on this Mac, or try the controls with sample saves.")
                        .foregroundStyle(.secondary)
                    if let message = server.error {
                        Label(message, systemImage: "exclamationmark.circle")
                            .foregroundStyle(.red)
                    }
                    if server.isRunning {
                        ProgressView("Starting the editor…")
                    } else {
                        HStack {
                            Button("Launch Sneaky Sasquatch") { server.launchGame() }
                                .buttonStyle(.borderedProminent)
                            Button("Edit Real Game Saves") { server.start(demo: false) }
                                .buttonStyle(.bordered)
                        }
                        HStack {
                            Button("Try Demo Editor") { server.start(demo: true) }
                            Button("Separate Game Saves…") { showIsolationInfo = true }
                        }
                        if server.isLaunching {
                            ProgressView("Opening Sneaky Sasquatch…")
                        }
                        HStack {
                            Text("Launch uses the installed game and its existing saves. No game is included.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                .frame(maxWidth: 440, alignment: .leading)
                .padding(24)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .frame(minWidth: 650, idealWidth: 1100, minHeight: 420, idealHeight: 800)
        .alert("Separate game saves", isPresented: $showIsolationInfo) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("A second playable save account is not available in this release. The installed game uses its own save container and iCloud settings. Demo mode is an editor preview, not a second game. The previous re-signed game copy failed Apple Arcade validation.")
        }
        .task {
            if !launched && ProcessInfo.processInfo.arguments.contains("--demo") {
                launched = true
                server.start(demo: true)
            }
        }
    }
}

private struct EditorWebView: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> WKWebView {
        let view = WKWebView()
        view.load(URLRequest(url: url))
        return view
    }

    func updateNSView(_ view: WKWebView, context: Context) {}
}

@MainActor
final class StudioServer: ObservableObject {
    @Published private(set) var url: URL?
    @Published private(set) var error: String?
    @Published private(set) var isRunning = false

    @Published private(set) var isDemo = false
    @Published private(set) var isLaunching = false

    func launchGame() {
        guard !isLaunching else { return }
        let identifier = "com.rac7.SneakySasquatchMac"
        var gameURL = NSWorkspace.shared.urlForApplication(withBundleIdentifier: identifier)
        if gameURL == nil {
            let picker = NSOpenPanel()
            picker.title = "Choose your installed Sneaky Sasquatch app"
            picker.canChooseDirectories = false
            picker.canChooseFiles = true
            picker.allowedContentTypes = [.applicationBundle]
            picker.directoryURL = URL(fileURLWithPath: "/Applications")
            guard picker.runModal() == .OK else { return }
            gameURL = picker.url
        }
        guard let gameURL, Bundle(url: gameURL)?.bundleIdentifier == identifier else {
            error = "Choose the original installed Sneaky Sasquatch app. A test copy cannot be launched here."
            return
        }
        let editor = process
        isLaunching = true
        stop()
        Task { @MainActor in
            // Let the server finish shutdown before allowing the game to load saves.
            for _ in 0..<100 {
                if editor?.isRunning != true { break }
                try? await Task.sleep(nanoseconds: 100_000_000)
            }
            guard editor?.isRunning != true else {
                error = "The editor has not finished closing. Wait and try again."
                isLaunching = false
                return
            }
            let configuration = NSWorkspace.OpenConfiguration()
            configuration.activates = true
            NSWorkspace.shared.openApplication(at: gameURL, configuration: configuration) { _, failure in
                Task { @MainActor in
                    self.isLaunching = false
                    self.error = failure.map { "Could not launch Sneaky Sasquatch: " + $0.localizedDescription }
                }
            }
        }
    }

    private var process: Process?
    private var output: Pipe?
    private var pendingOutput = Data()

    func start(demo: Bool) {
        guard !isRunning, !isLaunching, let resources = Bundle.main.resourceURL,
              let executables = Bundle.main.executableURL?.deletingLastPathComponent() else { return }

        let child = Process()
        let pipe = Pipe()
        let script = resources.appendingPathComponent("tools/ss_web.py")
        child.executableURL = executables.appendingPathComponent("studio-python")
        child.standardOutput = pipe
        child.standardError = pipe
        child.environment = [
            "PATH": "/usr/bin:/bin",
            "HOME": NSHomeDirectory(),
            "PYTHONHOME": resources.appendingPathComponent("Python").path,
        ]
        child.arguments = ["-B", "-s", script.path, "--port", "0"]

        if demo {
            child.arguments?.append("--demo")
        } else {
            let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            child.arguments?.append(contentsOf: ["--data-dir", support.appendingPathComponent("Sasquatch Save Studio").path])
        }

        output = pipe
        process = child
        pendingOutput.removeAll()
        error = nil
        isRunning = true
        isDemo = demo
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
            } else {
                Task { @MainActor in
                    self?.receive(data, from: child)
                }
            }
        }
        child.terminationHandler = { [weak self] _ in
            Task { @MainActor in
                guard self?.process === child else { return }
                self?.stop()
                self?.error = "The local editor stopped. Try opening it again."
            }
        }
        do {
            try child.run()
        } catch {
            stop()
            self.error = error.localizedDescription
        }
    }

    func stop() {
        output?.fileHandleForReading.readabilityHandler = nil
        let child = process
        process = nil
        output = nil
        isRunning = false
        url = nil
        if let child, child.isRunning { child.interrupt() }
    }

    private func receive(_ data: Data, from child: Process) {
        guard process === child, url == nil else { return }
        pendingOutput.append(data)
        let prefix = "Sasquatch editor: "
        while let newline = pendingOutput.firstIndex(of: 10) {
            let line = String(decoding: pendingOutput[..<newline], as: UTF8.self)
            pendingOutput.removeSubrange(...newline)
            if line.hasPrefix(prefix), let localURL = URL(string: String(line.dropFirst(prefix.count))),
               localURL.scheme == "http", localURL.host == "127.0.0.1", localURL.port != nil {
                url = localURL
                break
            }
        }
    }
}
