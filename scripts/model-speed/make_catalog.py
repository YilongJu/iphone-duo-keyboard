"""Writes the files of the bundle that the speed test reads, from the desktop runs.

Usage: python3 make_catalog.py WORK_DIR [COREML_DIR]
  WORK_DIR    $HOME/modelspeed of the desktop jobs: gguf/, tokens/ and out/
  COREML_DIR  the artifacts of the coreml job of .github/workflows/model-speed.yml, with one
              MODEL.manifest.json per model. Without it the catalog holds the llama.cpp pairs only.

Writes, from the repository root:
  Shared/model-speed-catalog.json         the models to download and the pairs (ModelSpeedCatalog)
  Shared/model-speed-reference.json       per model, the top candidate of each request from
                                          llama.cpp b12017 on the Q8_0 file; for "shipped", from
                                          llama.cpp b4846 on the keyboard's own file
  Shared/model-speed-tokens.MODEL.tsv     the tokens of the requests, for Core ML
  scripts/model-speed/reference/MODEL.Q8_0.answers  the answers behind the reference
  scripts/model-speed/gguf-sha256.txt     the SHA-256 value of each GGUF file of the release
"""

import hashlib
import json
import pathlib
import shutil
import sys

RELEASE = "model-speed-1"
BASE = f"https://github.com/YilongJu/iphone-duo-keyboard/releases/download/{RELEASE}/"
# The models of the shortlist that llama.cpp b4846, the app's framework, loads. b4846 has no
# architecture "qwen3". The attention-only Granite 4.0 converts to the architecture "granite",
# which b4846 has.
LLAMA_ON_PHONE = ("smollm2-360m", "qwen2.5-0.5b", "granite-4.0-350m-base")
TITLES = {
    "smollm2-135m": "SmolLM2-135M",
    "smollm2-360m": "SmolLM2-360M",
    "qwen2.5-0.5b": "Qwen2.5-0.5B",
    "qwen3-0.6b-base": "Qwen3-0.6B-Base",
    "granite-4.0-350m-base": "Granite-4.0-350M-Base",
}
GGUF_TYPES = ("Q4_K_M", "Q4_0")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for piece in iter(lambda: file.read(4 << 20), b""):
            digest.update(piece)
    return digest.hexdigest()


def top_candidates(answers):
    tops = []
    for line in pathlib.Path(answers).read_text().splitlines():
        scores = [sum(float(number) for number in field.split(" ")) for field in line.split("\t")]
        tops.append(max(range(len(scores)), key=lambda index: scores[index]))
    return tops


def main():
    work = pathlib.Path(sys.argv[1])
    coreml = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else None
    names = [model["name"] for model in json.loads(pathlib.Path("scripts/model-speed/models.json").read_text())["models"]]
    reference_dir = pathlib.Path("scripts/model-speed/reference")
    reference_dir.mkdir(parents=True, exist_ok=True)
    references = {"shipped": top_candidates(work / "out/shipped.Q4_K_M.b4846.answers")}
    shutil.copyfile(work / "out/shipped.Q4_K_M.b4846.answers", reference_dir / "shipped.Q4_K_M.b4846.answers")
    for name in names:
        answers = work / f"out/{name}.Q8_0.b12017.answers"
        references[name] = top_candidates(answers)
        shutil.copyfile(answers, reference_dir / f"{name}.Q8_0.answers")
        shutil.copyfile(work / f"tokens/{name}.tokens", f"Shared/model-speed-tokens.{name}.tsv")

    sums = []
    models, pairs = [], []
    pairs.append({"name": "shipped 135M fine-tune, Q4_K_M", "model": "bundled", "runtime": "llama-cpu", "reference": "shipped"})
    pairs.append({"name": "shipped 135M fine-tune, Q4_K_M", "model": "bundled", "runtime": "llama-metal", "reference": "shipped"})
    pairs.append({"name": "shipped 135M fine-tune, Q4_K_M", "model": "bundled", "runtime": "llama-metal-no-residency",
                  "reference": "shipped"})
    for name in names:
        for kind in GGUF_TYPES:
            path = work / f"gguf/{name}.{kind}.gguf"
            digest = sha256(path)
            sums.append(f"{digest}  {path.name}")
            if name not in LLAMA_ON_PHONE:
                continue
            model_id = f"{name}.{kind}"
            models.append({
                "id": model_id,
                "title": f"{TITLES[name]} {kind}",
                "files": [{"path": "model.gguf", "url": BASE + path.name, "sha256": digest, "bytes": path.stat().st_size}],
            })
            pairs.append({"name": f"{TITLES[name]} {kind}", "model": model_id, "runtime": "llama-cpu", "reference": name})
            if kind == "Q4_K_M":
                pairs.append({"name": f"{TITLES[name]} {kind}", "model": model_id, "runtime": "llama-metal",
                              "reference": name})
    if coreml is not None:
        for name in names:
            manifest = json.loads((coreml / f"{name}.manifest.json").read_text())
            model_id = manifest["id"]
            models.append({
                "id": model_id,
                "title": f"{TITLES[name]} Core ML 4-bit",
                "files": [{"path": entry["path"], "url": BASE + entry["asset"], "sha256": entry["sha256"],
                           "bytes": entry["bytes"]} for entry in manifest["files"]],
            })
            pairs.append({"name": f"{TITLES[name]} Core ML 4-bit", "model": model_id, "runtime": "coreml-gpu",
                          "tokens": name, "reference": name})
            if name == "smollm2-135m":
                pairs.append({"name": f"{TITLES[name]} Core ML 4-bit", "model": model_id, "runtime": "coreml-all",
                              "tokens": name, "reference": name})
    catalog = {"release": RELEASE, "models": models, "pairs": pairs}
    pathlib.Path("Shared/model-speed-catalog.json").write_text(json.dumps(catalog, indent=2) + "\n", newline="\n")
    pathlib.Path("Shared/model-speed-reference.json").write_text(json.dumps(references) + "\n", newline="\n")
    pathlib.Path("scripts/model-speed/gguf-sha256.txt").write_text("\n".join(sorted(sums, key=lambda s: s.split()[1])) + "\n",
                                                                   newline="\n")
    print(f"{len(models)} models and {len(pairs)} pairs")


if __name__ == "__main__":
    main()
