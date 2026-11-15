import SwiftUI
import UniformTypeIdentifiers

struct StudioView: View {
    @State private var workspace = SaveWorkspace()
    @State private var file: SaveFile?
    @State private var key: String?
    @State private var query = ""
    @State private var showImport = false
    @State private var showExport = false
    @State private var showNewField = false
    @State private var showReplaceDemo = false
    @State private var showReplaceImport = false
    @State private var exportDocument: SaveFileTransfer?
    @State private var exportName = ""
    @State private var status = ""
    @State private var errorMessage: String?

    var body: some View {
        NavigationSplitView {
            sidebar
        } content: {
            fieldList
        } detail: {
            detail
        }
        .navigationSplitViewStyle(.balanced)
        .fileImporter(isPresented: $showImport, allowedContentTypes: [.sasquatchSave, .data], allowsMultipleSelection: true) {
            result in importFiles(result)
        }
        .fileExporter(isPresented: $showExport, document: exportDocument,
                      contentType: .sasquatchSave, defaultFilename: exportName) { result in
            switch result {
            case .success(let url): status = "Exported \(url.lastPathComponent)."
            case .failure(let error): errorMessage = error.localizedDescription
            }
            exportDocument = nil
        }
        .sheet(isPresented: $showNewField) {
            if let file {
                NewFieldView { name, value in
                    if workspace.documents[file]?.value(for: name) != nil {
                        throw NewFieldError.alreadyExists
                    }
                    try apply(file: file, key: name, value: value)
                    key = name
                    query = ""
                }
            }
        }
        .confirmationDialog("Replace working copies?", isPresented: $showReplaceDemo, titleVisibility: .visible) {
            Button("Open Demo", role: .destructive, action: loadDemo)
        } message: {
            Text("The demo will replace this session. Export any edited files you want to keep.")
        }
        .confirmationDialog("Replace working copies?", isPresented: $showReplaceImport, titleVisibility: .visible) {
            Button("Choose Files", action: { showImport = true })
        } message: {
            Text("Opening files starts a new session. Export any edited files you want to keep.")
        }
        .alert("Save Studio", isPresented: Binding(
            get: { errorMessage != nil },
            set: { if !$0 { errorMessage = nil } }
        ), actions: {
            Button("OK", role: .cancel) { errorMessage = nil }
        }, message: {
            Text(errorMessage ?? "")
        })
        .onChange(of: file) { _, _ in query = "" }
    }

    private var sidebar: some View {
        List(selection: $file) {
            Section {
                Button(action: chooseFiles) {
                    Label("Open Save Copies", systemImage: "folder")
                }
                .accessibilityIdentifier("open-saves")
                Button(action: chooseDemo) {
                    Label("Try Demo", systemImage: "leaf")
                }
                .accessibilityIdentifier("open-demo")
            }

            if !workspace.documents.isEmpty {
                Section(workspace.isDemo ? "Demo files" : "Working copies") {
                    ForEach(SaveFile.allCases.filter { workspace.documents[$0] != nil }) { document in
                        Label(document.title, systemImage: document.symbol)
                            .tag(document)
                            .accessibilityIdentifier(document.rawValue)
                    }
                }
            }
        }
        .navigationTitle("Save Studio")
        .navigationSplitViewColumnWidth(min: 210, ideal: 245, max: 300)
    }

    private var fieldList: some View {
        Group {
            if let file, let document = workspace.documents[file] {
                let matching = document.keys.filter {
                    query.isEmpty || $0.localizedCaseInsensitiveContains(query)
                        || file.label(for: $0).localizedCaseInsensitiveContains(query)
                }

                List(selection: $key) {
                    if matching.isEmpty {
                        Text(query.isEmpty ? "This file has no editable fields." : "No matching fields.")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(matching, id: \.self) { name in
                        let title = file.label(for: name)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(title)
                            if title != name {
                                Text(name)
                                    .font(.caption.monospaced())
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .tag(name)
                        .accessibilityIdentifier("field-\(name)")
                    }
                }
                .searchable(text: $query, prompt: "Find a field")
                .navigationTitle(file.title)
                .toolbar {
                    ToolbarItem {
                        Button("Add Field", systemImage: "plus") { showNewField = true }
                    }
                }
            } else {
                ContentUnavailableView("Select a Save File", systemImage: "doc.text")
                    .navigationTitle("Files")
            }
        }
        .navigationSplitViewColumnWidth(min: 240, ideal: 290)
    }

    private var detail: some View {
        Group {
            if let file, let document = workspace.documents[file] {
                if let key, let value = document.value(for: key) {
                    FieldEditor(title: file.label(for: key), key: key, savedValue: value) { value in
                        try apply(file: file, key: key, value: value)
                    }
                    .id(file.rawValue + ":" + key)
                } else {
                    ContentUnavailableView("Select a Field", systemImage: "slider.horizontal.3",
                                           description: Text("Pick a field from \(file.rawValue) to view or edit its JSON value."))
                        .navigationTitle(file.rawValue)
                }
            } else {
                welcome
            }
        }
        .safeAreaInset(edge: .bottom) {
            if !status.isEmpty {
                Text(status)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 20)
                    .padding(.vertical, 10)
                    .background(.bar)
                    .accessibilityIdentifier("session-status")
            }
        }
        .toolbar {
            if file != nil {
                ToolbarItemGroup {
                    Button("Undo", systemImage: "arrow.uturn.backward", action: undo)
                        .disabled(!workspace.canUndo)
                        .accessibilityIdentifier("undo-edit")
                    Button("Export Copy", systemImage: "square.and.arrow.up", action: export)
                        .accessibilityIdentifier("export-copy")
                }
            }
        }
    }

    private var welcome: some View {
        VStack(alignment: .leading, spacing: 24) {
            Image(systemName: "leaf.fill")
                .font(.system(size: 34, weight: .medium))
                .foregroundStyle(Color("StudioAccent"))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 8) {
                Text("Sasquatch Save Studio")
                    .font(.largeTitle.bold())
                    .accessibilityAddTraits(.isHeader)
                Text("Edit a copy of a save file from Files, or explore the app with sample data.")
                    .font(.body)
                    .foregroundStyle(.secondary)
            }
            VStack(alignment: .leading, spacing: 12) {
                Button(action: chooseFiles) {
                    Label("Open Save Copies", systemImage: "folder")
                }
                .buttonStyle(.borderedProminent)
                Button(action: chooseDemo) {
                    Label("Try Demo", systemImage: "leaf")
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(32)
        .frame(maxWidth: 560, alignment: .leading)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func chooseFiles() {
        if workspace.hasChanges {
            showReplaceImport = true
        } else {
            showImport = true
        }
    }

    private func chooseDemo() {
        if workspace.hasChanges {
            showReplaceDemo = true
        } else {
            loadDemo()
        }
    }

    private func loadDemo() {
        do {
            try open(SaveWorkspace.demoDocuments(), demo: true)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func importFiles(_ result: Result<[URL], Error>) {
        do {
            let urls = try result.get()
            guard !urls.isEmpty else { return }
            try open(urls.map(SaveFileTransfer.read), demo: false)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func open(_ documents: [SaveDocument], demo: Bool) throws {
        try workspace.replace(with: documents, demo: demo)
        file = SaveFile.allCases.first { workspace.documents[$0] != nil }
        key = nil
        query = ""
        status = demo ? "Demo session uses sample saves." : "Opened \(documents.count) working copies."
    }

    private func apply(file: SaveFile, key: String, value: String) throws {
        let changed = try workspace.apply(file: file, key: key, json: value)
        status = changed ? "Updated \(file.label(for: key)). Export a copy to keep it." : "That field already has this value."
    }

    private func undo() {
        guard let undone = workspace.undo() else { return }
        file = undone.file
        key = workspace.documents[undone.file]?.value(for: undone.key) == nil ? nil : undone.key
        status = "Undid change to \(undone.file.label(for: undone.key))."
    }

    private func export() {
        guard let file, let document = workspace.documents[file] else { return }
        exportDocument = SaveFileTransfer(data: document.data)
        exportName = "edited-\(file.rawValue)"
        showExport = true
    }
}

private enum NewFieldError: LocalizedError {
    case alreadyExists

    var errorDescription: String? { "That key already exists. Select it in the field list to edit its value." }
}

private struct FieldEditor: View {
    let title: String
    let key: String
    let savedValue: String
    let apply: (String) throws -> Void

    @State private var draft = ""
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if key != title {
                    Text(key)
                        .font(.subheadline.monospaced())
                        .foregroundStyle(.secondary)
                }
                JSONInput(text: $draft)
                if let error {
                    Label(error, systemImage: "exclamationmark.circle")
                        .font(.footnote)
                        .foregroundStyle(.red)
                }
                Button("Apply Change", systemImage: "checkmark") {
                    do {
                        try apply(draft)
                        error = nil
                    } catch {
                        self.error = error.localizedDescription
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(draft == savedValue)
                .accessibilityIdentifier("apply-field")
            }
            .padding(24)
            .frame(maxWidth: 800, alignment: .leading)
        }
        .navigationTitle(title)
        .onChange(of: savedValue, initial: true) { _, value in
            draft = value
            error = nil
        }
    }
}

private struct JSONInput: View {
    @Binding var text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("JSON value")
                .font(.headline)
            TextEditor(text: $text)
                .font(.body.monospaced())
                .foregroundStyle(.primary)
                .scrollContentBackground(.hidden)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
                .padding(8)
                .frame(minHeight: 180)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
                .overlay {
                    RoundedRectangle(cornerRadius: 12)
                        .strokeBorder(.quaternary)
                        .allowsHitTesting(false)
                }
                .accessibilityLabel("JSON value")
                .accessibilityIdentifier("field-json")
            Text("Put text in double quotes. Arrays and objects can contain nested values.")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }
}

private struct NewFieldView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var key = ""
    @State private var json = ""
    @State private var error: String?

    let add: (String, String) throws -> Void

    var body: some View {
        NavigationStack {
            Form {
                TextField("Field key", text: $key)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                JSONInput(text: $json)
                if let error {
                    Text(error).foregroundStyle(.red)
                }
            }
            .navigationTitle("Add Field")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Add") {
                        do {
                            try add(key, json)
                            dismiss()
                        } catch {
                            self.error = error.localizedDescription
                        }
                    }
                    .disabled(key.isEmpty || json.isEmpty)
                }
            }
        }
    }
}
