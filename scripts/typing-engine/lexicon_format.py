"""Writes a lexicon file that Engine/duo_engine.c reads.

A lexicon holds words, a letter tree over their spellings, and optional word-pair and
word-triple statistics.
- A word has a spelling (the letters a person types for it), a text (what the keyboard outputs),
  a log probability and a back-off weight. English: spelling and text are the same word.
  Pinyin: the spelling is "nihao" and the text is the Chinese word.
- The letter tree lets the engine walk all spellings letter by letter.
- A word pair holds the log of the chance that the second word follows the first.
- A word triple holds the log of the chance that the third word follows the first two.

The file names one of two ways to combine a word's own probability with the statistics:
- Model 0, mixed: the chance of a word after another is a fixed blend of the pair statistic and
  the word's own probability. The back-off weights are 0.
- Model 1, back-off: a listed triple gives the chance of its third word directly. Without a
  listed triple, the chance is the back-off weight of the two words before as a pair, plus the
  chance after the one word before. That chance is a listed pair's value, or the back-off weight
  of the word before plus the word's own log probability. This is the form of an ARPA language
  model.

There are two versions of the file. write_lexicon writes version 2, which holds words and
pairs. write_lexicon_with_triples writes version 3.

Version 2, all numbers little-endian:
    header    8 x uint32: magic "DUOL", version 2, node count, word count, string bytes,
              pair count, model, 0
    nodes     node count x 12 bytes: first child (uint32), first word (uint32),
              child count (uint8), letter (uint8), word count (uint16)
    words     word count x 12 bytes: offset of the text in the strings (uint32),
              log probability (float32), back-off weight (float32)
    pair index  (word count + 1) x uint32: for each first word, where its pairs start
    pairs     pair count x 8 bytes: second word (uint32), log probability (float32),
              sorted by second word inside each first word
    strings   the texts as UTF-8, each ended by a zero byte

Version 3 has the same nodes, pair index and strings, and these parts:
    header    10 x uint32: magic "DUOL", version 3, node count, word count, string bytes,
              pair count, model, context count, triple count, 0
    words     word count x 16 bytes: offset of the text (uint32), log probability (float32),
              back-off weight (float32), reading cost (float32)
    pairs     pair count x 8 bytes: second word (uint32, with bit 31 set when the pair opens
              triples), log probability (uint16: the negated value in steps of 1/2048),
              back-off weight (int16: the value in steps of 1/2048)
    contexts  (context count + 1) x 8 bytes, after the pairs: the position of a pair that opens
              triples (uint32) and the position of its first triple (uint32), sorted by pair.
              The last row closes the table with the pair count and the triple count.
    triples   triple count x 4 bytes, after the contexts: one uint32 with the third word in
              the low 20 bits and the log probability in the high 12 bits (the negated value in
              steps of 1/256), sorted by third word inside each pair

A word's reading cost is the log of the share of its spelling among the spellings of its text.
The word's log probability already holds the cost. The engine adds the cost to the value of a
listed pair or triple, which is a statistic of the text and not of one spelling.

The steps keep a pair at 8 bytes and a triple at 4 bytes. The largest rounding error is 0.00025
for a pair and 0.002 for a triple, in natural-log units. The writer stops on a value outside
the range of its field.

Node 0 is the root. The children of a node sit side by side, sorted by letter. The words of a
node sit side by side in the word table, most probable first, so a word's number says which node
it belongs to.
"""
import struct
from pathlib import Path

MAGIC = 0x4C4F5544
VERSION = 2
VERSION_WITH_TRIPLES = 3
MODEL_MIXED = 0
MODEL_BACK_OFF = 1
PAIR_STEPS = 2048
TRIPLE_STEPS = 256
TRIPLE_WORD_BITS = 20
PAIR_OPENS_TRIPLES = 0x80000000


def _lay_out(words):
    """Builds the letter tree and numbers the nodes and the words.

    `words` holds (spelling, text, log probability, more values). Returns the nodes in file
    order, the word records as (offset of the text, log probability, more values), the word
    numbers of each text, and the strings.
    """
    # Build the letter tree as nested dictionaries first.
    root = {"children": {}, "words": []}
    for spelling, text, *values in words:
        if not spelling:
            raise ValueError(f"empty spelling for {text!r}")
        node = root
        for letter in spelling.encode("ascii"):
            node = node["children"].setdefault(letter, {"children": {}, "words": []})
        node["words"].append((text, *values))

    # Number the nodes level by level, so the children of one node are neighbors.
    ordered = [root]
    root["letter"] = 0
    index = 0
    while index < len(ordered):
        node = ordered[index]
        node["first_child"] = len(ordered)
        for letter in sorted(node["children"]):
            child = node["children"][letter]
            child["letter"] = letter
            ordered.append(child)
        index += 1

    strings = bytearray()
    word_records = []
    word_ids: dict[str, list[int]] = {}
    for node in ordered:
        node["first_word"] = len(word_records)
        node["words"].sort(key=lambda item: -item[1])
        if len(node["words"]) > 0xFFFF:
            raise ValueError("a spelling has more than 65535 words")
        for text, *values in node["words"]:
            word_ids.setdefault(text, []).append(len(word_records))
            word_records.append((len(strings), *values))
            strings += text.encode("utf-8") + b"\0"
    return ordered, word_records, word_ids, strings


def _write_nodes(output, ordered):
    for node in ordered:
        if len(node["children"]) > 0xFF:
            raise ValueError("a node has more than 255 children")
        output.write(struct.pack("<IIBBH", node["first_child"], node["first_word"], len(node["children"]), node["letter"], len(node["words"])))


def write_lexicon(
    path: Path, words: list[tuple[str, str, float, float]], pairs: dict[tuple[str, str], float], model: int
) -> dict:
    """Writes a file of version 2.

    `words` holds (spelling, text, log probability, back-off weight). `pairs` maps
    (first text, second text) to the log of the chance that the second follows the first.
    A text that has several spellings gets the pair for each of them.
    """
    ordered, word_records, word_ids, strings = _lay_out(words)

    followers: dict[int, list[tuple[int, float]]] = {}
    for (first, second), log_probability in pairs.items():
        for first_id in word_ids.get(first, []):
            for second_id in word_ids.get(second, []):
                followers.setdefault(first_id, []).append((second_id, log_probability))
    pair_index = [0]
    pair_records = []
    for word_id in range(len(word_records)):
        pair_records.extend(sorted(followers.get(word_id, [])))
        pair_index.append(len(pair_records))

    with open(path, "wb") as output:
        output.write(struct.pack("<8I", MAGIC, VERSION, len(ordered), len(word_records), len(strings), len(pair_records), model, 0))
        _write_nodes(output, ordered)
        for offset, log_probability, back_off in word_records:
            output.write(struct.pack("<Iff", offset, log_probability, back_off))
        output.write(struct.pack(f"<{len(pair_index)}I", *pair_index))
        for second_id, log_probability in pair_records:
            output.write(struct.pack("<If", second_id, log_probability))
        output.write(strings)
    return {"nodes": len(ordered), "words": len(word_records), "pairs": len(pair_records), "bytes": path.stat().st_size}


def _steps(value: float, steps: int, low: int, high: int, name: str) -> int:
    """The value in steps of 1/steps. Stops on a value that its field cannot hold."""
    number = round(value * steps)
    if not low <= number <= high:
        raise ValueError(f"{name} {value} is outside the range of its field, {low / steps} to {high / steps}")
    return number


def write_lexicon_with_triples(
    path: Path,
    words: list[tuple[str, str, float, float, float]],
    pairs: dict[tuple[str, str], tuple[float, float]],
    triples: dict[tuple[str, str, str], float],
    model: int,
) -> dict:
    """Writes a file of version 3.

    `words` holds (spelling, text, log probability, back-off weight, reading cost). `pairs` maps
    (first text, second text) to the log of the chance that the second follows the first and
    the pair's back-off weight. `triples` maps (first text, second text, third text) to the log
    of the chance that the third follows the first two. The first two words of a triple must be
    a pair in `pairs`. A text that has several spellings gets each pair and triple for each of
    them.
    """
    ordered, word_records, word_ids, strings = _lay_out(words)
    if triples and len(word_records) > 1 << TRIPLE_WORD_BITS:
        raise ValueError(f"a triple holds its third word in {TRIPLE_WORD_BITS} bits, and the lexicon has {len(word_records)} words")
    if len(word_records) >= PAIR_OPENS_TRIPLES:
        raise ValueError("too many words for the pair table")

    followers: dict[int, list[tuple[int, int, int]]] = {}
    for (first, second), (log_probability, back_off) in pairs.items():
        value = _steps(-log_probability, PAIR_STEPS, 0, 0xFFFF, "the negated log probability of a pair")
        weight = _steps(back_off, PAIR_STEPS, -0x8000, 0x7FFF, "the back-off weight of a pair")
        for first_id in word_ids.get(first, []):
            for second_id in word_ids.get(second, []):
                followers.setdefault(first_id, []).append((second_id, value, weight))
    pair_index = [0]
    pair_records = []
    pair_position: dict[int, int] = {}
    word_count = len(word_records)
    for word_id in range(word_count):
        for record in sorted(followers.get(word_id, [])):
            pair_position[word_id * word_count + record[0]] = len(pair_records)
            pair_records.append(record)
        pair_index.append(len(pair_records))
    del followers

    thirds: dict[int, list[int]] = {}
    for (first, second, third), log_probability in triples.items():
        if (first, second) not in pairs:
            raise ValueError(f"the triple {first} {second} {third} has no pair {first} {second}")
        value = _steps(-log_probability, TRIPLE_STEPS, 0, 0xFFF, "the negated log probability of a triple")
        for first_id in word_ids.get(first, []):
            for second_id in word_ids.get(second, []):
                position = pair_position[first_id * word_count + second_id]
                for third_id in word_ids.get(third, []):
                    thirds.setdefault(position, []).append(value << TRIPLE_WORD_BITS | third_id)
    del pair_position
    context_records = []
    triple_records = []
    for position in sorted(thirds):
        context_records.append((position, len(triple_records)))
        # The third word sits in the low bits, so this sorts the triples of a pair by third word.
        triple_records.extend(sorted(thirds[position], key=lambda packed: packed & ((1 << TRIPLE_WORD_BITS) - 1)))
    context_count = len(context_records)
    context_records.append((len(pair_records), len(triple_records)))

    with open(path, "wb") as output:
        output.write(struct.pack(
            "<10I", MAGIC, VERSION_WITH_TRIPLES, len(ordered), word_count, len(strings), len(pair_records), model,
            context_count, len(triple_records), 0))
        _write_nodes(output, ordered)
        for offset, log_probability, back_off, reading_cost in word_records:
            output.write(struct.pack("<Ifff", offset, log_probability, back_off, reading_cost))
        output.write(struct.pack(f"<{len(pair_index)}I", *pair_index))
        for position, (second_id, value, weight) in enumerate(pair_records):
            output.write(struct.pack("<IHh", second_id | (PAIR_OPENS_TRIPLES if position in thirds else 0), value, weight))
        for position, first_triple in context_records:
            output.write(struct.pack("<II", position, first_triple))
        output.write(struct.pack(f"<{len(triple_records)}I", *triple_records))
        output.write(strings)
    return {
        "nodes": len(ordered), "words": word_count, "pairs": len(pair_records), "contexts": context_count,
        "triples": len(triple_records), "bytes": path.stat().st_size,
    }
