#!/usr/bin/env python3
"""Record human resolution of verification-queue items on a run record.

The engine routes doubtful judgments to a human — this records what the human
decided, so the run record shows the FULL control: engine scoring plus the
person who resolved the doubt. Without it, reliance on any queued control is
undocumented.

Usage:
  python3 clear_queue.py --run-record run-record-<id>.json \
      --resolver "Name <email>" \
      --item E2 confirmed "Checked scripts/pull.py — pull is timestamped" \
      --item A2 overturned "No reviewer gate exists; SKILL.md text is aspirational"

Resolutions: confirmed (model judgment stands) | overturned (judgment wrong) |
still-open (looked, could not resolve). Appends to the run record's
queue_clearance list — never rewrites prior entries. report.py renders the
clearance section. No dependencies.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

RESOLUTIONS = ("confirmed", "overturned", "still-open")


def main():
    ap = argparse.ArgumentParser(description="Record verification-queue clearance on a run record.")
    ap.add_argument("--run-record", required=True)
    ap.add_argument("--resolver", required=True, help='Who resolved these items, e.g. "Name <email>"')
    ap.add_argument("--item", nargs=3, action="append", required=True,
                    metavar=("ID", "RESOLUTION", "BASIS"),
                    help=f"Control id, one of {'|'.join(RESOLUTIONS)}, and a one-line basis. Repeatable.")
    args = ap.parse_args()

    try:
        with open(args.run_record, "r", encoding="utf-8") as f:
            rr = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: {args.run_record} is missing or not valid JSON ({e}).")
    if "derived" not in rr or "run_id" not in rr:
        sys.exit(f"ERROR: {args.run_record} is not a run record produced by engine.py.")

    queued = {v["meta"]["id"] for v in (rr["derived"].get("needs_verification") or [])}
    timestamp = datetime.now(timezone.utc).isoformat()
    entries = []
    for cid, resolution, basis in args.item:
        cid = cid.strip().upper()
        if resolution not in RESOLUTIONS:
            sys.exit(f"ERROR: resolution for {cid} must be one of {RESOLUTIONS}, got {resolution!r}.")
        if cid not in queued:
            sys.exit(f"ERROR: {cid} is not in this run's verification queue "
                     f"({', '.join(sorted(queued)) or 'empty'}).")
        entries.append({"id": cid, "resolution": resolution, "basis": basis.strip(),
                        "resolver": args.resolver, "timestamp": timestamp})

    rr.setdefault("queue_clearance", []).extend(entries)
    with open(args.run_record, "w", encoding="utf-8") as f:
        json.dump(rr, f, indent=2, ensure_ascii=False)

    resolved = {e["id"] for e in rr["queue_clearance"] if e["resolution"] != "still-open"}
    remaining = sorted(queued - resolved)
    print(json.dumps({"ok": True, "recorded": [e["id"] for e in entries],
                      "queue_remaining": remaining,
                      "note": "Re-run report.py to render the clearance section."}, indent=2))


if __name__ == "__main__":
    main()
