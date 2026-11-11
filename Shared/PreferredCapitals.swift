import UIKit

/// The preferred capitals of the words of a supplement, and the rule that gives a typed word one
/// of its forms. `PreferredCapitals` of scripts/lm-rerank/rerank.py is the same rule for the
/// harness, and docs/domain-pack-design.md describes it.
///
/// A word of the table has a preferred form, as "GPU", "PyTorch" and "vLLM". The keyboard writes
/// one of three forms of it: lower case, the preferred form, or all capitals. The capitals that
/// the person typed pick the form. A capital that the keyboard typed by itself at the start of a
/// sentence is not a capital the person asked for. A word outside the table never changes.
struct PreferredCapitals {
    struct Entry: Equatable {
        /// The form that the domain text writes most often, as "PyTorch" for "pytorch".
        let preferred: String
        /// True for a word that everyday text writes in another form, as "rag" for "RAG". A
        /// plain capital form of it, as "Rag", stays.
        let everyday: Bool
    }

    private let entries: [String: Entry]

    init(entries: [String: Entry]) {
        self.entries = entries
    }

    /// Reads a table of scripts/domain-pack/build_pack.py: one header line, then one line per
    /// word with the word, its frequency, its preferred form or nothing, and the everyday mark.
    /// The table ships inside the app, so a line that breaks this format stops the process.
    init(table: String) {
        var entries: [String: Entry] = [:]
        let lines = table.split(separator: "\n", omittingEmptySubsequences: true)
        precondition(lines.first == "word\tzipf\tpreferred\teveryday", "the table of preferred capitals has other columns")
        for line in lines.dropFirst() {
            let fields = line.split(separator: "\t", omittingEmptySubsequences: false)
            precondition(fields.count == 4, "a line of the table of preferred capitals has \(fields.count) fields")
            guard !fields[2].isEmpty else { continue }
            precondition(fields[2].lowercased() == fields[0] && (fields[3] == "0" || fields[3] == "1"),
                         "the line of \(fields[0]) in the table of preferred capitals is not valid")
            entries[String(fields[0])] = Entry(preferred: String(fields[2]), everyday: fields[3] == "1")
        }
        self.entries = entries
    }

    /// The table `<resource>.tsv` of the bundle. The keyboard cannot give a word of the pack its
    /// form without the table, so a missing file stops the process.
    static func bundled(resource: String) -> PreferredCapitals {
        guard let url = Bundle(for: TypingLexicon.self).url(forResource: resource, withExtension: "tsv"),
            let table = try? String(contentsOf: url, encoding: .utf8)
        else { fatalError("\(resource).tsv is missing from the bundle") }
        return PreferredCapitals(table: table)
    }

    /// The form of `word` to show. `word` is the keyboard's text for the typed word `typed`,
    /// with the capital that `KeyboardTextLogic.restoringCapitals` gave it. `automaticFirst`
    /// says that the keyboard typed the first letter as a capital by itself.
    ///
    /// 1. Without a typed capital the word stays in lower case.
    /// 2. Typed in capitals only, the word stays in capitals.
    /// 3. One capital, the keyboard's own at the start of a sentence: the preferred form. An
    ///    everyday word keeps its plain capital, as "Rag".
    /// 4. One capital that the person typed: the preferred form. An everyday word with that
    ///    capital on its first letter keeps it.
    /// 5. Two or more capitals: the preferred form or all capitals, whichever differs from the
    ///    typed capitals in fewer letters, and the preferred form on a tie.
    func form(of word: String, typed: String, automaticFirst: Bool) -> String {
        let lower = word.lowercased()
        guard let entry = entries[lower], word.allSatisfy({ $0.isASCII && $0.isLetter }) else { return word }
        // A corrected slip of another length keeps only the case of its first letter. The
        // keyboard never corrects a word with a capital after its first letter.
        let capitals: [Bool] = typed.count == lower.count
            ? typed.map { $0.isUppercase }
            : [typed.first?.isUppercase ?? false] + Array(repeating: false, count: lower.count - 1)
        let count = capitals.filter { $0 }.count
        if count == 0 { return word }
        if count == lower.count, count >= 2 { return lower.uppercased() }
        if count == 1, capitals[0], automaticFirst || entry.everyday {
            return entry.everyday ? word : entry.preferred
        }
        if count == 1 { return entry.preferred }
        let toPreferred = zip(capitals, entry.preferred).filter { $0 != $1.isUppercase }.count
        let toAllCapitals = lower.count - count
        return toAllCapitals < toPreferred ? lower.uppercased() : entry.preferred
    }

    /// Gives each word of `restored` its form. `typed` holds the typed words and `textBefore`
    /// the field's text before them. With another count of words than `typed`, only the first
    /// word gets a form, from the first typed word.
    func latch(_ restored: String, typed: String, textBefore: String, type: UITextAutocapitalizationType) -> String {
        var words = restored.split(separator: " ").map(String.init)
        let typedWords = typed.split(separator: " ").map(String.init)
        guard !words.isEmpty, !typedWords.isEmpty else { return restored }
        guard words.count == typedWords.count else {
            words[0] = form(of: words[0], typed: typedWords[0],
                            automaticFirst: KeyboardTextLogic.shouldAutoCapitalize(before: textBefore, type: type))
            return words.joined(separator: " ")
        }
        var before = textBefore
        for index in words.indices {
            words[index] = form(of: words[index], typed: typedWords[index],
                                automaticFirst: KeyboardTextLogic.shouldAutoCapitalize(before: before, type: type))
            before += words[index] + " "
        }
        return words.joined(separator: " ")
    }
}
