import AppKit
import Foundation

// Command-line tool for the Mac runner. The tool asks NSSpellChecker, the spell checker of macOS,
// for its automatic correction of each typed token of the English cases.
//
// Usage: nsspellchecker context|word <cases.jsonl> <predictions.jsonl>
//   context  the checked string holds the context of the case, the tokens corrected so far and
//            the token, and the word range covers the token
//   word     the checked string holds the token alone
//
// NSSpellChecker gets a string and never a touch position, so the tool measures the language
// side of Apple's correction without the touch side of the keyboard.

struct EvalCase: Decodable {
    let id: String
    let context: String
    let typed: String
}

struct Prediction: Encodable {
    let id: String
    let output: String
}

func stop(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}

let arguments = CommandLine.arguments
guard arguments.count == 4, ["context", "word"].contains(arguments[1]) else {
    stop("usage: nsspellchecker context|word <cases.jsonl> <predictions.jsonl>")
}
let useContext = arguments[1] == "context"
let language = "en_US"

let checker = NSSpellChecker.shared
checker.automaticallyIdentifiesLanguages = false
guard checker.setLanguage(language) else {
    stop("NSSpellChecker does not offer the language \(language). Offered: \(checker.availableLanguages)")
}
let documentTag = NSSpellChecker.uniqueSpellDocumentTag()
print("macOS \(ProcessInfo.processInfo.operatingSystemVersionString), NSSpellChecker language \(checker.language()), "
    + "automatic spelling correction setting \(NSSpellChecker.isAutomaticSpellingCorrectionEnabled), mode \(arguments[1])")

let decoder = JSONDecoder()
let encoder = JSONEncoder()
let cases = try String(contentsOfFile: arguments[2], encoding: .utf8)
    .split(separator: "\n")
    .map { try decoder.decode(EvalCase.self, from: Data($0.utf8)) }

var lines: [String] = []
var changedTokens = 0
for item in cases {
    var written = item.context.isEmpty ? "" : item.context + " "
    var corrected: [String] = []
    for token in item.typed.split(separator: " ").map(String.init) {
        let text = useContext ? written + token : token
        let tokenLength = (token as NSString).length
        let range = NSRange(location: (text as NSString).length - tokenLength, length: tokenLength)
        let correction = checker.correction(forWordRange: range, in: text, language: language, inSpellDocumentWithTag: documentTag)
        // NSSpellChecker returns nil when it does not propose a correction, and the token stays.
        let word = correction ?? token
        if word != token {
            changedTokens += 1
        }
        corrected.append(word)
        written += word + " "
    }
    let prediction = Prediction(id: item.id, output: corrected.joined(separator: " "))
    lines.append(String(decoding: try encoder.encode(prediction), as: UTF8.self))
}
try (lines.joined(separator: "\n") + "\n").write(toFile: arguments[3], atomically: true, encoding: .utf8)
print("\(cases.count) cases, \(changedTokens) tokens changed, written to \(arguments[3])")
