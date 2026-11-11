"""Picks the domain share of the vocabulary pack from the dev results of domain_pack.py, by the
rule of docs/domain-pack-design.md, and prints the comparison as Markdown.

Each result holds the same words at the frequencies of one share. The rule reads the
configuration that ships: the model with the pack on, against the model with the pack off.

1. Gate: no case of the clean controls (GATES) turns from right to wrong with the pack.
2. Gate: the everyday stream changes at most as many words as with the pack off.
3. Among the shares that pass both gates, the most right new dev cases win, over every group.
   Each case counts the same.
4. A tie goes to the smaller share.
When no share passes the gates, the script says so and names the share with the fewest lost
control cases. That share is then a choice for a person and not a result of the rule.

Usage:
    python3 scripts/lm-rerank/domain_pack_shares.py 0.03=DIR/result.dev.json 0.1=... 0.3=... 1.0=...
"""
import json
import sys
from pathlib import Path

GATES = ["neighbour_clean", "required_control", "domain_clean_hyphenated", "phrase_clean",
         "capital_control_everyday_start", "capital_control_everyday_deliberate", "capital_control_everyday_lower",
         "capital_control_ordinary_word", "capital_control_collision_lower"]


def main():
    results = {}
    for argument in sys.argv[1:]:
        share, path = argument.split("=", 1)
        results[float(share)] = json.loads(Path(path).read_text(encoding="utf-8"))
    if any(result["half"] != "dev" for result in results.values()):
        raise SystemExit("the rule reads dev results only")
    rows = []
    for share in sorted(results):
        result = results[share]
        row = {"share": share}
        for chooser in ("engine", "model"):
            on = result["configurations"][f"{chooser}, pack on"]
            off = result["configurations"][f"{chooser}, pack off"]
            lost = [case for case in result["pack_effect"][chooser]["domain"]["lost"] if case["category"] in GATES]
            row[chooser] = {
                "right": on["domain"]["right"], "cases": on["domain"]["cases"], "right_off": off["domain"]["right"],
                "groups": on["domain"]["groups"], "lost_controls": lost,
                "everyday_changed": on["stream"]["everyday"]["changed_words"],
                "everyday_changed_off": off["stream"]["everyday"]["changed_words"],
                "technical_per_1000": on["stream"]["technical"]["changed_words_per_1000"],
                "technical_per_1000_off": off["stream"]["technical"]["changed_words_per_1000"],
            }
        model = row["model"]
        row["passes"] = not model["lost_controls"] and model["everyday_changed"] <= model["everyday_changed_off"]
        rows.append(row)

    passing = [row for row in rows if row["passes"]]
    if passing:
        chosen = max(passing, key=lambda row: (row["model"]["right"], -row["share"]))
        verdict = f"The rule picks the share {chosen['share']:g}."
    else:
        chosen = min(rows, key=lambda row: (len(row["model"]["lost_controls"]), -row["model"]["right"], row["share"]))
        verdict = (f"No share passes both gates. The share {chosen['share']:g} loses the fewest control cases, "
                   f"{len(chosen['model']['lost_controls'])}.")

    groups = list(rows[0]["model"]["groups"])
    print("Table 1. Shares of domain text with the model: right new dev cases per group with the pack on, the gates, "
          "and the changed words of the streams.")
    print()
    print("| Share | " + " | ".join(groups) + " | all | all, pack off | lost control cases | everyday stream, changed words "
          "(pack off) | technical stream per 1,000 (pack off) | passes the gates |")
    print("| --- |" + " --- |" * (len(groups) + 6))
    for row in rows:
        model = row["model"]
        print(f"| {row['share']:g} | " + " | ".join(f"{model['groups'][g][0]}/{model['groups'][g][1]}" for g in groups)
              + f" | {model['right']}/{model['cases']} | {model['right_off']}/{model['cases']} | {len(model['lost_controls'])} "
              f"| {model['everyday_changed']} ({model['everyday_changed_off']}) "
              f"| {model['technical_per_1000']} ({model['technical_per_1000_off']}) | {'yes' if row['passes'] else 'no'} |")
    print()
    print("Table 2. The same shares with the engine alone, as the keyboard types before its model is ready.")
    print()
    print("| Share | " + " | ".join(groups) + " | all | lost control cases | everyday stream, changed words (pack off) |")
    print("| --- |" + " --- |" * (len(groups) + 3))
    for row in rows:
        engine = row["engine"]
        print(f"| {row['share']:g} | " + " | ".join(f"{engine['groups'][g][0]}/{engine['groups'][g][1]}" for g in groups)
              + f" | {engine['right']}/{engine['cases']} | {len(engine['lost_controls'])} "
              f"| {engine['everyday_changed']} ({engine['everyday_changed_off']}) |")
    print()
    print(verdict)
    print()
    for row in rows:
        for chooser in ("model", "engine"):
            for case in row[chooser]["lost_controls"]:
                print(f"Share {row['share']:g}, {chooser}, lost control case {case['id']} (`{case['category']}`): typed "
                      f"\"{case['typed']}\", pack off \"{case['pack_off']}\", pack on \"{case['pack_on']}\".")


if __name__ == "__main__":
    main()
