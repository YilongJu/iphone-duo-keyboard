"""Builds Shared/emoji-suggestions.tsv, the table of emoji that the keyboard offers for a word.

The table holds a word and at most two emoji for each word, for English and for Chinese. The
script generates the pairs of a word and an emoji from the sources below, and the hand-written
files beside this script correct the result. docs/emoji-suggestions.md describes every rule.

Sources:
1. The Unicode CLDR emoji annotations, version 49.0.0 (cldr-json package cldr-annotations-full),
   for English and Chinese: the keywords and the spoken name of each emoji. Unicode License v3:
   https://www.unicode.org/license.txt
2. Unicode emoji-test.txt for Emoji 17.0: the list of the emoji. Unicode License v3.
3. emojilib 4.0.3 (MIT license, https://github.com/muan/emojilib): English keywords of each emoji.
4. The Unicode emoji frequency page, https://home.unicode.org/emoji/emoji-frequency/. Its table
   ranks the emoji of Emoji 5.0 and before by their use in 2019. The page is website content
   under the Unicode Terms of Use, https://www.unicode.org/copyright.html. The script reads the
   order of the emoji from the page, and the table holds no copy of the page.
5. SymSpell's frequency_dictionary_en_82_765.txt (MIT license): the English word list.
6. Shared/lexicon-pinyin.bin: the Chinese words of the typing engine.

Hand-written files, one set for each language (en, zh):
- chosen-<language>.tsv: pairs that win over the generated pairs of the word.
- added-<language>.tsv: the chosen pairs that no source holds.
- denied-<language>.tsv: words, pairs and emoji that the table must not hold.
- accepted-words-<language>.txt: words that the word list of the language lacks.

The script downloads the sources into build/emoji-table/ and checks each file's SHA-256, so a
changed source stops the build.

Usage:
    python scripts/emoji-table/build_emoji_table.py
        Builds and checks the pairs, and writes Shared/emoji-suggestions.tsv.
    python scripts/emoji-table/build_emoji_table.py --candidates en good happy
        Prints every emoji that the sources give for each word, best first.
    python scripts/emoji-table/build_emoji_table.py --review --output build/emoji-table/draft.tsv
        Writes the table to another file, and writes build/emoji-table/review-<language>.tsv:
        each word with the origin of its emoji and the best emoji of the sources.
"""

import argparse
import hashlib
import html
import json
import re
import statistics
import struct
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CACHE = ROOT / "build" / "emoji-table"
OUTPUT = ROOT / "Shared" / "emoji-suggestions.tsv"
PINYIN_LEXICON = ROOT / "Shared" / "lexicon-pinyin.bin"

CLDR_VERSION = "49.0.0"
EMOJI_VERSION = "17.0"
EMOJILIB_VERSION = "4.0.3"
SOURCES = {
    "cldr-en.json":
        f"https://cdn.jsdelivr.net/npm/cldr-annotations-full@{CLDR_VERSION}/annotations/en/annotations.json",
    "cldr-zh.json":
        f"https://cdn.jsdelivr.net/npm/cldr-annotations-full@{CLDR_VERSION}/annotations/zh/annotations.json",
    "emoji-test.txt": f"https://unicode.org/Public/{EMOJI_VERSION}.0/emoji/emoji-test.txt",
    "emojilib-en.json": f"https://cdn.jsdelivr.net/npm/emojilib@{EMOJILIB_VERSION}/dist/emoji-en-US.json",
    "emoji-frequency.html": "https://home.unicode.org/emoji/emoji-frequency/",
    "symspell-en.txt":
        "https://raw.githubusercontent.com/wolfgarbe/SymSpell/master/SymSpell/frequency_dictionary_en_82_765.txt",
}
HASHES_FILE = HERE / "source-hashes.json"
LANGUAGES = ("en", "zh")

MAX_EMOJI_PER_WORD = 2
# An English word must be among this many most frequent words of SymSpell's list. The annotated
# words from place 30,000 to 60,000 are everyday words such as "cupcake", "dumpling" and
# "shrugging". Past 60,000 they are mostly rare names such as "annelid" and "sauropod".
ENGLISH_WORD_LIMIT = 60000
# A very frequent English word has many senses, and a keyword seldom is the sense that the
# person means. A word among this many most frequent words gets a generated emoji only when
# the word names the emoji. A Chinese word of one character follows the same rule.
FREQUENT_WORD_LIMIT = 5000
# A generated English word has this many letters or more. The words of two letters are mostly
# short forms such as "cl" and "ng", so chosen-en.tsv holds the few that are words.
GENERATED_WORD_LETTERS = 3
# A word that the sources give to more emoji than this is too general to mean one emoji.
# Such a word keeps only the emoji that it names.
GENERAL_WORD_LIMIT = 6
# The second emoji of a word that is only a keyword must be among this many most used emoji.
SECOND_EMOJI_PLACE_LIMIT = 300
# An emoji of these groups of emoji-test.txt is a sign or a shape. A keyword of such an emoji is
# seldom a good match, so a generated pair needs a word that names the emoji.
NAMED_ONLY_GROUPS = ("Symbols", "Flags")

# Relevance of an emoji for a word, best first. NAME: the word is the emoji's name. HEAD: the
# word is the head word of the name. AGREED: the word is a keyword in CLDR and in emojilib.
# KEYWORD: the word is a keyword in one source.
NAME, HEAD, AGREED, KEYWORD = 4, 3, 2, 1
RELEVANCE_LABELS = {NAME: "name", HEAD: "head", AGREED: "agreed", KEYWORD: "keyword"}

VARIATION_SELECTOR = "\N{VARIATION SELECTOR-16}"
ZERO_WIDTH_JOINER = 0x200D
KEYCAP = 0x20E3
FEMALE_SIGN, MALE_SIGN, MAN, WOMAN = 0x2640, 0x2642, 0x1F468, 0x1F469
SKIN_TONES = range(0x1F3FB, 0x1F400)
REGIONAL_INDICATORS = range(0x1F1E6, 0x1F200)
TAG_CHARACTERS = range(0xE0020, 0xE0080)
FLAG_SUBGROUPS = ("country-flag", "subdivision-flag")
EMOJI_TEST_LINE = re.compile(r"^([0-9A-F ]+?)\s*;\s*([a-z-]+)\s*# (\S+) E(\d+\.\d+) (.+)$")

# Words of an English emoji name that do not say what the emoji shows.
NAME_GENERIC_WORDS = {
    "face", "person", "people", "hand", "hands", "symbol", "sign", "button", "mark", "arrow", "gesture",
    "man", "woman", "men", "women",
}
NAME_FILLER_WORDS = {"a", "an", "the", "up", "down", "left", "right", "one", "two", "three", "four"}
# A word of this kind ends the main part of an English emoji name: "face with tears of joy".
NAME_LINK_WORDS = {"with", "without", "of", "in", "on", "over", "behind", "at", "and", "for", "under"}
ENGLISH_WORD = re.compile(r"[a-z]{2,}")
VOWELS = "aeiou"
# The plural of a word that ends with one of these takes "es": "boxes", "dishes", "heroes".
ES_PLURAL_ENDINGS = ("s", "x", "z", "ch", "sh", "o")
VERB_ENDINGS = ("ing", "ed")
# The groups of emoji-test.txt whose emoji show a face, a gesture or a person.
VERB_FORM_GROUPS = ("Smileys & Emotion", "People & Body")
# Chinese emoji names that end with one of these say the same thing without it: "狗脸" shows "狗".
CHINESE_NAME_ENDINGS = ("的脸", "笑脸", "脸", "头")


def bare(emoji):
    """The emoji without its variation selectors, the form of the annotation keys."""
    return emoji.replace(VARIATION_SELECTOR, "")


def fetch(name):
    """The bytes of one source file, from the cache or the network, checked against its hash."""
    url = SOURCES[name]
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if not path.exists():
        request = urllib.request.Request(url, headers={"User-Agent": "emoji-table-build"})
        with urllib.request.urlopen(request) as response:
            path.write_bytes(response.read())
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    hashes = json.loads(HASHES_FILE.read_text(encoding="utf-8"))
    if hashes.get(name) != digest:
        sys.exit(f"{name}: SHA-256 {digest} differs from source-hashes.json ({hashes.get(name)}). "
                 f"Check the new file, then write its hash into source-hashes.json.")
    return data


def reason_left_out(points, subgroup):
    """Why the table may not hold an emoji of these code points, or None when it may."""
    if any(point in SKIN_TONES for point in points):
        return "skin tone"
    if KEYCAP in points:
        return "keycap"
    is_flag = any(point in REGIONAL_INDICATORS or point in TAG_CHARACTERS for point in points)
    if is_flag != (subgroup in FLAG_SUBGROUPS):
        sys.exit(f"emoji-test.txt: the code points {points} and the subgroup {subgroup} disagree about a flag")
    if is_flag:
        return "flag"
    if ZERO_WIDTH_JOINER in points and {FEMALE_SIGN, MALE_SIGN, MAN, WOMAN} & set(points):
        return "gender variant"
    return None


def emoji_list():
    """The emoji that the table may hold, in the order of emoji-test.txt.

    Maps the bare form of each emoji to its fully-qualified text, its English name, its group and
    its subgroup. Leaves out the skin tone variants, the gender variants, the keycaps and the
    flags of countries and regions.
    """
    allowed = {}
    newest = 0.0
    group = subgroup = None
    for line in fetch("emoji-test.txt").decode("utf-8").splitlines():
        if line.startswith("# group:"):
            group = line.split(":", 1)[1].strip()
        elif line.startswith("# subgroup:"):
            subgroup = line.split(":", 1)[1].strip()
        elif line and not line.startswith("#"):
            match = EMOJI_TEST_LINE.match(line)
            if match is None:
                sys.exit(f"emoji-test.txt: unexpected line {line!r}")
            codes, status, text, version, name = match.groups()
            newest = max(newest, float(version))
            if status != "fully-qualified":
                continue
            if reason_left_out([int(code, 16) for code in codes.split()], subgroup) is None:
                allowed[bare(text)] = {"text": text, "name": name, "group": group, "subgroup": subgroup}
    if newest != float(EMOJI_VERSION) or len(allowed) < 1400:
        sys.exit(f"emoji-test.txt did not parse: newest version {newest}, {len(allowed)} emoji")
    return allowed


def frequency_places(allowed):
    """The place of each emoji by its use, 0 for the most used.

    The frequency page lists the emoji in table rows, most used first. An emoji that the page
    does not rank takes the median place of the ranked emoji of the table. Such an emoji is
    newer than the page, and the median place puts it among the emoji of average use.
    """
    page = fetch("emoji-frequency.html").decode("utf-8")
    ranking = []
    for row in re.findall(r"<tr.*?</tr>", page, re.S):
        cells = re.findall(r"<td.*?</td>", row, re.S)
        if len(cells) < 2:
            continue
        text = html.unescape(re.sub(r"<[^>]+>", " ", cells[1]))
        ranking += [bare(item.rstrip("…")) for item in text.split() if item != "…"]
    if len(ranking) < 1000 or ranking[0] != "\U0001F602":
        sys.exit(f"The frequency page did not parse: {len(ranking)} emoji, first {ranking[:1]}")
    places = {}
    for index, emoji in enumerate(ranking):
        if emoji in allowed:
            places.setdefault(emoji, index)
    default_place = int(statistics.median(places.values()))
    return {emoji: places.get(emoji, default_place) for emoji in allowed}


def annotations(language, allowed):
    """The CLDR keywords and spoken name of each emoji of the table, by the bare form of the emoji."""
    data = json.loads(fetch(f"cldr-{language}.json").decode("utf-8"))["annotations"]["annotations"]
    notes = {}
    for emoji in allowed:
        if emoji not in data:
            continue
        entry = data[emoji]
        if len(entry["tts"]) != 1:
            sys.exit(f"cldr-{language}.json: {emoji} has {len(entry['tts'])} spoken names")
        notes[emoji] = {"keywords": entry["default"], "name": entry["tts"][0]}
    return notes


def emojilib_words(allowed):
    """The emojilib keywords of each emoji of the table that are one plain English word."""
    data = json.loads(fetch("emojilib-en.json").decode("utf-8"))
    library = {}
    for emoji, keywords in data.items():
        if bare(emoji) in allowed:
            library[bare(emoji)] = {word.lower() for word in keywords if ENGLISH_WORD.fullmatch(word.lower())}
    return library


def english_word_places():
    """The place of each word of SymSpell's list by its count, 0 for the most frequent word."""
    counts = {}
    for line in fetch("symspell-en.txt").decode("utf-8-sig").splitlines():
        word, count = line.split()
        counts[word] = int(count)
    ordered_words = sorted(counts, key=lambda word: (-counts[word], word))
    return {word: place for place, word in enumerate(ordered_words)}


def chinese_vocabulary():
    """The word texts of Shared/lexicon-pinyin.bin, the Chinese lexicon of the typing engine.

    scripts/typing-engine/lexicon_format.py documents the file. The strings section ends the
    file and holds each text as UTF-8 with a zero byte after it.
    """
    data = PINYIN_LEXICON.read_bytes()
    magic, version, _, word_count, string_bytes = struct.unpack("<5I", data[:20])
    if magic != 0x4C4F5544 or version != 3:
        sys.exit(f"{PINYIN_LEXICON.name}: unexpected magic {magic:#x} or version {version}")
    texts = data[-string_bytes:].split(b"\0")
    if texts[-1] != b"" or len(texts) - 1 != word_count:
        sys.exit(f"{PINYIN_LEXICON.name}: the strings section holds {len(texts) - 1} texts for {word_count} words")
    return {text.decode("utf-8") for text in texts[:-1]}


def data_lines(path):
    """The lines of a hand-written file as lists of tab-separated fields, with their line numbers."""
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip() and not line.startswith("#"):
            yield number, line.split("\t")


def read_chosen(language):
    """chosen-<language>.tsv: each word with its one or two emoji, best first."""
    path = HERE / f"chosen-{language}.tsv"
    chosen = {}
    for number, fields in data_lines(path):
        if len(fields) != 2:
            sys.exit(f"{path.name}:{number}: a line holds a word, a tab and its emoji")
        word, emoji = fields[0], fields[1].split(" ")
        if word in chosen:
            sys.exit(f"{path.name}:{number}: {word} is in the file twice")
        if not 1 <= len(emoji) <= MAX_EMOJI_PER_WORD or len(set(emoji)) != len(emoji):
            sys.exit(f"{path.name}:{number}: {word} needs one or two different emoji")
        chosen[word] = emoji
    return chosen


def read_added(language):
    """added-<language>.tsv: the pairs of a word and an emoji that no source holds."""
    path = HERE / f"added-{language}.tsv"
    added = set()
    for number, fields in data_lines(path):
        if len(fields) != 2 or (fields[0], fields[1]) in added:
            sys.exit(f"{path.name}:{number}: a line holds a word, a tab and one emoji, and each pair once")
        added.add((fields[0], fields[1]))
    return added


def read_denied(language, allowed):
    """denied-<language>.tsv: the denied words, the denied pairs and the denied emoji."""
    path = HERE / f"denied-{language}.tsv"
    words, pairs, emoji = set(), set(), set()
    for number, fields in data_lines(path):
        if len(fields) == 1 and bare(fields[0]) in allowed:
            target, item = emoji, bare(fields[0])
        elif len(fields) == 1:
            target, item = words, fields[0]
        elif len(fields) == 2 and bare(fields[1]) in allowed:
            target, item = pairs, (fields[0], bare(fields[1]))
        else:
            sys.exit(f"{path.name}:{number}: a line holds a word, an emoji, or a word, a tab and an emoji")
        if item in target:
            sys.exit(f"{path.name}:{number}: {fields} is in the file twice")
        target.add(item)
    return words, pairs, emoji


def read_accepted_words(language):
    """accepted-words-<language>.txt: words that the word list of the language lacks."""
    path = HERE / f"accepted-words-{language}.txt"
    words = set()
    for number, fields in data_lines(path):
        if len(fields) != 1 or fields[0] in words:
            sys.exit(f"{path.name}:{number}: a line holds one word, and each word once")
        words.add(fields[0])
    return words


def short_stem(stem):
    """True for a stem of one syllable that ends vowel and consonant: "rat" of "rating".

    English writes "rating" for "rate" and "ratting" for "rat", so such a stem stands for the
    word with "e".
    """
    return (sum(letter in VOWELS for letter in stem) == 1 and len(stem) >= 2
            and stem[-1] not in VOWELS + "wxy" and stem[-2] in VOWELS)


def base_forms(word):
    """The words that an inflected English word may come from, most likely first: "dogs" gives "dog"."""
    bases = []
    if word.endswith("s") and not word.endswith("ss"):
        bases.append(word[:-1])
    if word.endswith("es") and word[:-2].endswith(ES_PLURAL_ENDINGS):
        bases.append(word[:-2])
    if word.endswith("ies"):
        bases.append(word[:-3] + "y")
    if word.endswith("ves"):
        bases += [word[:-3] + "f", word[:-3] + "fe"]
    for ending in VERB_ENDINGS:
        if not word.endswith(ending) or len(word) < len(ending) + 2:
            continue
        stem = word[:-len(ending)]
        if ending == "ing" and stem.endswith("y"):
            bases.append(stem[:-1] + "ie")
        if ending == "ed" and stem.endswith("i"):
            bases.append(stem[:-1] + "y")
        if stem[-1] == stem[-2] and stem[-1] not in VOWELS:
            bases += [stem, stem[:-1]]
        elif stem[-1] in VOWELS:
            bases += [stem + "e", stem] if ending == "ed" or stem[-1] == "u" else [stem]
        elif short_stem(stem):
            bases.append(stem + "e")
        else:
            bases += [stem, stem + "e"]
    return [base for base in bases if len(base) >= 3]


def inherits(word, base, base_emoji, word_places, allowed):
    """True when an inflected English word takes the emoji of its base word.

    A form that is more frequent than its base word has a meaning of its own: "building" is
    more than a form of "build". An "-ing" or "-ed" form is a verb form. It takes the emoji
    only when the first emoji of the base shows a face, a gesture or a person, because such
    an emoji stands for a feeling or an action: "laughed" takes the emoji of "laugh", and
    "booked" does not take the emoji of "book".
    """
    if word_places.get(word, ENGLISH_WORD_LIMIT) < word_places.get(base, ENGLISH_WORD_LIMIT):
        return False
    if word.endswith(VERB_ENDINGS):
        return allowed[bare(base_emoji[0])]["group"] in VERB_FORM_GROUPS
    return True


def same_stem(first, second):
    """True for two forms of one English word: "melt" and "melting"."""
    return first == second or first in base_forms(second) or second in base_forms(first)


def english_name_words(name):
    """The words of an English emoji name by relevance: "birthday cake" gives cake HEAD.

    The head word is the last word of the main part of the name that says what the emoji
    shows. A name of one such word gives that word as NAME. Every other word is a KEYWORD.
    """
    plain = re.sub(r"\(.*?\)", " ", name).lower()
    tokens = [token for token in re.split(r"[^a-z’'-]+", plain) if token]
    words = {token: KEYWORD for token in tokens if ENGLISH_WORD.fullmatch(token)}
    # A quoted name is a translation, and a name that starts with "no" shows the opposite.
    if "“" in name or tokens[:1] == ["no"] or plain.startswith("non-"):
        return words
    if len(tokens) == 1 and tokens[0] in words:
        return {tokens[0]: NAME}
    telling = [token for token in tokens
               if token in words and token not in NAME_GENERIC_WORDS | NAME_FILLER_WORDS | NAME_LINK_WORDS]
    main = []
    for token in tokens:
        if token in NAME_LINK_WORDS:
            break
        main.append(token)
    main_telling = [token for token in main if token in telling]
    if len(telling) == 1:
        words[telling[0]] = HEAD
    elif main_telling:
        words[main_telling[-1]] = HEAD
    return words


def english_candidates(notes, library):
    """Each English word with the emoji that the sources give it, as {emoji: relevance}."""
    found = {}
    for emoji, entry in notes.items():
        words = english_name_words(entry["name"])
        heads = [word for word, relevance in words.items() if relevance >= HEAD]
        for keyword in entry["keywords"]:
            keyword = keyword.lower()
            if not ENGLISH_WORD.fullmatch(keyword) or keyword in words:
                continue
            # A keyword that is another form of the head word is as close as the head word.
            words[keyword] = HEAD if any(same_stem(keyword, head) for head in heads) else KEYWORD
        for word in library.get(emoji, ()):
            if words.get(word, AGREED) == KEYWORD:
                words[word] = AGREED
            else:
                words.setdefault(word, KEYWORD)
        for word, relevance in words.items():
            found.setdefault(word, {})[emoji] = relevance
    return found


def chinese_candidates(notes):
    """Each Chinese word with the emoji that the annotations give it, as {emoji: relevance}."""
    names = {entry["name"] for entry in notes.values()}
    found = {}
    for emoji, entry in notes.items():
        name = entry["name"]
        words = {keyword: KEYWORD for keyword in entry["keywords"] if " " not in keyword}
        for word in words:
            if len(word) >= 2 and name.endswith(word):
                words[word] = HEAD
        for ending in CHINESE_NAME_ENDINGS:
            start = name[:-len(ending)]
            # "头" also ends words such as "骨头", so the rest must be an emoji name of its own.
            if name.endswith(ending) and start in words and (ending != "头" or start in names):
                words[start] = HEAD
                break
        words[name] = NAME
        for word, relevance in words.items():
            found.setdefault(word, {})[emoji] = relevance
    return found


def ordered(emoji_relevance, places, order):
    """The emoji of one word, best first.

    An emoji that the word names comes before a keyword emoji, and a keyword of two sources
    before a keyword of one source. Among equals the more used emoji comes first.
    """
    def key(emoji):
        relevance = emoji_relevance[emoji]
        return (-min(relevance, HEAD), places[emoji], -relevance, order[emoji])
    return sorted(emoji_relevance, key=key)


def generated_pairs(candidates, allowed, places, frequent, denied_words, denied_pairs, denied_emoji):
    """The one or two emoji that the rules choose for each word of the candidates."""
    order = {emoji: index for index, emoji in enumerate(allowed)}
    generated = {}
    for word, emoji_relevance in candidates.items():
        if word in denied_words or (word.isascii() and len(word) < GENERATED_WORD_LETTERS):
            continue
        named_only = frequent(word) or len(emoji_relevance) > GENERAL_WORD_LIMIT
        kept = {}
        for emoji, relevance in emoji_relevance.items():
            if emoji in denied_emoji or (word, emoji) in denied_pairs:
                continue
            if relevance < HEAD and (named_only or allowed[emoji]["group"] in NAMED_ONLY_GROUPS):
                continue
            kept[emoji] = relevance
        ranked = ordered(kept, places, order)
        if not ranked:
            continue
        first = ranked[0]
        chosen = [first]
        for second in ranked[1:]:
            if kept[first] >= HEAD and kept[second] >= HEAD:
                chosen.append(second)
            elif kept[first] == kept[second] == AGREED and places[second] < SECOND_EMOJI_PLACE_LIMIT:
                chosen.append(second)
            break
        generated[word] = chosen
    return generated


def build(language, allowed, places, review=None):
    """The table of one language: each word with its one or two fully-qualified emoji."""
    notes = annotations(language, allowed)
    order = {emoji: index for index, emoji in enumerate(allowed)}
    chosen = read_chosen(language)
    added = read_added(language)
    denied_words, denied_pairs, denied_emoji = read_denied(language, allowed)
    accepted = read_accepted_words(language)
    if language == "en":
        candidates = english_candidates(notes, emojilib_words(allowed))
        word_places = english_word_places()
        listed_words = {word for word, place in word_places.items() if place < ENGLISH_WORD_LIMIT}
        listed = f"among the {ENGLISH_WORD_LIMIT} most frequent words of SymSpell's list"
        sources = f"CLDR {CLDR_VERSION} and emojilib {EMOJILIB_VERSION} do"

        def frequent(word):
            return word_places.get(word, FREQUENT_WORD_LIMIT) < FREQUENT_WORD_LIMIT
    else:
        candidates = chinese_candidates(notes)
        listed_words = chinese_vocabulary()
        listed = "a word of Shared/lexicon-pinyin.bin"
        sources = f"CLDR {CLDR_VERSION} does"

        def frequent(word):
            return len(word) == 1
    known = listed_words | accepted

    errors = []
    for word, emoji_list in chosen.items():
        if language == "en" and not ENGLISH_WORD.fullmatch(word):
            errors.append(f"chosen-{language}.tsv: {word!r} is not a lower-case word of two letters or more")
        if word not in known:
            errors.append(f"chosen-{language}.tsv: {word} is not {listed} and not in accepted-words-{language}.txt")
        if word in denied_words:
            errors.append(f"{word} is in chosen-{language}.tsv and in denied-{language}.tsv")
        for emoji in emoji_list:
            if bare(emoji) not in allowed or allowed[bare(emoji)]["text"] != emoji:
                errors.append(f"chosen-{language}.tsv: {word} {emoji}: the table may not hold this emoji, "
                              f"or the emoji is not in its fully-qualified form")
                continue
            # A pair has a source when a source gives the emoji the word or the base of the word.
            forms = [word] + (base_forms(word) if language == "en" else [])
            held = any(bare(emoji) in candidates.get(form, {}) for form in forms)
            if held and (word, emoji) in added:
                errors.append(f"added-{language}.tsv: {word} {emoji}: a source holds the pair, so remove the line")
            if not held and (word, emoji) not in added:
                found = " ".join(allowed[e]["text"] for e in ordered(candidates.get(word, {}), places, order)) or "none"
                errors.append(f"chosen-{language}.tsv: {word} {emoji}: {sources} not give the emoji the word, "
                              f"and added-{language}.tsv does not list the pair. The sources give: {found}")
            if (word, bare(emoji)) in denied_pairs or bare(emoji) in denied_emoji:
                errors.append(f"{word} {emoji} is in chosen-{language}.tsv and in denied-{language}.tsv")
    for word, emoji in sorted(added):
        if emoji not in chosen.get(word, []):
            errors.append(f"added-{language}.tsv: {word} {emoji}: chosen-{language}.tsv does not hold the pair")
    for word, emoji in sorted(denied_pairs):
        if emoji not in candidates.get(word, {}):
            errors.append(f"denied-{language}.tsv: {word} {allowed[emoji]['text']}: no source holds the pair")
    for word in sorted(accepted & listed_words):
        errors.append(f"accepted-words-{language}.txt: {word} is {listed}, so remove the line")
    if errors:
        sys.exit("\n".join(errors))

    generated = generated_pairs(candidates, allowed, places, frequent, denied_words, denied_pairs, denied_emoji)
    table = {}
    origin = {}
    for word, emoji_list in generated.items():
        if word in known:
            table[word] = [allowed[emoji]["text"] for emoji in emoji_list]
            origin[word] = "generated"
    for word, emoji_list in chosen.items():
        table[word] = emoji_list
        origin[word] = "chosen"
    if language == "en":
        # An inflected form that has no emoji of its own takes the emoji of its base word.
        for word in sorted(known - set(table) - denied_words):
            for base in base_forms(word):
                if base in origin and not origin[base].startswith("from "):
                    if inherits(word, base, table[base], word_places, allowed):
                        table[word] = table[base]
                        origin[word] = f"from {base}"
                    break
                # A known word without emoji is the more likely base, so the search stops there.
                if base in listed_words:
                    break
    if review is not None:
        lines = []
        for word in sorted(table):
            relevance = candidates.get(word, {})
            best = " ".join(f"{allowed[emoji]['text']}{RELEVANCE_LABELS[relevance[emoji]][0]}{places[emoji]}"
                            for emoji in ordered(relevance, places, order)[:6])
            lines.append(f"{word}\t{' '.join(table[word])}\t{origin[word]}\t{len(relevance)}\t{best}")
        review.mkdir(parents=True, exist_ok=True)
        (review / f"review-{language}.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return table


def print_candidates(language, words, allowed, places):
    """Prints every emoji that the sources give each word: emoji, relevance and place by use."""
    notes = annotations(language, allowed)
    order = {emoji: index for index, emoji in enumerate(allowed)}
    if language == "en":
        candidates = english_candidates(notes, emojilib_words(allowed))
    else:
        candidates = chinese_candidates(notes)
    for word in words:
        relevance = candidates.get(word, {})
        found = [f"{allowed[emoji]['text']} {RELEVANCE_LABELS[relevance[emoji]]} {places[emoji]}"
                 for emoji in ordered(relevance, places, order)]
        print(f"{word}\t{len(found)} emoji\t{', '.join(found) or 'none'}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", nargs="+", metavar=("LANGUAGE", "WORD"))
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    allowed = emoji_list()
    places = frequency_places(allowed)
    if arguments.candidates:
        language, *words = arguments.candidates
        if language not in LANGUAGES:
            sys.exit(f"The language is one of {LANGUAGES}, not {language}")
        print_candidates(language, words, allowed, places)
        return
    lines = [
        "# Emoji that the keyboard offers for a word. Built by scripts/emoji-table/build_emoji_table.py",
        f"# from the Unicode CLDR {CLDR_VERSION} emoji annotations and the emoji list of Emoji {EMOJI_VERSION}",
        f"# (Unicode License v3), from the keywords of emojilib {EMOJILIB_VERSION} (MIT license), and from the",
        "# hand-written files beside the script. docs/emoji-suggestions.md describes the table.",
        "# Unicode data: Copyright (c) 1991-2026 Unicode, Inc. License: https://www.unicode.org/license.txt",
        "# emojilib: Copyright (c) 2014 Mu-An Chiou. License: https://github.com/muan/emojilib/blob/main/LICENSE",
        "# Columns: language, word, emoji separated by one space.",
    ]
    for language in LANGUAGES:
        table = build(language, allowed, places, CACHE if arguments.review else None)
        for word in sorted(table):
            lines.append(f"{language}\t{word}\t{' '.join(table[word])}")
        print(f"{language}: {len(table)} words, {len({e for emoji in table.values() for e in emoji})} different emoji")
    arguments.output.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {arguments.output}")


if __name__ == "__main__":
    main()
