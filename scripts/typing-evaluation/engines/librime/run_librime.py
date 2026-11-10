"""Runs one librime engine name over the Pinyin test cases.

Usage, from the repository root, on a machine with the Ubuntu librime packages and a built rime_cli:
    python3 scripts/typing-evaluation/engines/librime/run_librime.py --engine rime-default \
        --cli build/librime/rime_cli --halves dev test

The script works in build/librime/ENGINE. It copies the stock data folder /usr/share/rime-data into
the shared folder, writes the user folder, deploys once, types the probe strings, and then types
each half of the cases. The outputs go to build/typing-evaluation/ENGINE/.
"""
import argparse
import json
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CASES = ROOT / "scripts" / "typing-evaluation" / "cases"
STOCK_DATA = Path("/usr/share/rime-data")

# The custom patch that turns on the neighbor-key correction of librime.
CORRECTION_PATCH = "patch:\n  translator/enable_correction: true\n"

# The custom patch that adds the fuzzy-sound templates of the stock file pinyin.yaml. The five
# templates are the ones for the sound pairs of the fuzzy_sound category. The last three lines are
# the stock rules of luna_pinyin, and pinyin.yaml says the fuzzy-sound templates go before them.
FUZZY_SOUND_PATCH = """patch:
  speller/algebra:
    __patch:
      - pinyin:/zh_z_bufen
      - pinyin:/n_l_bufen
      - pinyin:/r_l_bufen
      - pinyin:/hu_f_buhun
      - pinyin:/en_eng_bufen
      - pinyin:/abbreviation
      - pinyin:/spelling_correction
      - pinyin:/key_correction
"""
# A rule of the template n_l_bufen. The deployed schema holds it only with the fuzzy-sound patch.
FUZZY_SOUND_MARKER = "derive/^n/l/"

# Each engine name is one stock schema with at most one custom patch.
ENGINES = {
    "rime-default": {"schema": "luna_pinyin_simp", "patch": None},
    "rime-correction": {"schema": "luna_pinyin_simp", "patch": CORRECTION_PATCH},
    "rime-fuzzy": {"schema": "luna_pinyin_simp", "patch": FUZZY_SOUND_PATCH},
    "rime-pinyin-simp-default": {"schema": "pinyin_simp", "patch": None},
    "rime-pinyin-simp-correction": {"schema": "pinyin_simp", "patch": CORRECTION_PATCH},
}

# The stock files each schema reads. A missing file stops the run before the deployment.
STOCK_FILES = {
    "luna_pinyin_simp": ["default.yaml", "luna_pinyin_simp.schema.yaml", "luna_pinyin.schema.yaml", "pinyin.yaml",
                         "luna_pinyin.dict.yaml", "essay.txt"],
    "pinyin_simp": ["default.yaml", "pinyin_simp.schema.yaml", "pinyin_simp.dict.yaml"],
}

# Probe strings that the log shows for every engine name. The first two have a required output.
# The others show how the engine treats one slip each: gn for ng, oa for ao, on for ong, ain for ian,
# a neighbor key, a missing letter, a doubled letter, a letter that does not start a syllable,
# l for n, z for zh, and four slips from the cases.
REQUIRED_PROBES = {"nihao": "你好", "zhongguo": "中国"}
PROBES = ["nihao", "zhongguo", "dagn", "hoa", "zhonguo", "tain", "nihso", "niha", "nihaoo", "nihaoiwomen",
          "lihao", "zongguo", "woydxiangqubeijing", "wocchimianbao", "taicanrnele", "lixihuanyuduiba"]


def run_cli(cli: Path, arguments: list[str], stdin_text: str | None = None) -> str:
    """Runs rime_cli. Its messages and the librime log go straight to this script's stderr."""
    print(f"$ {cli.name} {' '.join(arguments)}", flush=True)
    completed = subprocess.run([str(cli), *arguments], input=stdin_text, stdout=subprocess.PIPE,
                               text=True, encoding="utf-8", check=True)
    return completed.stdout


def convert(cli: Path, folders: list[str], settings: dict, items: list[tuple[str, str]]) -> list[dict]:
    """Types each (id, letters) item and returns one row per item, in the same order."""
    stdin_text = "".join(f"{identifier}\t{typed}\n" for identifier, typed in items)
    stdout = run_cli(cli, ["run", *folders, "--schema", settings["schema"],
                           "--correction", "on" if settings["patch"] is CORRECTION_PATCH else "off"], stdin_text)
    lines = stdout.removesuffix("\n").split("\n")
    if len(lines) != len(items):
        raise SystemExit(f"rime_cli printed {len(lines)} lines for {len(items)} cases")
    rows = []
    for (identifier, typed), line in zip(items, lines):
        fields = line.split("\t")
        if len(fields) != 5 or fields[0] != identifier:
            raise SystemExit(f"unexpected rime_cli line for {identifier}: {line!r}")
        if not fields[1]:
            raise SystemExit(f"rime_cli gave an empty output for {identifier}")
        rows.append({"id": identifier, "typed": typed, "output": fields[1], "stop": fields[2],
                     "selections": int(fields[3]), "first_candidate": fields[4]})
    return rows


def write_details(path: Path, rows: list[dict]) -> None:
    columns = ["id", "typed", "output", "stop", "selections", "first_candidate"]
    lines = ["\t".join(columns)] + ["\t".join(str(row[column]) for column in columns) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=sorted(ENGINES), required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--halves", nargs="+", choices=["dev", "test"], required=True)
    arguments = parser.parse_args()

    settings = ENGINES[arguments.engine]
    schema = settings["schema"]
    cli = arguments.cli.resolve()
    work = ROOT / "build" / "librime" / arguments.engine
    shared, user = work / "shared", work / "user"
    output = ROOT / "build" / "typing-evaluation" / arguments.engine

    for name in STOCK_FILES[schema]:
        if not (STOCK_DATA / name).is_file():
            raise SystemExit(f"the stock file {STOCK_DATA / name} is missing")
    if work.exists():
        shutil.rmtree(work)
    # copytree keeps the file times, and librime compares them with the times in the prebuilt files.
    shutil.copytree(STOCK_DATA, shared)
    user.mkdir(parents=True)
    output.mkdir(parents=True, exist_ok=True)

    custom_files = {"default.custom.yaml": f"patch:\n  schema_list:\n    - schema: {schema}\n"}
    if settings["patch"] is not None:
        custom_files[f"{schema}.custom.yaml"] = settings["patch"]
    for name, text in custom_files.items():
        (user / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"--- {user / name}\n{text}", end="", flush=True)

    folders = ["--shared", str(shared), "--user", str(user)]
    version = run_cli(cli, ["version"]).strip()
    started = time.monotonic()
    run_cli(cli, ["deploy", *folders])
    deploy_seconds = time.monotonic() - started
    staged = sorted(path.name for path in (user / "build").iterdir()) if (user / "build").is_dir() else []
    print(f"deployed in {deploy_seconds:.1f} s, files that librime built in the user folder: {staged}", flush=True)

    # librime reads the deployed schema from the user folder first, then from the prebuilt files.
    deployed = [folder / "build" / f"{schema}.schema.yaml" for folder in (user, shared)]
    deployed = [path for path in deployed if path.is_file()]
    if not deployed:
        raise SystemExit(f"the deployed schema {schema}.schema.yaml is missing")
    has_fuzzy_rule = FUZZY_SOUND_MARKER in deployed[0].read_text(encoding="utf-8")
    if has_fuzzy_rule != (settings["patch"] is FUZZY_SOUND_PATCH):
        raise SystemExit(f"{deployed[0]} {'holds' if has_fuzzy_rule else 'does not hold'} the rule {FUZZY_SOUND_MARKER}")
    print(f"deployed schema {deployed[0]}: the rule {FUZZY_SOUND_MARKER} is {'present' if has_fuzzy_rule else 'absent'}",
          flush=True)

    probe_rows = convert(cli, folders, settings, [(probe, probe) for probe in PROBES])
    write_details(output / "probes.tsv", probe_rows)
    print(f"probes for {arguments.engine}:")
    for row in probe_rows:
        print(f"  {row['typed']:22s} -> {row['output']}   ({row['stop']}, {row['selections']} selections, "
              f"first candidate {row['first_candidate']})")
    for row in probe_rows:
        wanted = REQUIRED_PROBES.get(row["typed"])
        if wanted is not None and row["output"] != wanted:
            raise SystemExit(f"the probe {row['typed']} gave {row['output']!r}, expected {wanted!r}")

    info = {"engine": arguments.engine, "librime_version": version, "schema": schema,
            "custom_files": custom_files,
            "files_built_in_user_folder": staged, "deploy_seconds": round(deploy_seconds, 1), "halves": {}}
    for half in arguments.halves:
        cases = [json.loads(line) for line in (CASES / f"pinyin.{half}.jsonl").read_text(encoding="utf-8").splitlines() if line]
        started = time.monotonic()
        rows = convert(cli, folders, settings, [(case["id"], case["typed"]) for case in cases])
        seconds = time.monotonic() - started
        (output / f"pinyin.{half}.jsonl").write_text(
            "".join(json.dumps({"id": row["id"], "output": row["output"]}, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8", newline="\n")
        write_details(output / f"pinyin.{half}.details.tsv", rows)
        stops = Counter(row["stop"] for row in rows)
        info["halves"][half] = {"cases": len(rows), "seconds": round(seconds, 1), "stops": dict(stops),
                                "cases_with_a_selection": sum(row["selections"] > 0 for row in rows)}
        print(f"{arguments.engine} on pinyin.{half}: {len(rows)} cases in {seconds:.1f} s, stops {dict(stops)}", flush=True)
    (output / "run-info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
