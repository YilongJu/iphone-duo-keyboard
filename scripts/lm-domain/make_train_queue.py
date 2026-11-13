"""Writes scripts/lm-domain/train-queue.json: the arms of docs/lm-domain-design.md, in their order.

The first ten arms are fixed. --third-wave SHARE [LOSS] adds the arms that the share rule and
the loss rule of the design name after the first ten arms are scored: seeds 2 and 3 of the
picked share, and the picked share with the picked loss ("ce-c4" or "ec-c4"). summarize3.py
applies the two rules and prints the share and the loss to pass here.

Usage, from the repository root:
    python scripts/lm-domain/make_train_queue.py
    python scripts/lm-domain/make_train_queue.py --third-wave 0.4 ec-c4
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVERYDAY = "build/lm-domain/data/everyday/"
PACK_ON = "build/lm-domain/data/everyday-pack-on/"
DOMAIN = "build/lm-domain/data/domain/"
STEPS = 11000
MEMORY_GB = 3.2
SHARES = {"0.15": "s15", "0.4": "s40", "1.0": "s100"}


def cross_entropy(clean_weight: int) -> list[str]:
    return ["--loss", "cross-entropy", "--clean-weight", str(clean_weight)]


def expected_cost(clean_cost: int) -> list[str]:
    return ["--loss", "expected-cost", "--clean-cost", str(clean_cost), "--cross-entropy-share", "0.1"]


LOSSES = {"ce-c1": cross_entropy(1), "ce-c4": cross_entropy(4), "ec-c4": expected_cost(4)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--third-wave", nargs="+", metavar=("SHARE", "LOSS"))
    arguments = parser.parse_args()
    stops = ["--stop-lists", "round1=" + EVERYDAY + "lists.stop.jsonl.gz", "round2=" + EVERYDAY + "lists2.stop.jsonl.gz",
             "domain=" + DOMAIN + "lists.stop.jsonl.gz"]
    common = ["--steps", str(STEPS), "--evaluate-every", "1000", "--stop-sample", "2000", "--micro-tokens", "1500", *stops]
    mix = ["--train-lists", EVERYDAY + "lists.train.jsonl.gz", EVERYDAY + "lists2.train.jsonl.gz"]
    needs_stop = [DOMAIN + "lists.stop.jsonl.gz"]
    needs_domain = [DOMAIN + "lists.stop.jsonl.gz", DOMAIN + "lists.train.jsonl.gz", PACK_ON + "lists.train.jsonl.gz"]

    def bridge_arm(seed: int) -> dict:
        """The lists of round 2 as they are, with the recipe of this round."""
        return {"name": f"ce-c1-seed{seed}", "memory_gb": MEMORY_GB, "needs": needs_stop,
                "arguments": ["--seed", str(seed), *LOSSES["ce-c1"], *mix]}

    def domain_arm(name: str, share: float, seed: int, loss: str = "ce-c1") -> dict:
        values = ["--seed", str(seed), *LOSSES[loss], "--train-lists", PACK_ON + "lists.train.jsonl.gz"]
        if share > 0:
            values += ["--sampled-train-lists", DOMAIN + "lists.train.jsonl.gz", "--sample-share", str(share)]
        return {"name": name, "memory_gb": MEMORY_GB, "needs": needs_domain, "arguments": values}

    # The bridge arm needs no new list, so it starts first. Every other arm trains on the
    # everyday lists that build_lists3.py builds with the work area on.
    arms = [bridge_arm(1),
            domain_arm("dom-s0-seed1", 0.0, 1), domain_arm("dom-s40-seed1", 0.4, 1), domain_arm("dom-s100-seed1", 1.0, 1),
            domain_arm("dom-s15-seed1", 0.15, 1), domain_arm("ce-c4-seed1", 0.0, 1, "ce-c4"), domain_arm("ec-c4-seed1", 0.0, 1, "ec-c4"),
            domain_arm("dom-s0-seed2", 0.0, 2), domain_arm("ce-c4-seed2", 0.0, 2, "ce-c4"), domain_arm("ec-c4-seed2", 0.0, 2, "ec-c4")]
    if arguments.third_wave:
        share = arguments.third_wave[0]
        if share not in SHARES:
            raise SystemExit(f"the share must be one of {sorted(SHARES)}")
        label = SHARES[share]
        arms += [domain_arm(f"dom-{label}-seed2", float(share), 2), domain_arm(f"dom-{label}-seed3", float(share), 3)]
        if len(arguments.third_wave) == 2:
            loss = arguments.third_wave[1]
            if loss not in ("ce-c4", "ec-c4"):
                raise SystemExit("the loss must be ce-c4 or ec-c4")
            arms.append(domain_arm(f"dom-{label}-{loss}-seed1", float(share), 1, loss))
        elif len(arguments.third_wave) > 2:
            raise SystemExit("--third-wave takes a share and at most one loss")
    note = ("The training runs of the domain round, in the order of docs/lm-domain-design.md. Up to four arms train at the "
            "same time, and every arm takes 11,000 steps. make_train_queue.py writes this file.")
    path = ROOT / "scripts" / "lm-domain" / "train-queue.json"
    path.write_text(json.dumps({"note": note, "common": common, "arms": arms}, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(ROOT)}: {[arm['name'] for arm in arms]}")


if __name__ == "__main__":
    main()
