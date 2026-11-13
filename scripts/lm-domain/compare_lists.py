"""Counts the lists that differ between two builds of one list file, as after a change of the pack.

Two lists of the same case and typed span differ when their readings, their engine scores or
their target differ. The script prints the lists of each file, the lists that only one file
holds, and the lists that differ.

Usage: python3 scripts/lm-domain/compare_lists.py OLD.jsonl.gz NEW.jsonl.gz
"""
import gzip
import json
import sys


def read(path: str) -> dict:
    lists = {}
    with gzip.open(path, "rt", encoding="utf-8") as file:
        for line in file:
            item = json.loads(line)
            lists[(item["case"], item["context"], item["typed"])] = (item["readings"], item["target"])
    return lists


old, new = read(sys.argv[1]), read(sys.argv[2])
shared = set(old) & set(new)
other_readings = sum(1 for key in shared if [r[0] for r in old[key][0]] != [r[0] for r in new[key][0]])
other_target = sum(1 for key in shared if old[key][0][old[key][1]][0] != new[key][0][new[key][1]][0])
print(json.dumps({"old": len(old), "new": len(new), "only_old": len(set(old) - set(new)), "only_new": len(set(new) - set(old)),
                  "differ": sum(1 for key in shared if old[key] != new[key]), "other_reading_texts": other_readings,
                  "other_target_text": other_target}))
