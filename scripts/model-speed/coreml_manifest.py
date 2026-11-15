"""Lists the files of a compiled Core ML model for the release model-speed-1.

Usage: python3 coreml_manifest.py COMPILED_DIR MODEL_ID MANIFEST.json ASSET_DIR
  COMPILED_DIR  holds model.mlmodelc
  MODEL_ID      the id of the model in Shared/model-speed-catalog.json, such as
                smollm2-135m.coreml-int4
Copies each file of model.mlmodelc into ASSET_DIR under a flat release asset name,
"MODEL_ID--" and the path with "--" in place of each "/", and writes MANIFEST.json: one entry per
file with its path under the model's folder, its asset name, its SHA-256 value and its size.
"""

import hashlib
import json
import pathlib
import shutil
import sys


def main():
    compiled = pathlib.Path(sys.argv[1])
    model_id = sys.argv[2]
    manifest = pathlib.Path(sys.argv[3])
    assets = pathlib.Path(sys.argv[4])
    assets.mkdir(parents=True, exist_ok=True)
    root = compiled / "model.mlmodelc"
    if not root.is_dir():
        raise SystemExit(f"{root} is not a folder")
    entries = []
    for file in sorted(path for path in root.rglob("*") if path.is_file()):
        relative = "model.mlmodelc/" + file.relative_to(root).as_posix()
        asset = model_id + "--" + relative.replace("/", "--")
        shutil.copyfile(file, assets / asset)
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        entries.append({"path": relative, "asset": asset, "sha256": digest, "bytes": file.stat().st_size})
    manifest.write_text(json.dumps({"id": model_id, "files": entries}, indent=2) + "\n")
    print(f"{len(entries)} files, {sum(entry['bytes'] for entry in entries)} bytes")


if __name__ == "__main__":
    main()
