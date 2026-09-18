"""Generate static public pages. Safe to run every day under Windows Task Scheduler."""
from __future__ import annotations
import argparse, json, os, tempfile
from pathlib import Path
from data_backend import ROOT, build_payload

OUT = ROOT / "output"

def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text); f.flush(); os.fsync(f.fileno())
    os.replace(temp, path)

def render(template: Path, data, strategy_id=None):
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    text = template.read_text(encoding="utf-8").replace("__PAYLOAD_JSON__", raw)
    return text if strategy_id is None else text.replace("__STRATEGY_ID__", strategy_id)

def main():
    p = argparse.ArgumentParser(); p.add_argument("--no-refresh", action="store_true"); a = p.parse_args()
    payload = build_payload(refresh=not a.no_refresh)
    write(OUT / "latest.json", json.dumps(payload, ensure_ascii=False, indent=2))
    home = render(ROOT / "templates/index.html", payload)
    write(OUT / "index.html", home)
    for strategy in payload["research"]["covered_call"]:
        write(OUT / "strategy" / f"{strategy['id']}.html", render(ROOT / "templates/strategy.html", payload, strategy["id"]))
    print(json.dumps({"status": "published", "market_as_of": payload["market"]["as_of"], "mode": payload["freshness"]["status"]}, ensure_ascii=False))

if __name__ == "__main__":
    main()
