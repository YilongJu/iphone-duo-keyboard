"""Builds comparison.html: today's compact layout beside proposal-layout.json, drawn at 458 pt.

Usage, from the repository root:
    python scripts/keyboard-preview/proposal-swipe/make_proposal.py
    python scripts/keyboard-preview/proposal-swipe/build_comparison.py
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
before = json.loads((ROOT / "Shared" / "keyboard-layout.json").read_text(encoding="utf-8"))
after = json.loads((HERE / "proposal-layout.json").read_text(encoding="utf-8"))
html = (HERE / "comparison-template.html").read_text(encoding="utf-8")
for name, data in (("BEFORE", before), ("AFTER", after)):
    placeholder = f"/*{name}_JSON*/"
    if html.count(placeholder) != 1:
        raise SystemExit(f"the template must hold {placeholder} exactly once")
    html = html.replace(placeholder, json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
html = re.sub(r"(?m)^\.", "  .", html)
out = HERE / "comparison.html"
out.write_text(html, encoding="utf-8", newline="\n")
print("wrote", out.relative_to(ROOT))
