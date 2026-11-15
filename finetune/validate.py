"""Validate train/heldout JSONL against CONTRACTS.md section 4.
Row: {"input": {"snippet","published_at","source_url"}, "output": event | null}
Usage: python finetune/validate.py finetune/train.jsonl"""
import json, sys
from datetime import datetime
from pathlib import Path

schema = json.loads((Path(__file__).parent / "event_schema.json").read_text())
TYPES = schema["properties"]["type"]["enum"]

def ts(s): datetime.fromisoformat(s.replace("Z", "+00:00"))

def check(row):
    errs = []
    inp = row.get("input", {})
    for k in ("snippet", "published_at", "source_url"):
        if k not in inp: errs.append(f"input missing {k}")
    o = row.get("output", "MISSING")
    if o is None: return errs
    if o == "MISSING": return errs + ["no output key"]
    errs += [f"missing {k}" for k in schema["required"] if k not in o]
    if o.get("type") not in TYPES: errs.append(f"bad type {o.get('type')!r}")
    loc = o.get("location") or {}
    errs += [f"location missing {k}" for k in ("name", "lat", "lon") if k not in loc]
    w = o.get("window") or {}
    if "start" not in w or "end" not in w: errs.append("window needs start,end")
    for t in (w.get("start"), w.get("end")):
        if t is not None:
            try: ts(t)
            except ValueError: errs.append(f"bad timestamp {t!r}")
    if any(k in o for k in ("status", "cost", "level")): errs.append("forbidden field (status/cost/level)")
    return errs

if __name__ == "__main__":
    bad = n = 0
    for i, line in enumerate(Path(sys.argv[1]).read_text().splitlines(), 1):
        n += 1
        e = check(json.loads(line))
        if e: bad += 1; print(f"line {i}: {'; '.join(e)}")
    print(f"{'FAIL' if bad else 'ok'}: {n} rows, {bad} bad")
    sys.exit(bad > 0)
