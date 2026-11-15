"""Places the downloaded release files of one model at their paths in a models folder, the way
the app's downloader (App/ModelSpeedDownloader.swift) does, and checks each SHA-256 value.

Usage: python3 place_release_files.py MODEL_ID ASSET_DIR OUT_FOLDER
  MODEL_ID    the id of a model of Shared/model-speed-catalog.json
  ASSET_DIR   holds the release assets of the model, as `gh release download` writes them
  OUT_FOLDER  gets OUT_FOLDER/MODEL_ID/<path of each file>
The workflow "Language model in the keyboard" uses it to give the simulator test a Core ML model.
"""

import hashlib
import json
import pathlib
import shutil
import sys


def main():
    model_id, assets, out = sys.argv[1], pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
    catalog = json.loads(pathlib.Path("Shared/model-speed-catalog.json").read_text())
    models = [model for model in catalog["models"] if model["id"] == model_id]
    if len(models) != 1:
        raise SystemExit(f"the catalog has {len(models)} models with the id {model_id}")
    for file in models[0]["files"]:
        source = assets / file["url"].rsplit("/", 1)[1]
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != file["sha256"]:
            raise SystemExit(f"{source} has the SHA-256 value {digest}, expected {file['sha256']}")
        target = out / model_id / file["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    print(f"placed {len(models[0]['files'])} files of {model_id} in {out}")


if __name__ == "__main__":
    main()
