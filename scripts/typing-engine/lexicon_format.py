"""Writes a lexicon file that Engine/duo_engine.c reads.

A lexicon holds words, a letter tree over their spellings, and optional word-pair statistics.
- A word has a spelling (the letters a person types for it), a text (what the keyboard outputs),
  and a log probability. English: spelling and text are the same word. Pinyin: the spelling is
  "nihao" and the text is the Chinese word.
- The letter tree lets the engine walk all spellings letter by letter.
- A word pair holds the log of the chance that the second word follows the first.

File layout, all numbers little-endian:
    header    8 x uint32: magic "DUOL", version 1, node count, word count, string bytes,
              pair count, 0, 0
    nodes     node count x 12 bytes: first child (uint32), first word (uint32),
              child count (uint8), letter (uint8), word count (uint16)
    words     word count x 8 bytes: offset of the text in the strings (uint32),
              log probability (float32)
    pair index  (word count + 1) x uint32: for each first word, where its pairs start
    pairs     pair count x 8 bytes: second word (uint32), log probability (float32),
              sorted by second word inside each first word
    strings   the texts as UTF-8, each ended by a zero byte

Node 0 is the root. The children of a node sit side by side, sorted by letter. The words of a
node sit side by side in the word table, most probable first, so a word's number says which node
it belongs to.
"""
import struct
from pathlib import Path

MAGIC = 0x4C4F5544
VERSION = 1


def write_lexicon(path: Path, words: list[tuple[str, str, float]], pairs: dict[tuple[str, str], float]) -> dict:
    """Writes the file.

    `words` holds (spelling, text, log probability). `pairs` maps (first text, second text) to
    the log of the chance that the second follows the first. A text that has several spellings
    gets the pair for each of them.
    """
    # Build the letter tree as nested dictionaries first.
    root = {"children": {}, "words": []}
    for spelling, text, log_probability in words:
        if not spelling:
            raise ValueError(f"empty spelling for {text!r}")
        node = root
        for letter in spelling.encode("ascii"):
            node = node["children"].setdefault(letter, {"children": {}, "words": []})
        node["words"].append((text, log_probability))

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
        for text, log_probability in node["words"]:
            word_ids.setdefault(text, []).append(len(word_records))
            word_records.append((len(strings), log_probability))
            strings += text.encode("utf-8") + b"\0"

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
        output.write(struct.pack("<8I", MAGIC, VERSION, len(ordered), len(word_records), len(strings), len(pair_records), 0, 0))
        for node in ordered:
            if len(node["children"]) > 0xFF:
                raise ValueError("a node has more than 255 children")
            output.write(struct.pack("<IIBBH", node["first_child"], node["first_word"], len(node["children"]), node["letter"], len(node["words"])))
        for offset, log_probability in word_records:
            output.write(struct.pack("<If", offset, log_probability))
        output.write(struct.pack(f"<{len(pair_index)}I", *pair_index))
        for second_id, log_probability in pair_records:
            output.write(struct.pack("<If", second_id, log_probability))
        output.write(strings)
    return {"nodes": len(ordered), "words": len(word_records), "pairs": len(pair_records), "bytes": path.stat().st_size}
