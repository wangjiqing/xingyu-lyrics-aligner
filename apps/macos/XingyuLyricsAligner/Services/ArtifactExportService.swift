import Foundation

enum ArtifactExportError: LocalizedError {
    case unsupportedSchema(Int?)
    case unsafePath(String)
    case missingFile(String)
    case duplicateArtifact(String)

    var errorDescription: String? {
        switch self {
        case .unsupportedSchema(let version): "不支持 artifacts schema：\(version.map(String.init) ?? "缺失")"
        case .unsafePath(let path): "产物路径不安全：\(path)"
        case .missingFile(let path): "产物文件不存在：\(path)"
        case .duplicateArtifact(let value): "产物清单存在重复或冲突：\(value)"
        }
    }
}

actor ArtifactExportService {
    private let fileManager = FileManager.default

    func export(
        result: WorkerResult,
        workspace: JobWorkspace,
        selection: DesktopExports,
        destinationRoot: URL,
        songName: String
    ) throws -> [URL] {
        guard result.artifactsSchemaVersion == 1 else {
            throw ArtifactExportError.unsupportedSchema(result.artifactsSchemaVersion)
        }
        let jobRoot = workspace.jobDirectory.standardizedFileURL.resolvingSymlinksInPath()
        try fileManager.createDirectory(at: destinationRoot, withIntermediateDirectories: true)
        let rootValues = try destinationRoot.resourceValues(forKeys: [.isSymbolicLinkKey])
        guard rootValues.isSymbolicLink != true else { throw ArtifactExportError.unsafePath(destinationRoot.path) }
        let destination = destinationRoot.appendingPathComponent(sanitizedFolderName(songName), isDirectory: true)
        try fileManager.createDirectory(at: destination, withIntermediateDirectories: true)
        let destinationValues = try destination.resourceValues(forKeys: [.isSymbolicLinkKey])
        guard destinationValues.isSymbolicLink != true else { throw ArtifactExportError.unsafePath(destination.path) }
        var exported: [URL] = []
        var kinds = Set<String>()
        var sources = Set<String>()
        for artifact in result.artifacts ?? [] where artifact.exportable && isSelected(artifact.kind, selection) {
            let relative = artifact.relativePath
            guard !relative.hasPrefix("/"), !relative.split(separator: "/").contains("..") else {
                throw ArtifactExportError.unsafePath(relative)
            }
            let unresolvedSource = workspace.jobDirectory.appendingPathComponent(relative).standardizedFileURL
            let unresolvedValues = try unresolvedSource.resourceValues(forKeys: [.isSymbolicLinkKey])
            guard unresolvedValues.isSymbolicLink != true else { throw ArtifactExportError.unsafePath(relative) }
            let source = unresolvedSource.resolvingSymlinksInPath()
            guard source.path == jobRoot.path || source.path.hasPrefix(jobRoot.path + "/") else {
                throw ArtifactExportError.unsafePath(relative)
            }
            let values = try source.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
            guard values.isRegularFile == true, values.isSymbolicLink != true else {
                throw ArtifactExportError.missingFile(relative)
            }
            let kindKey = outputName(for: artifact.kind)
            guard kinds.insert(kindKey).inserted else { throw ArtifactExportError.duplicateArtifact(kindKey) }
            guard sources.insert(source.path).inserted else { throw ArtifactExportError.duplicateArtifact(relative) }
            let target = destination.appendingPathComponent(kindKey)
            let temporary = destination.appendingPathComponent(".\(kindKey).\(UUID().uuidString).tmp")
            do {
                try fileManager.copyItem(at: source, to: temporary)
                let handle = try FileHandle(forWritingTo: temporary)
                try handle.synchronize()
                try handle.close()
                let sourceSize = try source.resourceValues(forKeys: [.fileSizeKey]).fileSize
                let temporarySize = try temporary.resourceValues(forKeys: [.fileSizeKey]).fileSize
                guard sourceSize == temporarySize else { throw ArtifactExportError.missingFile(relative) }
                if fileManager.fileExists(atPath: target.path) {
                    _ = try fileManager.replaceItemAt(target, withItemAt: temporary)
                } else {
                    try fileManager.moveItem(at: temporary, to: target)
                }
            } catch {
                try? fileManager.removeItem(at: temporary)
                throw error
            }
            exported.append(target)
        }
        return exported
    }

    private func isSelected(_ kind: ArtifactKind, _ exports: DesktopExports) -> Bool {
        switch kind {
        case .lrc: exports.lrc
        case .swlrc: exports.swlrc
        case .vocals: exports.vocals
        case .accompaniment: exports.accompaniment
        case .alignmentJSON: exports.alignmentJSON
        case .reportJSON: exports.reportJSON
        case .unknown: false
        }
    }

    private func outputName(for kind: ArtifactKind) -> String {
        switch kind {
        case .lrc: "lyrics.lrc"
        case .swlrc: "lyrics.swlrc"
        case .vocals: "vocals.wav"
        case .accompaniment: "accompaniment.wav"
        case .alignmentJSON: "alignment.json"
        case .reportJSON: "report.json"
        case .unknown(let value): value.lowercased()
        }
    }

    private func sanitizedFolderName(_ value: String) -> String {
        let invalid = CharacterSet(charactersIn: "/:")
        let cleaned = value.components(separatedBy: invalid).joined(separator: "-")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return cleaned.isEmpty ? "Xingyu Export" : cleaned
    }
}
