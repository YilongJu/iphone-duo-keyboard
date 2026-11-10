"""Builds docs/keyboard-preview.html from Shared/keyboard-layout.json.

The page draws the keyboard in a browser from the same layout file the iPhone app reads, so a
layout change shows in seconds, before any phone build.

Usage, from the repository root:
    python scripts/keyboard-preview/build_preview.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAYOUT = ROOT / "Shared" / "keyboard-layout.json"
TEMPLATE = Path(__file__).with_name("template.html")
OUTPUT = ROOT / "docs" / "keyboard-preview.html"
PLACEHOLDER = "/*LAYOUT_JSON*/"

layout = json.loads(LAYOUT.read_text(encoding="utf-8"))

# A layout that breaks a rule in check_layout.py does not get a preview.
sys.path.insert(0, str(Path(__file__).parent))
from check_layout import check  # noqa: E402

problems = check(layout)
if problems:
    raise SystemExit("layout problems:\n" + "\n".join(problems))

template = TEMPLATE.read_text(encoding="utf-8")
if template.count(PLACEHOLDER) != 1:
    raise SystemExit(f"template.html must hold {PLACEHOLDER} exactly once")

# "</" inside a script block would end the block, so the JSON escapes the slash.
payload = json.dumps(layout, ensure_ascii=False).replace("</", "<\\/")
html = template.replace(PLACEHOLDER, payload)

# Slack reads a line that starts with a dot as a troff command and mislabels the file.
dot_lines = re.findall(r"(?m)^\..*", html)
if dot_lines:
    raise SystemExit(f"{len(dot_lines)} line(s) start with a dot, first: {dot_lines[0][:60]}")

OUTPUT.write_text(html, encoding="utf-8", newline="\n")
print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(html)} characters)")
