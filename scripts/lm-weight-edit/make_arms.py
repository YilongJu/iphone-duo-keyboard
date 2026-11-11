"""Writes the arm files of docs/lm-weight-edit-design.md (Tables 2 and 3).

Usage: python scripts/lm-weight-edit/make_arms.py --out build/lm-weight-edit/arms [--with-seed2]
"""
import argparse
import json
from pathlib import Path

LAMS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]


# The alpha grid of Perin et al. 2026 (0.01 to 0.05), then two larger values as an extension.
TFTV_ALPHAS = [0.01, 0.02, 0.03, 0.04, 0.05, 0.1, 0.2]


def tftv(prefix: str, intervals: list[tuple[int, int]]) -> list[dict]:
    return [{"name": f"{prefix}-tftv-b{first}-{last}-a{alpha}", "kind": "tftv", "blocks": [first, last], "alpha": alpha}
            for first, last in intervals for alpha in TFTV_ALPHAS]


def smollm2() -> list[dict]:
    lora = ["smollm2-lora-seed1"]
    arms = [{"name": "s-stock", "kind": "stock"}]
    arms += [{"name": f"s-tv-{lam}", "kind": "tv", "tuned": lora, "lam": lam} for lam in LAMS]
    arms += [{"name": f"s-dare-p{p}-lam{lam}", "kind": "dare", "tuned": lora, "drop": p, "lam": lam, "seed": 1}
             for p in (0.5, 0.9, 0.99) for lam in (1.0, 1.5)]
    arms += [{"name": f"s-random-{lam}", "kind": "random", "tuned": lora, "lam": lam, "seed": 1} for lam in (0.5, 1.0, 2.0)]
    arms += [{"name": f"s-instruct-{lam}", "kind": "external", "tuned": ["smollm2-135m-instruct"], "lam": lam}
             for lam in (-1.0, -0.5, 0.5, 1.0)]
    arms += [{"name": f"s-steer-L{layer}-a{alpha}", "kind": "steer", "layer": layer, "alpha": alpha}
             for layer in (4, 8, 15, 22) for alpha in (-2.0, -1.0, 1.0, 2.0, 4.0, 8.0)]
    arms += tftv("s", [(8, 16), (12, 22), (16, 24)])
    return arms


def distilgpt2(with_seed2: bool) -> list[dict]:
    lora, full = "distilgpt2-lora-seed1", "distilgpt2-full-seed1"
    group = [lora, full] + (["distilgpt2-lora-seed2"] if with_seed2 else [])
    tag = "3" if with_seed2 else "2"
    arms = [{"name": "d-stock", "kind": "stock"}]
    arms += [{"name": f"d-tv-lora-{lam}", "kind": "tv", "tuned": [lora], "lam": lam} for lam in LAMS]
    arms += [{"name": f"d-tv-full-{lam}", "kind": "tv", "tuned": [full], "lam": lam} for lam in LAMS]
    arms += [{"name": f"d-soup{tag}", "kind": "soup", "tuned": group}]
    arms += [{"name": f"d-ta{tag}-{lam}", "kind": "ta", "tuned": group, "lam": lam} for lam in (0.3, 0.5, 0.7, 1.0)]
    arms += [{"name": f"d-ties{tag}-{lam}", "kind": "ties", "tuned": group, "keep": 0.2, "lam": lam} for lam in (0.5, 1.0, 1.5, 2.0)]
    arms += [{"name": f"d-dare{tag}-{lam}", "kind": "dare", "tuned": group, "drop": 0.9, "lam": lam, "seed": 1} for lam in (0.5, 1.0)]
    arms += [{"name": f"d-random-{lam}", "kind": "random", "tuned": [lora], "lam": lam, "seed": 1} for lam in (0.5, 1.0, 2.0)]
    arms += [{"name": f"d-steer-L{layer}-a{alpha}", "kind": "steer", "layer": layer, "alpha": alpha}
             for layer in (2, 3, 4) for alpha in (-2.0, -1.0, 1.0, 2.0, 4.0, 8.0)]
    arms += tftv("d", [(1, 3), (2, 4), (3, 5)])
    return arms


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--with-seed2", action="store_true")
    arguments = parser.parse_args()
    arguments.out.mkdir(parents=True, exist_ok=True)
    (arguments.out / "smollm2.json").write_text(json.dumps(smollm2(), indent=1), encoding="utf-8")
    (arguments.out / "distilgpt2.json").write_text(json.dumps(distilgpt2(arguments.with_seed2), indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
