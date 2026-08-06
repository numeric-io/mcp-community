#!/usr/bin/env python3
"""Regression suite for the deterministic engine. Run after ANY change to
engine.py, report.py, or the rubric data:  python3 <skill-dir>/scripts/check_golden.py

Covers: golden happy path, primary auto-union, fabrication caps + majority-unfound
warning, blocker gate, N/A-flood guard, evidence-reuse cap, short-quote fallback,
per-file tie-out (no cross-file phantoms/stitching), low-confidence redirect
rejection, dimension exact-name matching, consensus dispute + full-vs-redirect,
registry append, queue clearance + report rendering, directory-mode submission.

Exits 0 on success, 1 with FAIL lines on any mismatch. No dependencies.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "engine.py")
REPORT = os.path.join(HERE, "report.py")
CLEAR = os.path.join(HERE, "clear_queue.py")
EXAMPLES = os.path.join(HERE, "..", "examples")
EXAMPLE = os.path.join(EXAMPLES, "prepaid-rollforward-workpaper-100.md")
RUBRIC = os.path.join(HERE, "..", "references", "rubric.md")
GOLDEN = os.path.join(EXAMPLES, "golden", "findings.json")

_spec = importlib.util.spec_from_file_location("engine", ENGINE)
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)

FAILURES = []


def check(label, got, want):
    if got != want:
        FAILURES.append(f"FAIL [{label}]: expected {want!r}, got {got!r}")


def check_in(label, needle, hay):
    if needle not in hay:
        FAILURES.append(f"FAIL [{label}]: {needle!r} not found in {str(hay)[:300]!r}")


def golden():
    with open(GOLDEN, "r", encoding="utf-8") as f:
        return json.load(f)


def run_engine(findings_obj, tmp, name, submission=None, extra=None, findings_b=None):
    """Write findings, run engine in tmp cwd. Returns (returncode, stdout-json-or-None)."""
    fpath = os.path.join(tmp, f"{name}.json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(findings_obj, f)
    cmd = [sys.executable, ENGINE, "--findings", fpath,
           "--submission", *(submission or [EXAMPLE]), "--primary", EXAMPLE,
           "--out", os.path.join(tmp, f"rr-{name}.json"), "--reviewer", "Check Golden"]
    if findings_b is not None:
        bpath = os.path.join(tmp, f"{name}-b.json")
        with open(bpath, "w", encoding="utf-8") as f:
            json.dump(findings_b, f)
        cmd += ["--findings-b", bpath]
    cmd += extra or []
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        out = None
    return proc.returncode, out, os.path.join(tmp, f"rr-{name}.json")


def main():
    tmp = tempfile.mkdtemp(prefix="check-golden-")
    norm = engine.normalize_for_match

    # 1. Golden happy path — including unqualified display verdict.
    rc, s, _ = run_engine(golden(), tmp, "g1")
    check("golden rc", rc, 0)
    check("golden verdict", s["verdict"], "Audit-ready")
    check("golden verdict_display", s["verdict_display"], "Audit-ready")
    check("golden score", s["overall_score"], 100)
    check("golden applicable", s["applicable_controls"], "18/18")
    check("golden evidence", s["evidence"], {"tied": 18, "unfound": 0})
    check("golden queue", s["verification_queue"], 0)

    # 2. Primary auto-union: primary omitted from --submission, quotes still tie.
    rc, s, _ = run_engine(golden(), tmp, "g2", submission=[RUBRIC])
    check("auto-union tied", s["evidence"]["tied"], 18)

    # 3. Fabricated quote: cap 40, flagged, queued, verdict qualified.
    g = golden()
    g["checklist"][1]["evidence"] = "this text appears nowhere in any submission file"
    rc, s, rrp = run_engine(g, tmp, "g3")
    check("fab queue", s["verification_queue"], 1)
    check_in("fab verdict qualified", "pending 1 human verification", s["verdict_display"])
    with open(rrp, encoding="utf-8") as f:
        rr3 = json.load(f)
    e2 = next(i for i in rr3["model_findings"]["checklist"] if i["id"] == "E2")
    check("fab conf cap", e2["confidence"], 40)
    check_in("fab flag", "quote_not_found", e2["flags"])

    # 4. Majority-unfound diagnostic fires.
    g = golden()
    for it in g["checklist"][:10]:
        it["evidence"] = "gibberish quote that exists nowhere at all " + it["id"]
    rc, s, rrp = run_engine(g, tmp, "g4")
    with open(rrp, encoding="utf-8") as f:
        warns = " ".join(json.load(f)["validation_warnings"])
    check_in("unfound diagnostic", "NOT found in the submission", warns)

    # 5. Blocker gate: baseline fail => Contains blocker.
    g = golden()
    g["checklist"][4].update({"status": "fail", "evidence": "", "note": "no reviewer gate"})
    rc, s, _ = run_engine(g, tmp, "g5")
    check("blocker verdict", s["verdict"], "Contains blocker")
    check("blocker ids", s["blockers"], ["A2"])

    # 6. N/A flood: 15 controls N/A => baseline N/As queued, applicable surfaced.
    g = golden()
    for it in g["checklist"]:
        if it["id"] not in ("A1", "A2", "A3"):
            it.update({"status": "not_applicable", "confidence": 90, "evidence": ""})
    rc, s, _ = run_engine(g, tmp, "g6")
    check("na applicable", s["applicable_controls"], "3/18")
    check("na baseline queued", s["baseline_controls_pending_verification"] >= 2, True)
    check_in("na verdict surfaces waiver", "scored on 3/18 applicable controls", s["verdict_display"])

    # 7. Evidence reuse: same quote on 3 controls => capped 50 and queued.
    g = golden()
    q = g["checklist"][0]["evidence"]
    for i in (0, 3, 4):  # E1, A1, A2
        g["checklist"][i]["evidence"] = q
    rc, s, rrp = run_engine(g, tmp, "g7")
    check("reuse queue", s["verification_queue"] >= 3, True)
    with open(rrp, encoding="utf-8") as f:
        rr7 = json.load(f)
    a1 = next(i for i in rr7["model_findings"]["checklist"] if i["id"] == "A1")
    check("reuse cap", a1["confidence"], 50)
    check_in("reuse flag", "evidence_reused", a1["flags"])

    # 8. verify_evidence unit checks: short quotes, phantoms, stitching.
    f1, f2 = norm("Every entry cites JE-1042 as the source."), norm("A reviewer must approve.")
    check("short quote ties", engine.verify_evidence("JE-1042", [f1])["verified"], True)
    check("cross-file phantom rejected",
          engine.verify_evidence("the source. a reviewer", [f1, f2])["verified"], False)
    check("cross-file stitch rejected",
          engine.verify_evidence("entry cites je-1042 ... reviewer must approve", [f1, f2])["verified"], False)
    check("same-file stitch ok",
          engine.verify_evidence("every entry ... the source", [f1, f2])["verified"], True)

    # 9. Low-confidence Category-3 redirect is rejected.
    redirect = {"classification": {"category": 3, "confidence": 20, "rationale": "hedgy",
                                   "performs_review_function": False, "review_function_confidence": 50},
                "redirect_message": "out of scope", "what_to_celebrate": "n/a"}
    rc, s, _ = run_engine(redirect, tmp, "g9")
    check("low-conf redirect rejected", rc, 1)

    # 10. Dimension exact-name matching: near-miss name warns, narrative not misattached.
    g = golden()
    g["dimensions"][0]["name"] = "Evidence Trail and Sourcing"  # '&' vs 'and': key differs
    res = engine.validate_and_normalize(g, [norm(open(EXAMPLE, encoding="utf-8").read())])
    check_in("dim mismatch warned", "No dimensions entry matched",
             " ".join(res["data"]["validation_warnings"]))

    # 11. Consensus dispute: conservative status wins, DISPUTED capped.
    gb = golden()
    gb["checklist"][4].update({"status": "fail", "evidence": "", "note": "pass B: no gate"})
    rc, s, _ = run_engine(golden(), tmp, "g11", findings_b=gb)
    check("consensus conservative blocker", s["verdict"], "Contains blocker")
    check("consensus disputed count", s["disputed_controls"], 1)

    # 12. Consensus full-vs-redirect: surfaced as a warning, not a buried badge.
    redirect80 = dict(redirect); redirect80["classification"] = dict(redirect["classification"], confidence=80)
    rc, s, rrp = run_engine(golden(), tmp, "g12", findings_b=redirect80)
    with open(rrp, encoding="utf-8") as f:
        rr12 = json.load(f)
    check_in("kind mismatch warned", "disagreed on whether the rubric applies",
             " ".join(rr12["validation_warnings"]))

    # 13. Registry: one line per run, appended in cwd.
    with open(os.path.join(tmp, "review-registry.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    check("registry populated", len(rows) >= 8, True)
    check("registry fields", all(r.get("run_id") and r.get("skill_name") for r in rows), True)

    # 14. Queue clearance + report rendering.
    rc3 = subprocess.run([sys.executable, CLEAR, "--run-record", os.path.join(tmp, "rr-g3.json"),
                          "--resolver", "Check Golden",
                          "--item", "E2", "confirmed", "verified by inspection"],
                         capture_output=True, text=True, cwd=tmp)
    check("clear_queue rc", rc3.returncode, 0)
    rep = subprocess.run([sys.executable, REPORT, "--run-record", os.path.join(tmp, "rr-g3.json")],
                         capture_output=True, text=True, cwd=tmp)
    check("report rc", rep.returncode, 0)
    with open(os.path.join(tmp, f"review-{rr3['run_id']}.json".replace(".json", ".md")), encoding="utf-8") as f:
        md = f.read()
    check_in("report clearance section", "Queue resolution", md)
    check_in("report reviewer rendered", "Check Golden", md)
    check_in("report qualified verdict", "pending 1 human verification", md)

    # 15. Directory-mode submission (junk skipped, per-file tie-out intact).
    rc, s, _ = run_engine(golden(), tmp, "g15", submission=[EXAMPLES])
    check("dir-mode tied", s["evidence"]["tied"], 18)

    if FAILURES:
        print("\n".join(FAILURES))
        sys.exit(1)
    print(f"OK: 15 regression cases green (artifacts in {tmp}).")


if __name__ == "__main__":
    main()
