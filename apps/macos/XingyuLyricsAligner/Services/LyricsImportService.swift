import Foundation

enum LyricsImportService {
    private static let timedTag = try! NSRegularExpression(pattern: #"\[(?:\d{1,3}:)?\d{1,2}:\d{1,2}(?:[.:]\d{1,3})?\]"#)
    private static let metadataTag = try! NSRegularExpression(pattern: #"^\[(?:ar|al|ti|by|offset|re|ve):.*\]$"#, options: .caseInsensitive)

    static func normalizedLyrics(from text: String, fileExtension: String? = nil) -> String {
        guard fileExtension?.lowercased() == "lrc" || text.contains("[") else {
            return text.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        let output = text.components(separatedBy: .newlines).compactMap { raw -> String? in
            let trimmed = raw.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty else { return nil }
            let fullRange = NSRange(trimmed.startIndex..., in: trimmed)
            if metadataTag.firstMatch(in: trimmed, range: fullRange) != nil { return nil }
            let stripped = timedTag.stringByReplacingMatches(in: trimmed, range: fullRange, withTemplate: "")
                .trimmingCharacters(in: .whitespaces)
            return stripped.isEmpty ? nil : stripped
        }
        return output.joined(separator: "\n")
    }
}
