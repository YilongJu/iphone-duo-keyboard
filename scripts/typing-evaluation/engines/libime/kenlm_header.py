"""Prints the n-gram order and the n-gram counts stored in the header of a KenLM binary language model.

Usage:
    python3 scripts/typing-evaluation/engines/libime/kenlm_header.py /usr/lib/x86_64-linux-gnu/libime/zh_CN.lm

libime stores its language model as a KenLM binary file. The layout below follows KenLM's
lm/binary_format.cc for a 64-bit little-endian build: a Sanity block of 88 bytes that starts with
the text "mmap lm http://kheafield.com/code format version 5", then the fixed parameters
(order, probing multiplier, model type, has-vocabulary flag, search version) in 20 bytes, then one
64-bit count per n-gram order. The script stops when the text or the reference values differ.
"""
import struct
import sys
from pathlib import Path

MAGIC = b"mmap lm http://kheafield.com/code format version 5\n\x00"
SANITY_BYTES = 88
MODEL_TYPES = {0: "PROBING", 1: "REST_PROBING", 2: "TRIE", 3: "QUANT_TRIE", 4: "ARRAY_TRIE", 5: "QUANT_ARRAY_TRIE"}


def read_header(path: Path) -> dict:
    with path.open("rb") as handle:
        head = handle.read(SANITY_BYTES + 20 + 8 * 16)
    if not head.startswith(MAGIC):
        raise ValueError(f"{path} does not start with the KenLM version 5 text; first bytes: {head[:60]!r}")
    # Sanity block after the 56-byte text field: three floats, two word indexes, one 64-bit integer.
    zero, one, minus_half, one_word, max_word, one_uint64 = struct.unpack_from("<fffIIxxxxQ", head, 56)
    if (zero, one, minus_half, one_word, max_word, one_uint64) != (0.0, 1.0, -0.5, 1, 0xFFFFFFFF, 1):
        raise ValueError(f"{path}: the reference values in the Sanity block differ: "
                         f"{(zero, one, minus_half, one_word, max_word, one_uint64)}")
    order, probing_multiplier, model_type, has_vocabulary, search_version = struct.unpack_from("<BxxxfiBxxxI", head, SANITY_BYTES)
    if not 1 <= order <= 16:
        raise ValueError(f"{path}: order {order} is outside 1 to 16")
    if model_type not in MODEL_TYPES:
        raise ValueError(f"{path}: unknown model type {model_type}")
    counts = list(struct.unpack_from(f"<{order}Q", head, SANITY_BYTES + 20))
    return {"file": str(path), "bytes": path.stat().st_size, "order": order, "counts": counts,
            "model_type": MODEL_TYPES[model_type], "probing_multiplier": probing_multiplier,
            "has_vocabulary": bool(has_vocabulary), "search_version": search_version}


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: kenlm_header.py LANGUAGE_MODEL")
    header = read_header(Path(sys.argv[1]))
    print(f"{header['file']}: {header['bytes']} bytes, KenLM binary format version 5")
    print(f"  n-gram order: {header['order']}")
    for n, count in enumerate(header["counts"], 1):
        print(f"  {n}-grams: {count}")
    print(f"  model type: {header['model_type']}, search version {header['search_version']}, "
          f"vocabulary stored in the file: {header['has_vocabulary']}")


if __name__ == "__main__":
    main()
