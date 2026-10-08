"""Build dashboard/index.html by dropping dashboard_data.json into the template.

Run:  python src/build_dashboard.py   (after analyze.py)
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "template.html"
DATA = ROOT / "dashboard" / "dashboard_data.json"
OUT = ROOT / "dashboard" / "index.html"


def main():
    template = TEMPLATE.read_text()
    if "__DATA__" not in template:
        raise ValueError("template.html is missing the __DATA__ placeholder")
    data = json.loads(DATA.read_text())
    # Compact JSON; escape "</" so the data can never close the <script> tag early
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    OUT.write_text(template.replace("__DATA__", payload))
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
