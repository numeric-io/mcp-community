#!/usr/bin/env python3
"""
skill-reviewer deterministic scoring engine.

Ported 1:1 from the Audit-Readiness Reviewer app (v3 "deterministic where it
counts"). The model is a fact-finder only; this engine owns every number:

  - dimension scores      fixed credit table over checklist statuses
  - overall score 0-100   fixed weights, renormalized over applicable dims
  - blocker state         baseline-control table x category x review-function
  - verdict               three buckets, fixed thresholds
  - score drag            any dimension < 6
  - evidence tie-out      every quote string-matched against the submission
  - confidence policy     caps, reliance floor, human-verification queue
  - consensus (optional)  two independent passes reconciled by fixed
                          conservative rules, disagreements flagged DISPUTED
  - run record            hashes, versions, overrides; exportable JSON

The model NEVER supplies: scores, verdicts, blocker flags, or weights. If it
tries, the engine discards them and logs a validation warning.

Usage:
  python3 engine.py --findings findings.json \
      --submission SKILL.md references/*.md \
      --primary SKILL.md
  # run record lands at run-record-{run_id}.json (pass --out to fix the path)
  # consensus:            add --findings-b findings-b.json
  # category override:    add --override-category 1|2|3
  # review-fn override:   add --override-review-fn true|false
  # user-asserted cat:    add --forced-category 1|2|3   (recorded, not applied)

No third-party dependencies. Python 3.8+.
"""

import argparse
import copy
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone

ENGINE_VERSION = "1.0.0"
RUBRIC_VERSION = "3.0"

# ---- Confidence policy (every threshold fixed) ------------------------------
CONF = {
    "HIGH": 85,                  # >= HIGH: high-confidence judgment
    "RELY": 60,                  # < RELY: below reliance floor -> verification queue
    "CAP_QUOTE_NOT_FOUND": 40,   # cited evidence not found in submission
    "CAP_NO_EVIDENCE": 50,       # pass/partial asserted with no supporting quote
    "CAP_DISPUTED": 50,          # consensus passes disagreed
    "CAP_REUSED": 50,            # same quote cited as evidence for 3+ controls
    "CAT3_REDIRECT_MIN": 75,     # model may short-circuit to Cat-3 redirect only at/above
}

# ---- Status policy: fixed credit + severity (for conservative reconciliation)
STATUS_META = {
    "pass":           {"credit": 1.0,  "severity": 4, "label": "Pass"},
    "partial":        {"credit": 0.5,  "severity": 2, "label": "Partial"},
    "fail":           {"credit": 0.0,  "severity": 0, "label": "Fail"},
    "unverifiable":   {"credit": 0.0,  "severity": 1, "label": "Can't verify"},
    "not_applicable": {"credit": None, "severity": 3, "label": "N/A"},
}
VALID_STATUSES = list(STATUS_META.keys())

# ---- The 18-control checklist (6 dimensions x 3). Single source of truth. ---
# baseline:    always a baseline control (an applicable "fail" => Contains blocker)
# baseline_if: "category1"       -> baseline only for Category 1
#              "category1Review" -> baseline only for Category 1 skills that
#                                   perform a review/control function
AUDIT_CHECKLIST = [
    {"id": "E1", "dimension": "Evidence Trail & Sourcing", "label": "Captures the period being operated on explicitly", "baseline": True},
    {"id": "E2", "dimension": "Evidence Trail & Sourcing", "label": "Timestamps when data was pulled from source systems"},
    {"id": "E3", "dimension": "Evidence Trail & Sourcing", "label": "Cites source IDs (transaction IDs, task GIDs, JE numbers, URLs)"},
    {"id": "A1", "dimension": "Attribution & Sign-Off", "label": "Identifies the preparer", "baseline": True},
    {"id": "A2", "dimension": "Attribution & Sign-Off", "label": "Surfaces or requires reviewer before final state", "baseline": True},
    {"id": "A3", "dimension": "Attribution & Sign-Off", "label": "Gates destructive or write-back actions behind confirmation", "baseline": True},
    {"id": "P1", "dimension": "IPE Risk & Evidence Sufficiency", "label": "Workflow pattern (A/B/C/D) is identifiable and evidence design matches it"},
    {"id": "P2", "dimension": "IPE Risk & Evidence Sufficiency", "label": "Validates completeness & accuracy of input data before operating on it"},
    {"id": "P3", "dimension": "IPE Risk & Evidence Sufficiency", "label": "Documents judgments/transformations and requires user sign-off on them"},
    {"id": "R1", "dimension": "Reproducibility & Snapshot Discipline", "label": "Output is run-stamped (timestamp + run ID)"},
    {"id": "R2", "dimension": "Reproducibility & Snapshot Discipline", "label": "Locks source data snapshot rather than re-pulling live state"},
    {"id": "R3", "dimension": "Reproducibility & Snapshot Discipline", "label": "Excluded items surfaced explicitly, not silently dropped"},
    {"id": "M1", "dimension": "Materiality & Threshold Awareness", "label": "Applies a documented, defensible materiality threshold (basis stated)", "baseline_if": "category1Review"},
    {"id": "M2", "dimension": "Materiality & Threshold Awareness", "label": "Flags items above threshold for human review"},
    {"id": "M3", "dimension": "Materiality & Threshold Awareness", "label": "Surfaces items below threshold (not hidden); aggregates where relevant"},
    {"id": "O1", "dimension": "Auditor-Consumable Output", "label": "Output is an auditor-consumable artifact (xlsx/PDF/workpaper, not just chat)", "baseline_if": "category1"},
    {"id": "O2", "dimension": "Auditor-Consumable Output", "label": "Output includes sign-off block / run metadata footer"},
    {"id": "O3", "dimension": "Auditor-Consumable Output", "label": "Computed numbers shown as correct, traceable formulas, not hard-coded values"},
]
CONTROL_COUNT = len(AUDIT_CHECKLIST)  # 18 -- derived, so copy can never drift
ALL_IDS = [c["id"] for c in AUDIT_CHECKLIST]

DIMENSION_RUBRIC = [
    {"name": "Attribution & Sign-Off", "weight": 30, "short": "Segregation of duties",
     "blurb": "Is the preparer identified, a reviewer required before final state, and write-back gated behind confirmation? The highest-stakes dimension — a single person controlling the full transaction lifecycle is a design-level ICFR deficiency."},
    {"name": "Evidence Trail & Sourcing", "weight": 25, "short": "Traceability",
     "blurb": "Is the period explicit, the data pull timestamped, and every number traceable to a source ID? Without traceability nothing else holds up."},
    {"name": "IPE Risk & Evidence Sufficiency", "weight": 20, "short": "Information Produced by the Entity",
     "blurb": "Does the skill's evidence design match its workflow pattern (A–D)? Cross-system and judgment workflows need completeness checks, transformation docs, and sign-off on the judgments themselves."},
    {"name": "Auditor-Consumable Output", "weight": 20, "short": "The artifact must exist",
     "blurb": "Is the final output something an auditor can receive — a formatted workpaper with sign-off block and correct, traceable formulas — rather than a chat answer that disappears? (Not a blocker for Category 2 process enablers.)"},
    {"name": "Reproducibility & Snapshot Discipline", "weight": 15, "short": "Same inputs, same output",
     "blurb": "Does the skill lock its data snapshot and run-stamp its output, so re-running a week later doesn't silently produce a different answer? Largely a consequence of good evidence-trail discipline."},
    {"name": "Materiality & Threshold Awareness", "weight": 10, "short": "Contextual — graded only where it applies",
     "blurb": "Where relevant to the work, is there a documented, defensible threshold (basis stated, not a bare number), with above/below handling, aggregation, and qualitative triggers? Controls inapplicable to the work type are excluded, not zero-scored."},
]

CHECKLIST_BY_DIMENSION = {}
for item in AUDIT_CHECKLIST:
    CHECKLIST_BY_DIMENSION.setdefault(item["dimension"], []).append(item)


# ---- Small utilities ---------------------------------------------------------

def js_round(x):
    """JS Math.round semantics: half rounds toward +infinity."""
    import math
    return math.floor(x + 0.5)


def clamp_int(v, lo, hi, fallback):
    try:
        n = js_round(float(v))
    except (TypeError, ValueError):
        return fallback
    if n != n:  # NaN
        return fallback
    return max(lo, min(hi, n))


def fnv1a(s):
    """FNV-1a 32-bit — stable content hash for run records (matches the app)."""
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch) & 0xFFFF  # charCodeAt parity for BMP text
        h = (h * 0x01000193) & 0xFFFFFFFF
    return format(h, "08x")


def is_baseline_for_category(meta, category, review_fn):
    if meta.get("baseline"):
        return True
    if meta.get("baseline_if") == "category1" and category == 1:
        return True
    if meta.get("baseline_if") == "category1Review" and category == 1 and review_fn is True:
        return True
    return False


# ---- Evidence tie-out: does the model's quote actually appear in the corpus? -

_NORM_STRIP = re.compile(r'[`*_>#"“”‘’\']')
_WS = re.compile(r"\s+")


def normalize_for_match(s):
    s = (s or "").lower()
    s = _NORM_STRIP.sub("", s)
    s = _WS.sub(" ", s)
    return s.strip()


def verify_evidence(evidence, norm_files):
    """norm_files: one normalized corpus PER submission file. All fragments of a
    quote must appear in the SAME file — matching against a single concatenation
    let quotes span file boundaries (text existing in no file) and let ellipsis
    fragments stitch unrelated files into 'verified' evidence."""
    norm = normalize_for_match(evidence)
    if not norm:
        return {"provided": False, "verified": False}
    # Models often join fragments with ellipses — verify each fragment independently.
    segments = [seg.strip() for seg in re.split(r"\.\.\.|…", norm)]
    long_enough = [seg for seg in segments if len(seg) >= 8]
    # Short genuine quotes (source IDs like "JE-1042") fall back to exact
    # membership instead of being branded fabricated.
    segments = long_enough or [seg for seg in segments if seg]
    if not segments:
        return {"provided": True, "verified": False}
    verified = any(all(seg in nf for seg in segments) for nf in norm_files)
    return {"provided": True, "verified": verified}


# ---- Validate + normalize a raw model response into a trusted shape. ---------

def validate_and_normalize(raw, norm_files):
    """Returns {ok, fatal:[], warnings:[], data}. Missing checklist items are
    injected as unverifiable/conf-0 so downstream math never sees a hole."""
    warnings = []
    fatal = []
    if not isinstance(raw, dict):
        return {"ok": False, "fatal": ["Response is not a JSON object."], "warnings": warnings, "data": None}

    # --- classification ---
    raw_class = raw.get("classification") or {}
    legacy_category = raw.get("skill_category")  # tolerate older shape
    category = clamp_int(raw_class.get("category", legacy_category), 1, 3, 0)
    if category not in (1, 2, 3):
        warnings.append("classification.category missing/invalid — defaulted to 1 (most scrutiny).")
        category = 1
    classification = {
        "category": category,
        "confidence": clamp_int(raw_class.get("confidence"), 0, 100, 50),
        "rationale": str(raw_class.get("rationale") or raw.get("classification_rationale") or "").strip(),
        "performs_review_function": raw_class.get("performs_review_function") is True,
        "review_function_confidence": clamp_int(raw_class.get("review_function_confidence"), 0, 100, 50),
    }
    if raw_class.get("confidence") is None:
        warnings.append("classification.confidence missing — defaulted to 50.")

    # --- redirect (confident Category 3) ---
    is_redirect = category == 3 and not isinstance(raw.get("checklist"), list)
    if is_redirect and classification["confidence"] < CONF["CAT3_REDIRECT_MIN"]:
        return {"ok": False,
                "fatal": [f"Category-3 redirect requires classification confidence >= "
                          f"{CONF['CAT3_REDIRECT_MIN']}% (got {classification['confidence']}%). "
                          "A low-confidence Category-3 lean must submit the full 18-control "
                          "schema so the user can rescore with --override-category."],
                "warnings": warnings, "data": None}
    if is_redirect:
        return {
            "ok": True, "fatal": fatal, "warnings": warnings,
            "data": {
                "kind": "redirect",
                "classification": classification,
                "ipe": None,
                "headline": "",
                "checklist": [],
                "dimensions": [],
                "redirect_message": str(raw.get("redirect_message") or "").strip(),
                "rewritten_description": "",
                "top_three_remediations": [],
                "what_to_celebrate": str(raw.get("what_to_celebrate") or "").strip(),
                "validation_warnings": warnings,
            },
        }

    # --- checklist (required for a scored review) ---
    raw_checklist = raw.get("checklist")
    if not isinstance(raw_checklist, list) or len(raw_checklist) == 0:
        return {"ok": False,
                "fatal": ["checklist array missing or empty for a scored (Category 1/2) review."],
                "warnings": warnings, "data": None}
    supplied_by_id = {}
    for it in raw_checklist:
        if isinstance(it, dict) and isinstance(it.get("id"), str):
            supplied_by_id[it["id"].strip().upper()] = it

    checklist = []
    for meta in AUDIT_CHECKLIST:
        src = supplied_by_id.get(meta["id"])
        flags = []
        if not src:
            warnings.append(f"Checklist item {meta['id']} missing from response — injected as unverifiable, confidence 0.")
            checklist.append({
                "id": meta["id"], "status": "unverifiable", "confidence": 0,
                "note": "Model did not evaluate this control — verify manually or re-run.",
                "evidence": "", "evidence_provided": False, "evidence_verified": False,
                "flags": ["not_evaluated"], "disputed": False,
            })
            continue
        status = re.sub(r"[\s-]+", "_", str(src.get("status") or "").lower().strip())
        if status in ("na", "n_a", "not_app"):
            status = "not_applicable"
        if status not in VALID_STATUSES:
            warnings.append(f'Item {meta["id"]}: invalid status "{src.get("status")}" — coerced to unverifiable.')
            status = "unverifiable"
            flags.append("invalid_status")
        confidence = clamp_int(src.get("confidence"), 0, 100, 50)
        if src.get("confidence") is None:
            warnings.append(f"Item {meta['id']}: confidence missing — defaulted to 50.")
            flags.append("confidence_defaulted")

        evidence = str(src.get("evidence") or "").strip()[:400]
        tie = verify_evidence(evidence, norm_files)
        provided, verified = tie["provided"], tie["verified"]
        # Deterministic confidence caps — the anti-hallucination controls:
        if provided and not verified:
            confidence = min(confidence, CONF["CAP_QUOTE_NOT_FOUND"])
            flags.append("quote_not_found")
        if status in ("pass", "partial") and (not provided or not verified):
            confidence = min(confidence, CONF["CAP_NO_EVIDENCE"])
            flags.append("asserted_without_evidence")
        checklist.append({
            "id": meta["id"], "status": status, "confidence": confidence,
            "note": str(src.get("note") or "").strip(),
            "evidence": evidence, "evidence_provided": provided, "evidence_verified": verified,
            "flags": flags, "disputed": False,
        })

    # --- evidence reuse: one quote cited for 3+ controls is boilerplate, not
    # per-control evidence. Tie-out proves quotation, not relevance — cap and
    # queue so a human decides whether the reuse is legitimate.
    reuse_counts = {}
    for it in checklist:
        key = normalize_for_match(it["evidence"])
        if key:
            reuse_counts[key] = reuse_counts.get(key, 0) + 1
    for it in checklist:
        key = normalize_for_match(it["evidence"])
        if key and reuse_counts[key] >= 3:
            it["confidence"] = min(it["confidence"], CONF["CAP_REUSED"])
            it["flags"].append("evidence_reused")
    reused = sorted({it["id"] for it in checklist if "evidence_reused" in it["flags"]})
    if reused:
        warnings.append(
            f"The same evidence quote was cited for {len(reused)} controls ({', '.join(reused)}) — "
            f"confidence capped at {CONF['CAP_REUSED']}% and routed to human verification. "
            "Tie-out verifies quotation, not per-control relevance.")

    # --- IPE pattern ---
    raw_ipe = raw.get("ipe") or {}
    pattern = str(raw_ipe.get("pattern") or "").strip().upper()
    if pattern not in ("A", "B", "C", "D"):
        if raw_ipe.get("pattern") is not None:
            warnings.append(f'ipe.pattern invalid ("{raw_ipe.get("pattern")}") — cleared.')
        pattern = None
    ipe = {
        "pattern": pattern,
        "confidence": clamp_int(raw_ipe.get("confidence"), 0, 100, 50),
        "rationale": str(raw_ipe.get("rationale") or "").strip(),
    }

    # --- narrative dimensions (qualitative only; scores computed here, not there)
    raw_dims = raw.get("dimensions") if isinstance(raw.get("dimensions"), list) else []

    def dim_key(name):
        return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()

    dims_by_key = {dim_key(x["name"]): x for x in raw_dims
                   if isinstance(x, dict) and isinstance(x.get("name"), str)}
    dimensions = []
    for d in DIMENSION_RUBRIC:
        src = dims_by_key.get(dim_key(d["name"]), {})
        if not src and raw_dims:
            warnings.append(f'No dimensions entry matched "{d["name"]}" (names must match the '
                            "rubric exactly) — narrative left empty.")
        if src.get("score") is not None:
            warnings.append(f'Model supplied a score for "{d["name"]}" — ignored (scores are computed by the engine).')
        dim = {
            "name": d["name"],
            "what_works": str(src.get("what_works") or "").strip(),
            "what_to_fix": str(src.get("what_to_fix") or "").strip(),
            "example_fix": str(src.get("example_fix") or "").strip(),
        }
        if isinstance(src.get("materiality_concepts"), list):
            dim["materiality_concepts"] = [str(c) for c in src["materiality_concepts"]][:5]
        dimensions.append(dim)

    if raw.get("overall_score") is not None:
        warnings.append("Model supplied overall_score — ignored (computed by the engine).")
    if raw.get("is_blocker") is not None:
        warnings.append("Model supplied is_blocker — ignored (computed by the engine).")

    top3 = raw.get("top_three_remediations")
    top3 = [str(x) for x in top3][:3] if isinstance(top3, list) else []

    return {
        "ok": True, "fatal": fatal, "warnings": warnings,
        "data": {
            "kind": "full",
            "classification": classification,
            "ipe": ipe,
            "headline": str(raw.get("headline") or "").strip(),
            "checklist": checklist,
            "dimensions": dimensions,
            "redirect_message": str(raw.get("redirect_message") or "").strip(),
            "rewritten_description": str(raw.get("rewritten_description") or "").strip(),
            "top_three_remediations": top3,
            "what_to_celebrate": str(raw.get("what_to_celebrate") or "").strip(),
            "validation_warnings": warnings,
        },
    }


# ---- Consensus mode: reconcile two independent passes with fixed rules. ------
# Status disagreement -> take the more conservative status (lower severity),
# cap confidence at CAP_DISPUTED, flag DISPUTED. Narrative comes from pass 1.

def reconcile_passes(a, b):
    if a["kind"] == "redirect" and b["kind"] == "redirect":
        merged = copy.deepcopy(a)
        merged["classification"]["confidence"] = js_round(
            (a["classification"]["confidence"] + b["classification"]["confidence"]) / 2)
        return {"data": merged, "disputed_ids": [], "classification_disputed": False}
    if a["kind"] != b["kind"]:
        # One pass scored it, one redirected — keep the scored pass (more
        # scrutiny), but the classification is disputed and capped. This is a
        # TOTAL disagreement about whether the rubric applies; surface it at
        # least as loudly as a single-control dispute.
        full = a if a["kind"] == "full" else b
        merged = copy.deepcopy(full)
        merged["classification"]["confidence"] = min(
            merged["classification"]["confidence"], CONF["CAP_DISPUTED"])
        return {"data": merged, "disputed_ids": [], "classification_disputed": True,
                "kind_mismatch": True}

    merged = copy.deepcopy(a)
    b_by_id = {i["id"]: i for i in b["checklist"]}
    disputed_ids = []
    new_checklist = []
    for ia in merged["checklist"]:
        ib = b_by_id.get(ia["id"])
        if not ib:
            new_checklist.append(ia)
            continue
        if ia["status"] == ib["status"]:
            # Prefer the pass whose evidence actually tied out; union the flags
            # so one pass's tie-out failure survives the merge, and take min
            # (not average) confidence when either pass had a tie-out flag —
            # averaging half-washed a 40-cap back above the reliance floor.
            base = ia if (ia["evidence_verified"] or not ib["evidence_verified"]) else ib
            item = dict(base)
            item["flags"] = sorted(set((ia.get("flags") or []) + (ib.get("flags") or [])))
            tie_flags = {"quote_not_found", "asserted_without_evidence"}
            both_tied = ia["evidence_verified"] and ib["evidence_verified"]
            if both_tied or not (tie_flags & set(item["flags"])):
                item["confidence"] = js_round((ia["confidence"] + ib["confidence"]) / 2)
            else:
                item["confidence"] = min(ia["confidence"], ib["confidence"])
            new_checklist.append(item)
            continue
        disputed_ids.append(ia["id"])
        conservative = ia if STATUS_META[ia["status"]]["severity"] <= STATUS_META[ib["status"]]["severity"] else ib
        item = dict(conservative)
        item["confidence"] = min(ia["confidence"], ib["confidence"], CONF["CAP_DISPUTED"])
        item["disputed"] = True
        item["flags"] = sorted(set((conservative.get("flags") or []) + ["disputed_between_passes"]))
        item["note"] = (conservative.get("note") or "") + \
            f' [Passes disagreed: {ia["status"]} vs {ib["status"]} — conservative status taken.]'
        new_checklist.append(item)
    merged["checklist"] = new_checklist

    # Classification: lower category number = more scrutiny = conservative.
    classification_disputed = False
    if a["classification"]["category"] != b["classification"]["category"]:
        classification_disputed = True
        merged["classification"]["category"] = min(a["classification"]["category"], b["classification"]["category"])
        merged["classification"]["confidence"] = min(
            a["classification"]["confidence"], b["classification"]["confidence"], CONF["CAP_DISPUTED"])
    else:
        merged["classification"]["confidence"] = js_round(
            (a["classification"]["confidence"] + b["classification"]["confidence"]) / 2)
    if a["classification"]["performs_review_function"] != b["classification"]["performs_review_function"]:
        classification_disputed = True
        merged["classification"]["performs_review_function"] = True  # conservative: review fn => M1 gate applies
        merged["classification"]["review_function_confidence"] = min(
            a["classification"]["review_function_confidence"],
            b["classification"]["review_function_confidence"], CONF["CAP_DISPUTED"])
    # IPE: higher letter = more exposure = conservative.
    a_p = (a.get("ipe") or {}).get("pattern")
    b_p = (b.get("ipe") or {}).get("pattern")
    if a_p and b_p and a_p != b_p:
        merged["ipe"]["pattern"] = max(a_p, b_p)
        merged["ipe"]["confidence"] = min(a["ipe"]["confidence"], b["ipe"]["confidence"], CONF["CAP_DISPUTED"])
    return {"data": merged, "disputed_ids": disputed_ids, "classification_disputed": classification_disputed}


# ---- Derive everything displayable from normalized model output + overrides. -
# Pure: same inputs => same review.

def derive_review(model, overrides=None):
    ov = overrides or {}
    category = ov.get("category", model["classification"]["category"])
    review_fn = ov.get("review_fn", model["classification"]["performs_review_function"])

    if category == 3 or model["kind"] == "redirect":
        return {"category": category, "review_fn": review_fn, "out_of_scope": True,
                "can_rescore_inline": model["kind"] == "full"}

    by_id = {i["id"]: i for i in model["checklist"]}

    # Dimension scores — fixed credit table, N/A excluded from the denominator.
    dims = []
    for d in DIMENSION_RUBRIC:
        metas = CHECKLIST_BY_DIMENSION.get(d["name"], [])
        items = [{"meta": m, "item": by_id[m["id"]]} for m in metas if m["id"] in by_id]
        applicable = [x for x in items if x["item"]["status"] != "not_applicable"]
        credits = sum(STATUS_META[x["item"]["status"]]["credit"] for x in applicable)
        score = js_round((credits / len(applicable)) * 100) / 10 if applicable else None
        counts = {"pass": 0, "partial": 0, "fail": 0, "unverifiable": 0, "not_applicable": 0}
        for x in items:
            counts[x["item"]["status"]] += 1
        dims.append({**d, "score": score, "counts": counts,
                     "applicable_count": len(applicable), "item_count": len(items)})

    # Overall — fixed weights, renormalized over dimensions with applicable controls.
    scored = [d for d in dims if d["score"] is not None]
    weight_sum = sum(d["weight"] for d in scored)
    overall = js_round(sum(d["score"] * d["weight"] for d in scored) / weight_sum * 10) if weight_sum else 0

    # Blockers — applicable baseline control failed.
    blockers = []
    for meta in AUDIT_CHECKLIST:
        if not is_baseline_for_category(meta, category, review_fn):
            continue
        item = by_id.get(meta["id"])
        if item and item["status"] == "fail":
            blockers.append({"meta": meta, "item": item})

    # Human-verification queue — judgments the engine refuses to silently rely on.
    needs_verification = []
    for meta in AUDIT_CHECKLIST:
        item = by_id.get(meta["id"])
        if not item:
            continue
        baseline = is_baseline_for_category(meta, category, review_fn)
        reasons = []
        if item["confidence"] < CONF["RELY"]:
            reasons.append(f'confidence {item["confidence"]}% — below the {CONF["RELY"]}% reliance floor')
        if item["status"] == "unverifiable":
            reasons.append("could not be verified from the submission")
        if baseline and item["status"] == "not_applicable":
            # At ANY confidence: waiving a baseline control removes it from the
            # score's denominator, so a human always confirms the waiver.
            reasons.append("baseline control judged N/A — a person must confirm the waiver")
        if "quote_not_found" in item["flags"]:
            reasons.append("cited evidence was not found in the submission")
        if "evidence_reused" in item["flags"]:
            reasons.append("same evidence quote reused across 3+ controls — relevance unverified")
        if reasons:
            needs_verification.append({"meta": meta, "item": item, "baseline": baseline,
                                       "reasons": list(dict.fromkeys(reasons))})
    baseline_pending = [v for v in needs_verification if v["baseline"]]

    verdict = ("Contains blocker" if blockers
               else "Audit-ready" if overall >= 85
               else "Remediations recommended")

    # The displayed verdict carries the engine's own doubt — a queue full of
    # unverified judgments must qualify the headline, not sit below the fold.
    applicable_total = sum(1 for i in model["checklist"] if i["status"] != "not_applicable")
    verdict_display = verdict
    if needs_verification:
        verdict_display += (f" — pending {len(needs_verification)} human verification"
                            f"{'s' if len(needs_verification) != 1 else ''}")
        if baseline_pending:
            verdict_display += f" ({len(baseline_pending)} baseline)"
    if applicable_total < CONTROL_COUNT:
        verdict_display += f" · scored on {applicable_total}/{CONTROL_COUNT} applicable controls"

    # Findings confidence — weighted mean of per-control confidence using dimension weights.
    cw = cs = 0.0
    for d in DIMENSION_RUBRIC:
        metas = CHECKLIST_BY_DIMENSION.get(d["name"], [])
        for meta in metas:
            it = by_id.get(meta["id"])
            if it:
                w = d["weight"] / len(metas)
                cw += w
                cs += it["confidence"] * w
    findings_confidence = js_round(cs / cw) if cw else 0

    score_drag = [d for d in scored if d["score"] < 6]
    disputed_count = sum(1 for i in model["checklist"] if i.get("disputed"))
    evidence_stats = {
        "tied": sum(1 for i in model["checklist"] if i["evidence_verified"]),
        "unfound": sum(1 for i in model["checklist"] if "quote_not_found" in i["flags"]),
    }

    return {
        "category": category, "review_fn": review_fn, "out_of_scope": False,
        "dims": dims, "overall": overall,
        "blockers": blockers, "needs_verification": needs_verification,
        "baseline_pending": baseline_pending, "verdict": verdict,
        "verdict_display": verdict_display, "applicable_total": applicable_total,
        "control_count": CONTROL_COUNT,
        "findings_confidence": findings_confidence,
        "score_drag": score_drag, "disputed_count": disputed_count,
        "evidence_stats": evidence_stats,
    }


# ---- CLI ----------------------------------------------------------------------

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: findings file {path} is missing or not valid JSON ({e}) — "
              "re-write it and re-run.", file=sys.stderr)
        sys.exit(2)


# Junk to skip when a --submission argument is a directory (same list as SKILL.md Step 0).
JUNK_DIRS = {".git", "node_modules", "__pycache__"}
JUNK_FILES = {".DS_Store"}
JUNK_SUFFIXES = (".pyc", ".lock", ".zip", ".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".pdf")


def expand_submission(paths):
    """Expand directories into their reviewable files; skip junk."""
    out = []
    for p in paths:
        if not os.path.isdir(p):
            out.append(p)
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = sorted(d for d in dirs if d not in JUNK_DIRS)
            for name in sorted(files):
                if name in JUNK_FILES or name.lower().endswith(JUNK_SUFFIXES):
                    continue
                out.append(os.path.join(root, name))
    return out


def skill_name_from_primary(path):
    """Best-effort `name:` from the primary file's frontmatter, else basename."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(4000)
        m = re.search(r"^name:\s*(.+)$", head, re.MULTILINE)
        if m:
            return m.group(1).strip()
    except OSError:
        pass
    return os.path.basename(path)


def main():
    ap = argparse.ArgumentParser(description="Deterministic audit-readiness scoring engine.")
    ap.add_argument("--findings", required=True, help="Model findings JSON (pass 1)")
    ap.add_argument("--findings-b", help="Second independent pass for consensus mode")
    ap.add_argument("--submission", nargs="+", required=True,
                    help="Every file whose text evidence quotes may have come from")
    ap.add_argument("--primary", required=True, help="Path of the primary file (the SKILL.md under review)")
    ap.add_argument("--override-category", type=int, choices=[1, 2, 3],
                    help="User override: rescore findings under this category (no model re-run)")
    ap.add_argument("--override-review-fn", choices=["true", "false"],
                    help="User override for performs_review_function")
    ap.add_argument("--forced-category", type=int, choices=[1, 2, 3],
                    help="Category the USER asserted before the model pass (recorded in the run record)")
    ap.add_argument("--reviewer", help="Identity of the person running this review "
                    "(defaults to $USER); recorded in the run record")
    ap.add_argument("--reviewer-relation", choices=["author", "independent", "unknown"],
                    default="unknown",
                    help="Reviewer's relation to the reviewed skill (self-attested; recorded "
                    "and rendered so an author-run review cannot pose as independent)")
    ap.add_argument("--archive", metavar="DIR", nargs="?", const="",
                    help="Copy the submission corpus to DIR (default run-archive-{run_id}/) so "
                    "quote tie-out can be re-performed later. Recommended for auditor-facing reviews.")
    ap.add_argument("--registry", default="review-registry.jsonl",
                    help="Append-only review registry (JSONL); every run appends one line so the "
                    "population of reviewed skills is enumerable. Default: review-registry.jsonl in CWD.")
    ap.add_argument("--out", help="Output run record path (default: run-record-{run_id}.json "
                    "so re-runs never silently overwrite)")
    args = ap.parse_args()

    # The primary file is always part of the evidence corpus — omitting it from
    # --submission was the most common way to get a misleading review. Directories
    # expand with the same junk skip list as SKILL.md Step 0; duplicate entries
    # (a.md ./a.md) are deduped by realpath so the manifest — and therefore the
    # run_id lineage — is identical for the same logical input.
    engine_warnings = []
    submission, seen = [], set()
    for p in expand_submission(args.submission):
        rp = os.path.realpath(p)
        if rp not in seen:
            seen.add(rp)
            submission.append(p)
    if os.path.realpath(args.primary) not in seen:
        submission.append(args.primary)
        engine_warnings.append(
            f"--primary {args.primary} was not in --submission — auto-included in the evidence corpus.")

    # Build the corpus and file manifest.
    corpus_parts, manifest = [], []
    for path in submission:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            print(f"ERROR: cannot read submission file {path}: {e}", file=sys.stderr)
            sys.exit(2)
        corpus_parts.append(text)
        manifest.append({"path": path, "realpath": os.path.realpath(path),
                         "size": len(text), "hash": fnv1a(text)})
    # One normalized corpus PER FILE — quotes must tie out within a single file.
    norm_files = [normalize_for_match(t) for t in corpus_parts]

    # Validate pass 1 (and pass 2 if consensus).
    res_a = validate_and_normalize(load_json(args.findings), norm_files)
    if not res_a["ok"]:
        print(json.dumps({"ok": False, "fatal": res_a["fatal"], "warnings": res_a["warnings"]}, indent=2))
        sys.exit(1)
    model = res_a["data"]
    passes = 1
    disputed_ids, classification_disputed = [], False
    if args.findings_b:
        res_b = validate_and_normalize(load_json(args.findings_b), norm_files)
        if not res_b["ok"]:
            print(json.dumps({"ok": False, "fatal": res_b["fatal"], "warnings": res_b["warnings"]}, indent=2))
            sys.exit(1)
        rec = reconcile_passes(res_a["data"], res_b["data"])
        model = rec["data"]
        model["validation_warnings"] = list(dict.fromkeys(
            res_a["data"]["validation_warnings"] + res_b["data"]["validation_warnings"]))
        disputed_ids = rec["disputed_ids"]
        classification_disputed = rec["classification_disputed"]
        if rec.get("kind_mismatch"):
            engine_warnings.append(
                "Consensus passes disagreed on whether the rubric applies at all — one pass "
                "scored the skill, one redirected it as Category 3. The scored pass was kept and "
                "classification confidence capped at 50%. Treat the classification as unresolved.")
        passes = 2

    overrides = {}
    if args.override_category:
        overrides["category"] = args.override_category
    if args.override_review_fn:
        overrides["review_fn"] = args.override_review_fn == "true"

    derived = derive_review(model, overrides)

    # Diagnostic: a mostly-failed tie-out usually means an operator error, not
    # fabricated quotes — say so instead of leaving a confusing bad review.
    ev = derived.get("evidence_stats") or {}
    cited = ev.get("tied", 0) + ev.get("unfound", 0)
    if ev.get("unfound", 0) >= 1 and ev["unfound"] * 2 >= cited:
        engine_warnings.append(
            f"{ev['unfound']} of {cited} cited quotes were NOT found in the submission. "
            "If the quotes are genuine, --submission is probably missing a quoted file — "
            "fix the file list and re-run before trusting this review.")
    model["validation_warnings"] = model["validation_warnings"] + engine_warnings

    timestamp = datetime.now(timezone.utc).isoformat()
    manifest_hash = fnv1a(json.dumps(manifest, separators=(",", ":")))
    run_id = fnv1a(manifest_hash + timestamp + str(passes))
    out_path = args.out or f"run-record-{run_id}.json"
    reviewer = args.reviewer or os.environ.get("USER") or ""
    run_record = {
        "run_id": run_id,
        "reviewer": {"name": reviewer,
                     "source": "flag" if args.reviewer else ("env" if reviewer else "unknown"),
                     "relation": args.reviewer_relation},
        "skill_name": skill_name_from_primary(args.primary),
        "timestamp": timestamp,
        "engine_version": ENGINE_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "passes": passes,
        "primary": args.primary,
        "files": manifest,
        "file_manifest_hash": manifest_hash,
        "forced_category": args.forced_category,
        "overrides": overrides,
        "consensus": {"passes": passes, "disputed_ids": disputed_ids,
                      "classification_disputed": classification_disputed},
        "validation_warnings": model["validation_warnings"],
        "model_findings": model,
        "derived": derived,
        "policy": {"conf": CONF,
                   "weights": {d["name"]: d["weight"] for d in DIMENSION_RUBRIC},
                   "credit": {k: v["credit"] for k, v in STATUS_META.items()},
                   "hash_note": "FNV-1a 32-bit content hashes are integrity fingerprints for "
                                "drift detection, not tamper-evidence."},
    }

    # Archive the corpus so tie-out is re-performable after the originals move.
    if args.archive is not None:
        archive_dir = args.archive or f"run-archive-{run_id}"
        os.makedirs(archive_dir, exist_ok=True)
        import shutil
        for i, path in enumerate(submission):
            shutil.copy2(path, os.path.join(archive_dir, f"{i:02d}-{os.path.basename(path)}"))
        run_record["archive_dir"] = archive_dir

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(run_record, f, indent=2, ensure_ascii=False)

    # Append-only registry: makes "which skills were reviewed" enumerable, so the
    # population behind "skills are vetted before shipping" is testable.
    registry_row = {
        "timestamp": timestamp, "run_id": run_id,
        "skill_name": run_record["skill_name"], "primary": args.primary,
        "file_manifest_hash": manifest_hash,
        "category": derived["category"],
        "verdict": derived.get("verdict_display") or ("Out of scope (Category 3)"
                   if derived.get("out_of_scope") else ""),
        "overall": derived.get("overall"),
        "reviewer": reviewer, "run_record": out_path,
    }
    with open(args.registry, "a", encoding="utf-8") as f:
        f.write(json.dumps(registry_row, ensure_ascii=False) + "\n")

    # Console summary — enough to talk about the result without opening the file.
    if derived.get("out_of_scope"):
        summary = {
            "ok": True, "run_id": run_record["run_id"], "verdict": "Out of scope (Category 3)",
            "category": derived["category"],
            "redirect_message": model.get("redirect_message", ""),
            "validation_warnings": len(model["validation_warnings"]),
            "run_record": out_path,
        }
    else:
        summary = {
            "ok": True, "run_id": run_record["run_id"],
            "verdict": derived["verdict"], "verdict_display": derived["verdict_display"],
            "overall_score": derived["overall"],
            "applicable_controls": f"{derived['applicable_total']}/{derived['control_count']}",
            "category": derived["category"], "performs_review_function": derived["review_fn"],
            "blockers": [b["meta"]["id"] for b in derived["blockers"]],
            "verification_queue": len(derived["needs_verification"]),
            "baseline_controls_pending_verification": len(derived["baseline_pending"]),
            "findings_confidence": derived["findings_confidence"],
            "disputed_controls": derived["disputed_count"],
            "evidence": derived["evidence_stats"],
            "dimension_scores": {d["name"]: d["score"] for d in derived["dims"]},
            "validation_warnings": len(model["validation_warnings"]),
            "run_record": out_path,
            "registry": args.registry,
        }
    if run_record.get("archive_dir"):
        summary["archive_dir"] = run_record["archive_dir"]
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
