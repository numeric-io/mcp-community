#!/usr/bin/env python3
"""
skill-reviewer report renderer.

Reads the run record produced by engine.py and renders:
  - review.md        the written review (auditor-voice, full detail)
  - dashboard.html   a self-contained styled dashboard mirroring the original app

Recomputes NOTHING. Every number comes from the run record. If a number is not
in the run record, it does not appear in a report.

Usage:
  python3 report.py --run-record run-record.json --out review.md --html dashboard.html
  (either --out or --html may be omitted)
"""

import argparse
import html as html_mod
import json

# Numeric brand palette (ported from the app)
C = {
    "bg": "#f4ede0", "panel": "#EFE5D3", "ink": "#1A0859", "purple": "#5827CC",
    "gold": "#A07A2C", "rust": "#C2410C", "cream": "#f4ede0",
}
STATUS_STYLE = {
    "pass":           {"icon": "✓", "label": "Pass",         "bg": C["ink"],   "fg": C["cream"]},
    "partial":        {"icon": "◐", "label": "Partial",      "bg": C["gold"],  "fg": C["cream"]},
    "fail":           {"icon": "✗", "label": "Fail",         "bg": C["rust"],  "fg": C["cream"]},
    "unverifiable":   {"icon": "◯", "label": "Can't verify", "bg": C["panel"], "fg": C["purple"]},
    "not_applicable": {"icon": "—", "label": "N/A",          "bg": C["panel"], "fg": C["gold"]},
}
DIM_ORDER = ["Attribution & Sign-Off", "Evidence Trail & Sourcing",
             "IPE Risk & Evidence Sufficiency", "Auditor-Consumable Output",
             "Reproducibility & Snapshot Discipline", "Materiality & Threshold Awareness"]
CATEGORY_LABEL = {1: "Category 1 — Audit Evidence Producer",
                  2: "Category 2 — Process Enabler",
                  3: "Category 3 — Workflow Orchestrator"}


def esc(s):
    return html_mod.escape(str(s if s is not None else ""))


def verdict_color(derived):
    if derived.get("blockers"):
        return C["rust"]
    if derived.get("overall", 0) >= 85:
        return C["ink"]
    return C["gold"]


def verdict_text(derived):
    """Displayed verdict carries the engine's own doubt (queue, waived controls)."""
    return derived.get("verdict_display") or derived.get("verdict", "")


def reviewer_text(rr):
    rev = rr.get("reviewer") or {}
    if not rev.get("name"):
        return "not recorded"
    src = {"flag": "self-reported via --reviewer", "env": "self-reported via $USER"}.get(
        rev.get("source"), "unknown source")
    rel = rev.get("relation", "unknown")
    return f"{rev['name']} ({src}; relation to reviewed skill: {rel})"


def conf_band(c, conf_policy):
    if c >= conf_policy["HIGH"]:
        return "high"
    if c >= conf_policy["RELY"]:
        return "moderate"
    return "below floor"


def checklist_by_dim(model):
    by_id = {i["id"]: i for i in model["checklist"]}
    return by_id


# =============================== MARKDOWN =====================================

def return_md_checklist(lines, rr, by_id):
    """Continues render_md — split for readability."""
    a = lines.append
    model = rr["model_findings"]
    derived = rr["derived"]
    conf_policy = rr["policy"]["conf"]

    meta_labels = _control_labels()
    for cid, (dim, label) in meta_labels.items():
        it = by_id.get(cid)
        if not it:
            continue
        st = STATUS_STYLE[it["status"]]
        ev = "✓ tied out" if it["evidence_verified"] else (
            "⚠️ quote not found" if "quote_not_found" in it["flags"] else
            ("(absence)" if not it["evidence_provided"] else "—"))
        disputed = " **DISPUTED**" if it.get("disputed") else ""
        note = it["note"].replace("|", "\\|")
        a(f"| {cid} | {label} | {st['icon']} {st['label']}{disputed} | {it['confidence']}% | {ev} | {note} |")
    a("")
    ev_stats = derived["evidence_stats"]
    a(f"Evidence tie-out: {ev_stats['tied']} quote(s) string-matched against the submission; "
      f"{ev_stats['unfound']} cited quote(s) NOT found (confidence capped at "
      f"{conf_policy['CAP_QUOTE_NOT_FOUND']}%).")
    a("")
    a("*Tie-out verifies quotation — that each quote appears in the submission — not that the "
      "quote supports the judgment attached to it. Judgment quality is what the confidence "
      "figures and the verification queue measure.*")
    a("")

    # --- Verification queue ---
    a("## Human verification queue")
    a("")
    nv = derived["needs_verification"]
    if not nv:
        a("Empty — every judgment cleared the reliance floor with verifiable evidence.")
        a("")
    else:
        a(f"**{len(nv)} control judgment(s) the engine refuses to silently rely on.** "
          "These need a person before the score above is trusted"
          + (f" — including {len(derived['baseline_pending'])} BASELINE control(s)."
             if derived["baseline_pending"] else "."))
        a("")
        for v in nv:
            base = " *(baseline)*" if v["baseline"] else ""
            a(f"- **{v['meta']['id']} — {v['meta']['label']}**{base}: " + "; ".join(v["reasons"]))
        a("")

    # --- Queue clearance (recorded by scripts/clear_queue.py) ---
    clearance = rr.get("queue_clearance") or []
    if nv:
        a("### Queue resolution")
        a("")
        if not clearance:
            a("**None recorded.** Until each queued control carries a resolution below (via "
              "`scripts/clear_queue.py`), the human half of this review is undocumented and the "
              "score above should not be relied on.")
            a("")
        else:
            a("| Control | Resolution | Basis | Resolver | When (UTC) |")
            a("|---|---|---|---|---|")
            for e in clearance:
                a(f"| {e['id']} | {e['resolution']} | {e['basis']} | {e['resolver']} | {e['timestamp']} |")
            a("")
            resolved = {e["id"] for e in clearance if e["resolution"] != "still-open"}
            open_ids = sorted({v["meta"]["id"] for v in nv} - resolved)
            a(f"Still open: {', '.join(open_ids) if open_ids else 'none — queue fully resolved.'}")
            a("")

    # --- Remediations ---
    if model.get("top_three_remediations"):
        a("## Top three remediations")
        a("")
        for i, r in enumerate(model["top_three_remediations"], 1):
            a(f"{i}. {r}")
        a("")
    if model.get("rewritten_description"):
        a("## Suggested description rewrite")
        a("")
        a("The SKILL.md description does not surface the audit controls relevant to its "
          "category. Suggested rewrite:")
        a("")
        a(f"> {model['rewritten_description']}")
        a("")
    if model.get("what_to_celebrate"):
        a(f"**Worth celebrating:** {model['what_to_celebrate']}")
        a("")

    # --- Run record ---
    a("---")
    a("")
    a("## Run record")
    a("")
    a("| Field | Value |")
    a("|---|---|")
    a(f"| Run ID | `{rr['run_id']}` |")
    a(f"| Reviewer of record | {reviewer_text(rr)} |")
    a(f"| Timestamp (UTC) | {rr['timestamp']} |")
    a(f"| Engine / rubric version | {rr['engine_version']} / {rr['rubric_version']} |")
    a(f"| Passes | {rr['passes']}{' (consensus)' if rr['passes'] == 2 else ''} |")
    a(f"| File manifest hash | `{rr['file_manifest_hash']}` |")
    a(f"| Corpus archive | {rr.get('archive_dir') or 'not archived — originals must be retained for re-performance'} |")
    a(f"| Forced category (pre-model) | {rr['forced_category'] or '—'} |")
    a(f"| Overrides (post-model) | {json.dumps(rr['overrides']) if rr['overrides'] else '—'} |")
    a("")
    a("### Sign-off")
    a("")
    a(f"- **Preparer of record (ran the review):** {reviewer_text(rr)}")
    a("- **Countersign (reviewed this review):** ______________________  Date: __________")
    a("")
    a("**Files reviewed:**")
    a("")
    for f in rr["files"]:
        a(f"- `{f['path']}` — {f['size']} chars, hash `{f['hash']}`")
    a("")
    if rr["validation_warnings"]:
        a("**Validation warnings** (the engine corrected or rejected these on intake):")
        a("")
        for w in rr["validation_warnings"]:
            a(f"- {w}")
        a("")
    a("*Scores, blockers, and the verdict are computed deterministically by engine.py from "
      "the model's control-by-control findings. Same findings in, same review out.*")
    a("")
    a("*Re-performance boundary: the scoring is fully re-performable from the findings embedded "
      "in this run record, and every evidence quote can be re-tied against the archived corpus. "
      "The fact-finding pass itself is model judgment — evidenced, not re-performable. "
      "Compensating controls: consensus mode (recorded as passes=2), the 60% reliance floor, "
      "and the human verification queue.*")


def _control_labels():
    """id -> (dimension, label), in canonical order."""
    return {c["id"]: (c["dimension"], c["label"]) for c in _CHECKLIST}


_CHECKLIST = [
    {"id": "E1", "dimension": "Evidence Trail & Sourcing", "label": "Captures the period being operated on explicitly"},
    {"id": "E2", "dimension": "Evidence Trail & Sourcing", "label": "Timestamps when data was pulled from source systems"},
    {"id": "E3", "dimension": "Evidence Trail & Sourcing", "label": "Cites source IDs (transaction IDs, task GIDs, JE numbers, URLs)"},
    {"id": "A1", "dimension": "Attribution & Sign-Off", "label": "Identifies the preparer"},
    {"id": "A2", "dimension": "Attribution & Sign-Off", "label": "Surfaces or requires reviewer before final state"},
    {"id": "A3", "dimension": "Attribution & Sign-Off", "label": "Gates destructive or write-back actions behind confirmation"},
    {"id": "P1", "dimension": "IPE Risk & Evidence Sufficiency", "label": "Workflow pattern (A/B/C/D) is identifiable and evidence design matches it"},
    {"id": "P2", "dimension": "IPE Risk & Evidence Sufficiency", "label": "Validates completeness & accuracy of input data before operating on it"},
    {"id": "P3", "dimension": "IPE Risk & Evidence Sufficiency", "label": "Documents judgments/transformations and requires user sign-off on them"},
    {"id": "R1", "dimension": "Reproducibility & Snapshot Discipline", "label": "Output is run-stamped (timestamp + run ID)"},
    {"id": "R2", "dimension": "Reproducibility & Snapshot Discipline", "label": "Locks source data snapshot rather than re-pulling live state"},
    {"id": "R3", "dimension": "Reproducibility & Snapshot Discipline", "label": "Excluded items surfaced explicitly, not silently dropped"},
    {"id": "M1", "dimension": "Materiality & Threshold Awareness", "label": "Applies a documented, defensible materiality threshold (basis stated)"},
    {"id": "M2", "dimension": "Materiality & Threshold Awareness", "label": "Flags items above threshold for human review"},
    {"id": "M3", "dimension": "Materiality & Threshold Awareness", "label": "Surfaces items below threshold (not hidden); aggregates where relevant"},
    {"id": "O1", "dimension": "Auditor-Consumable Output", "label": "Output is an auditor-consumable artifact (xlsx/PDF/workpaper, not just chat)"},
    {"id": "O2", "dimension": "Auditor-Consumable Output", "label": "Output includes sign-off block / run metadata footer"},
    {"id": "O3", "dimension": "Auditor-Consumable Output", "label": "Computed numbers shown as correct, traceable formulas, not hard-coded values"},
]


# ================================= HTML =======================================

def render_html(rr):
    model = rr["model_findings"]
    derived = rr["derived"]
    cls = model["classification"]
    conf_policy = rr["policy"]["conf"]
    vc = verdict_color(derived) if not derived.get("out_of_scope") else C["gold"]

    def chip(status, disputed=False):
        st = STATUS_STYLE[status]
        d = ' <span class="disputed">DISPUTED</span>' if disputed else ""
        return (f'<span class="chip" style="background:{st["bg"]};color:{st["fg"]}">'
                f'{st["icon"]} {st["label"]}</span>{d}')

    head = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Audit-Readiness Review — {esc(rr['primary'])}</title>
<style>
  :root {{ --ink:{C['ink']}; --purple:{C['purple']}; --gold:{C['gold']}; --rust:{C['rust']};
           --bg:{C['bg']}; --panel:{C['panel']}; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font-family:'Helvetica Neue',Arial,sans-serif; line-height:1.5; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:32px 24px 64px; }}
  h1 {{ font-size:26px; letter-spacing:-0.5px; margin:0 0 4px; }}
  h2 {{ font-size:15px; text-transform:uppercase; letter-spacing:1.5px; color:var(--purple);
        margin:40px 0 12px; border-bottom:2px solid var(--ink); padding-bottom:6px; }}
  .meta {{ font-size:12px; color:var(--purple); margin-bottom:24px; }}
  .meta code {{ background:var(--panel); padding:1px 5px; border-radius:3px; }}
  .scorecard {{ display:flex; gap:16px; flex-wrap:wrap; align-items:stretch; margin:20px 0; }}
  .verdict {{ flex:2 1 340px; border:2px solid var(--ink); background:#fff8;
              padding:20px 24px; border-left:10px solid {vc}; }}
  .verdict .v {{ font-size:24px; font-weight:700; color:{vc}; }}
  .bignum {{ flex:1 1 160px; border:2px solid var(--ink); background:var(--ink); color:var(--bg);
             padding:20px 24px; text-align:center; }}
  .bignum .n {{ font-size:44px; font-weight:700; line-height:1; }}
  .bignum .l {{ font-size:11px; text-transform:uppercase; letter-spacing:1px; opacity:.8; }}
  .badges {{ margin:10px 0 0; font-size:13px; }}
  .badge {{ display:inline-block; background:var(--panel); border:1px solid var(--ink);
            padding:2px 10px; border-radius:99px; margin:2px 6px 2px 0; font-size:12px; }}
  .headline {{ font-size:17px; font-style:italic; border-left:4px solid var(--gold);
               padding:8px 16px; margin:18px 0; background:#fff6; }}
  .blocker {{ border:2px solid var(--rust); background:#C2410C14; padding:16px 20px; margin:16px 0; }}
  .blocker h3 {{ margin:0 0 8px; color:var(--rust); font-size:15px; text-transform:uppercase; letter-spacing:1px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; background:#fff6; }}
  th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:1px;
        color:var(--purple); border-bottom:2px solid var(--ink); padding:8px; }}
  td {{ border-bottom:1px solid #1A085922; padding:8px; vertical-align:top; }}
  .chip {{ display:inline-block; padding:1px 8px; border-radius:99px; font-size:11px;
           font-weight:600; white-space:nowrap; }}
  .disputed {{ color:var(--rust); font-weight:700; font-size:10px; letter-spacing:1px; }}
  .dimbar {{ height:8px; background:#1A085922; border-radius:99px; overflow:hidden; margin-top:4px; }}
  .dimbar i {{ display:block; height:100%; background:var(--ink); }}
  .drag i {{ background:var(--rust); }}
  .dimcard {{ border:1.5px solid var(--ink); background:#fff6; padding:14px 18px; margin:10px 0; }}
  .dimcard h3 {{ margin:0; font-size:14px; display:flex; justify-content:space-between; }}
  .dimcard .blurb {{ font-size:12px; color:var(--purple); margin:4px 0 8px; }}
  .kv b {{ color:var(--ink); }} .kv {{ font-size:13px; margin:6px 0; }}
  .queue {{ border:2px solid var(--gold); background:#A07A2C10; padding:16px 20px; }}
  .queue li {{ margin:6px 0; font-size:13px; }}
  .conf-high {{ color:var(--ink); font-weight:600; }}
  .conf-moderate {{ color:var(--gold); font-weight:600; }}
  .conf-below {{ color:var(--rust); font-weight:600; }}
  .evtag {{ font-size:11px; }}
  .runrec {{ font-size:12px; background:var(--panel); border:1.5px solid var(--ink); padding:16px 20px; }}
  .runrec code {{ background:#fff8; padding:1px 4px; }}
  .warn {{ color:var(--gold); }}
  footer {{ margin-top:40px; font-size:11px; color:var(--purple); border-top:1px solid var(--ink); padding-top:12px; }}
  @media print {{ body {{ background:#fff; }} }}
</style></head><body><div class="wrap">
<h1>Audit-Readiness Review</h1>
<div class="meta">Submission <code>{esc(rr['primary'])}</code> · {len(rr['files'])} file(s) ·
Run <code>{esc(rr['run_id'])}</code> · {esc(rr['timestamp'])} ·
Rubric v{esc(rr['rubric_version'])} · Engine v{esc(rr['engine_version'])} ·
{rr['passes']} pass{'es (consensus)' if rr['passes'] == 2 else ''} ·
Reviewer of record: {esc(reviewer_text(rr))}</div>"""

    if derived.get("out_of_scope"):
        body = f"""
<div class="scorecard"><div class="verdict" style="border-left-color:{C['gold']}">
  <div class="v" style="color:{C['gold']}">Out of scope for this rubric</div>
  <div class="badges"><span class="badge">{esc(CATEGORY_LABEL.get(derived['category'], 'Category 3'))}</span>
  <span class="badge">confidence {cls['confidence']}%</span></div>
  <p>{esc(cls.get('rationale', ''))}</p>
  <p>{esc(model.get('redirect_message', ''))}</p>
  {f"<p><b>Worth celebrating:</b> {esc(model['what_to_celebrate'])}</p>" if model.get('what_to_celebrate') else ""}
  <p style="font-size:12px;color:{C['purple']}">Believe this is wrong? Re-run the engine with
  <code>--override-category 1</code> — findings rescore instantly, no second model pass.</p>
</div></div>"""
        return head + body + _html_runrec(rr) + "</div></body></html>"

    review_badge = (f'<span class="badge">performs review/control function '
                    f'({cls["review_function_confidence"]}%)</span>' if derived["review_fn"] else "")
    ipe = model.get("ipe") or {}
    ipe_badge = (f'<span class="badge">IPE pattern {esc(ipe["pattern"])} ({ipe["confidence"]}%)</span>'
                 if ipe.get("pattern") else "")
    ov_badge = (f'<span class="badge" style="border-color:{C["rust"]}">overrides: '
                f'{esc(json.dumps(rr["overrides"]))}</span>' if rr["overrides"] else "")
    applicable = derived.get("applicable_total")
    total = derived.get("control_count", 18)
    applicable_badge = ""
    if applicable is not None:
        waived_style = ' style="border-color:' + C["rust"] + '"' if applicable < total else ""
        applicable_badge = ('<span class="badge"' + waived_style + '>'
                            + f"scored on {applicable}/{total} applicable controls</span>")
    body = [f"""
<div class="scorecard">
  <div class="verdict">
    <div class="v">{esc(verdict_text(derived))}</div>
    <div class="badges">
      <span class="badge">{esc(CATEGORY_LABEL[derived['category']])} ({cls['confidence']}%)</span>
      {review_badge}{ipe_badge}{ov_badge}
      <span class="badge">findings confidence {derived['findings_confidence']}%</span>
      {applicable_badge}
    </div>
  </div>
  <div class="bignum"><div class="n">{derived['overall']}</div>
  <div class="l">overall / 100{f" · {applicable}/{total} applicable" if applicable is not None and applicable < total else ""}</div></div>
</div>"""]
    if model.get("headline"):
        body.append(f'<div class="headline">{esc(model["headline"])}</div>')

    if derived["blockers"]:
        items = "".join(f"<li><b>{esc(b['meta']['id'])} — {esc(b['meta']['label'])}</b>: "
                        f"{esc(b['item']['note'])}</li>" for b in derived["blockers"])
        body.append(f"""<div class="blocker"><h3>Contains blocker</h3>
<p>An applicable <b>baseline control failed</b>. Whatever the score says, do not run this skill
against real financial data until these are fixed:</p><ul>{items}</ul></div>""")

    if rr["passes"] == 2:
        cons = rr.get("consensus") or {}
        d_ids = cons.get("disputed_ids") or []
        if d_ids or cons.get("classification_disputed"):
            msg = []
            if d_ids:
                msg.append(f"controls <b>{', '.join(map(esc, d_ids))}</b> disagreed between passes — "
                           f"conservative status taken, confidence capped at {conf_policy['CAP_DISPUTED']}%")
            if cons.get("classification_disputed"):
                msg.append("classification disputed — resolved conservatively")
            body.append(f'<div class="blocker" style="border-color:{C["gold"]};background:#A07A2C10">'
                        f'<h3 style="color:{C["gold"]}">Consensus notes</h3><p>{"; ".join(msg)}.</p></div>')

    # Dimensions
    body.append("<h2>Dimension scores</h2>")
    dims = {d["name"]: d for d in derived["dims"]}
    dim_narr = {d["name"]: d for d in model["dimensions"]}
    for name in DIM_ORDER:
        d = dims[name]
        n = dim_narr.get(name, {})
        drag = any(x["name"] == name for x in derived["score_drag"])
        score_txt = f"{d['score']}/10" if d["score"] is not None else "n/a"
        pct = (d["score"] or 0) * 10
        mat = (f'<div class="kv"><b>Applicable materiality concepts:</b> '
               f'{esc(", ".join(n["materiality_concepts"]))}</div>'
               if n.get("materiality_concepts") else "")
        body.append(f"""<div class="dimcard">
<h3><span>{esc(name)} <span style="font-weight:400;color:{C['purple']};font-size:12px">· weight {d['weight']}%</span></span>
<span style="color:{C['rust'] if drag else C['ink']}">{score_txt}{' ⚠︎ drag' if drag else ''}</span></h3>
<div class="dimbar{' drag' if drag else ''}"><i style="width:{pct}%"></i></div>
<div class="blurb">{esc(d['blurb'])}</div>{mat}
{f'<div class="kv"><b>What works:</b> {esc(n["what_works"])}</div>' if n.get("what_works") else ""}
{f'<div class="kv"><b>What to fix:</b> {esc(n["what_to_fix"])}</div>' if n.get("what_to_fix") else ""}
{f'<div class="kv"><b>Example fix:</b> {esc(n["example_fix"])}</div>' if n.get("example_fix") else ""}
</div>""")

    # Checklist
    body.append("<h2>The 18 controls</h2><table><tr><th>#</th><th>Control</th><th>Status</th>"
                "<th>Conf.</th><th>Evidence</th><th>Note</th></tr>")
    by_id = {i["id"]: i for i in model["checklist"]}
    for c in _CHECKLIST:
        it = by_id.get(c["id"])
        if not it:
            continue
        band = conf_band(it["confidence"], conf_policy)
        band_cls = {"high": "conf-high", "moderate": "conf-moderate", "below floor": "conf-below"}[band]
        if it["evidence_verified"]:
            ev = f'<span class="evtag" style="color:{C["ink"]}">✓ tied out</span>'
            if it["evidence"]:
                ev += f'<br><span class="evtag" style="color:{C["purple"]}">“{esc(it["evidence"][:120])}”</span>'
        elif "quote_not_found" in it["flags"]:
            ev = f'<span class="evtag" style="color:{C["rust"]}">⚠ quote not found</span>'
        elif not it["evidence_provided"]:
            ev = f'<span class="evtag" style="color:{C["gold"]}">judged by absence</span>'
        else:
            ev = "—"
        body.append(f"<tr><td><b>{c['id']}</b></td><td>{esc(c['label'])}</td>"
                    f"<td>{chip(it['status'], it.get('disputed'))}</td>"
                    f'<td class="{band_cls}">{it["confidence"]}%</td>'
                    f"<td>{ev}</td><td>{esc(it['note'])}</td></tr>")
    ev_stats = derived["evidence_stats"]
    body.append(f"</table><p style='font-size:12px;color:{C['purple']}'>Evidence tie-out: "
                f"{ev_stats['tied']} quote(s) string-matched against the submission; "
                f"{ev_stats['unfound']} not found (confidence capped at "
                f"{conf_policy['CAP_QUOTE_NOT_FOUND']}%). <i>Tie-out verifies quotation, not "
                f"judgment — that each quote appears in the submission, not that it supports the "
                f"status attached to it.</i></p>")

    # Verification queue
    body.append("<h2>Human verification queue</h2>")
    nv = derived["needs_verification"]
    if not nv:
        body.append('<p>Empty — every judgment cleared the reliance floor with verifiable evidence.</p>')
    else:
        items = "".join(
            f"<li><b>{esc(v['meta']['id'])} — {esc(v['meta']['label'])}</b>"
            f"{' <span class=&quot;disputed&quot;>BASELINE</span>' if v['baseline'] else ''}: "
            + esc("; ".join(v["reasons"])) + "</li>" for v in nv)
        body.append(f"""<div class="queue"><p><b>{len(nv)} judgment(s) the engine refuses to silently
rely on</b> — a person needs to check these before trusting the score
{f"(including {len(derived['baseline_pending'])} baseline control(s))" if derived['baseline_pending'] else ""}:</p>
<ul>{items}</ul></div>""")
        clearance = rr.get("queue_clearance") or []
        if not clearance:
            body.append(f'<p style="font-size:12px;color:{C["rust"]}"><b>No queue resolution '
                        'recorded.</b> Record who verified each item with '
                        '<code>scripts/clear_queue.py</code> — until then the human half of this '
                        "review is undocumented.</p>")
        else:
            rows = "".join(f"<tr><td><b>{esc(e['id'])}</b></td><td>{esc(e['resolution'])}</td>"
                           f"<td>{esc(e['basis'])}</td><td>{esc(e['resolver'])}</td>"
                           f"<td>{esc(e['timestamp'])}</td></tr>" for e in clearance)
            resolved = {e["id"] for e in clearance if e["resolution"] != "still-open"}
            open_ids = sorted({v["meta"]["id"] for v in nv} - resolved)
            still = ", ".join(open_ids) if open_ids else "none — queue fully resolved"
            body.append("<h2>Queue resolution</h2><table><tr><th>Control</th><th>Resolution</th>"
                        "<th>Basis</th><th>Resolver</th><th>When (UTC)</th></tr>" + rows +
                        f"</table><p style='font-size:12px'>Still open: {esc(still)}.</p>")

    # Remediations + celebrate
    if model.get("top_three_remediations"):
        body.append("<h2>Top three remediations</h2><ol>" +
                    "".join(f"<li>{esc(r)}</li>" for r in model["top_three_remediations"]) + "</ol>")
    if model.get("rewritten_description"):
        body.append("<h2>Suggested description rewrite</h2>"
                    f"<p style='font-style:italic'>{esc(model['rewritten_description'])}</p>")
    if model.get("what_to_celebrate"):
        body.append(f"<p><b>Worth celebrating:</b> {esc(model['what_to_celebrate'])}</p>")

    return head + "".join(body) + _html_runrec(rr) + "</div></body></html>"


def _html_runrec(rr):
    files = "".join(f"<li><code>{esc(f['path'])}</code> — {f['size']} chars, hash "
                    f"<code>{esc(f['hash'])}</code></li>" for f in rr["files"])
    warns = ("".join(f'<li class="warn">{esc(w)}</li>' for w in rr["validation_warnings"])
             or "<li>none</li>")
    archive = rr.get("archive_dir") or "not archived — originals must be retained for re-performance"
    return f"""
<h2>Run record</h2>
<div class="runrec">
<p>Run <code>{esc(rr['run_id'])}</code> · {esc(rr['timestamp'])} · engine v{esc(rr['engine_version'])} ·
rubric v{esc(rr['rubric_version'])} · {rr['passes']} pass(es) · manifest hash
<code>{esc(rr['file_manifest_hash'])}</code> · forced category: {esc(rr['forced_category'] or '—')} ·
overrides: <code>{esc(json.dumps(rr['overrides']) if rr['overrides'] else '—')}</code></p>
<p><b>Reviewer of record:</b> {esc(reviewer_text(rr))}</p>
<p><b>Corpus archive:</b> {esc(archive)}</p>
<p><b>Sign-off</b> — Preparer of record: {esc(reviewer_text(rr))} ·
Countersign (reviewed this review): ______________________ Date: __________</p>
<p><b>Files reviewed:</b></p><ul>{files}</ul>
<p><b>Validation warnings</b> (corrected or rejected on intake):</p><ul>{warns}</ul>
</div>
<footer>Scores, blockers, and the verdict are computed deterministically by engine.py from the
model's control-by-control findings — the model never grades its own findings. Same findings in,
same review out.<br><br>Re-performance boundary: the scoring is fully re-performable from the
findings embedded in the run record, and every evidence quote can be re-tied against the archived
corpus. The fact-finding pass itself is model judgment — evidenced, not re-performable;
compensating controls are consensus mode, the 60% reliance floor, and the human verification
queue.</footer>"""


def main():
    import sys
    ap = argparse.ArgumentParser(description="Render review.md and dashboard.html from a run record.")
    ap.add_argument("--run-record", required=True)
    ap.add_argument("--out", help="Markdown report output path "
                    "(default: review-{run_id}.md — stamped so re-runs never silently overwrite)")
    ap.add_argument("--html", help="HTML dashboard output path (default: dashboard-{run_id}.html)")
    args = ap.parse_args()

    try:
        with open(args.run_record, "r", encoding="utf-8") as f:
            rr = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: cannot read run record {args.run_record} ({e}) — pass the "
                 "run-record-<id>.json path printed in the engine summary.")
    if not all(k in rr for k in ("run_id", "derived", "model_findings", "policy")):
        sys.exit(f"ERROR: {args.run_record} is not a run record produced by engine.py — pass the "
                 "run-record-<id>.json path printed in the engine summary.")

    out_path = args.out or f"review-{rr['run_id']}.md"
    html_path = args.html or f"dashboard-{rr['run_id']}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(render_md(rr))
    print(f"wrote {out_path}")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_html(rr))
    print(f"wrote {html_path}")


def render_md(rr):
    """Render the markdown review from a run record."""
    model = rr["model_findings"]
    derived = rr["derived"]
    cls = model["classification"]
    lines = []
    a = lines.append

    a("# Audit-Readiness Review")
    a("")
    a(f"**Submission:** `{rr['primary']}` ({len(rr['files'])} file{'s' if len(rr['files']) != 1 else ''})  ")
    a(f"**Run ID:** `{rr['run_id']}` · **Timestamp:** {rr['timestamp']} · "
      f"**Rubric v{rr['rubric_version']}** · **Engine v{rr['engine_version']}** · "
      f"**Passes:** {rr['passes']}{' (consensus)' if rr['passes'] == 2 else ''}")
    a(f"**Reviewer of record:** {reviewer_text(rr)}")
    a("")

    if derived.get("out_of_scope"):
        a("## Verdict: Out of scope for this rubric")
        a("")
        a(f"**{CATEGORY_LABEL.get(derived['category'], 'Category 3')}** (confidence {cls['confidence']}%)")
        a("")
        if cls.get("rationale"):
            a(f"> {cls['rationale']}")
            a("")
        if model.get("redirect_message"):
            a(model["redirect_message"])
            a("")
        if model.get("what_to_celebrate"):
            a(f"**Worth celebrating:** {model['what_to_celebrate']}")
            a("")
        a("*This rubric grades skills that produce audit evidence. If you believe this "
          "classification is wrong, re-run the engine with `--override-category 1` (or 2) — "
          "if the model returned full findings they rescore instantly, with no second model pass.*")
        return "\n".join(lines) + "\n"

    a(f"## Verdict: {verdict_text(derived)} — {derived['overall']}/100")
    a("")
    if derived.get("applicable_total") is not None:
        a(f"*Score computed over {derived['applicable_total']} of "
          f"{derived.get('control_count', 18)} applicable controls"
          + (" — N/A controls are excluded from the denominator, so fewer applicable controls "
             "mean each remaining judgment carries more weight.*"
             if derived["applicable_total"] < derived.get("control_count", 18) else ".*"))
        a("")
    a(f"**{CATEGORY_LABEL[derived['category']]}** (confidence {cls['confidence']}%)"
      + (f" · **performs a review/control function** (confidence {cls['review_function_confidence']}%)"
         if derived["review_fn"] else ""))
    ipe = model.get("ipe") or {}
    if ipe.get("pattern"):
        a(f"**IPE workflow pattern {ipe['pattern']}** (confidence {ipe['confidence']}%)"
          + (f" — {ipe['rationale']}" if ipe.get("rationale") else ""))
    a(f"**Findings confidence:** {derived['findings_confidence']}% (weighted mean of per-control confidence)")
    if rr["overrides"]:
        a(f"**User overrides applied:** `{json.dumps(rr['overrides'])}` — findings unchanged, scores recomputed.")
    a("")
    if model.get("headline"):
        a(f"> **{model['headline']}**")
        a("")

    if derived["blockers"]:
        a("## 🚫 Blockers")
        a("")
        a("An applicable **baseline control failed**. Whatever the numeric score says, this "
          "skill should not run against real financial data until these are fixed:")
        a("")
        for b in derived["blockers"]:
            a(f"- **{b['meta']['id']} — {b['meta']['label']}**: {b['item']['note']}")
        a("")

    consensus = rr.get("consensus") or {}
    if rr["passes"] == 2:
        d_ids = consensus.get("disputed_ids") or []
        a("## Consensus")
        a("")
        if d_ids or consensus.get("classification_disputed"):
            bits = []
            if d_ids:
                bits.append(f"controls {', '.join(d_ids)} were judged differently by the two passes — "
                            "the conservative status was taken and confidence capped at 50%")
            if consensus.get("classification_disputed"):
                bits.append("the passes disagreed on classification — resolved conservatively")
            a("Two independent passes were reconciled. " + "; ".join(bits) + ".")
        else:
            a("Two independent passes agreed on every control status. Confidences were averaged.")
        a("")

    a("## Dimension scores")
    a("")
    a("| Dimension | Weight | Score | Controls |")
    a("|---|---|---|---|")
    dims = {d["name"]: d for d in derived["dims"]}
    for name in DIM_ORDER:
        d = dims[name]
        score = f"{d['score']}/10" if d["score"] is not None else "n/a (all controls N/A)"
        cts = d["counts"]
        parts = [f"{v} {k.replace('_', ' ')}" for k, v in cts.items() if v]
        drag = " ⚠️" if any(x["name"] == name for x in derived["score_drag"]) else ""
        a(f"| {name}{drag} | {d['weight']}% | {score} | {', '.join(parts)} |")
    a("")
    if derived["score_drag"]:
        a("⚠️ = scoring below 6/10 and dragging the overall score.")
        a("")

    dim_narrative = {d["name"]: d for d in model["dimensions"]}
    for name in DIM_ORDER:
        n = dim_narrative.get(name, {})
        d = dims[name]
        score = f"{d['score']}/10" if d["score"] is not None else "n/a"
        a(f"### {name} — {score}")
        a("")
        if n.get("materiality_concepts"):
            a(f"*Applicable materiality concepts: {', '.join(n['materiality_concepts'])}*")
            a("")
        if n.get("what_works"):
            a(f"**What works:** {n['what_works']}")
            a("")
        if n.get("what_to_fix"):
            a(f"**What to fix:** {n['what_to_fix']}")
            a("")
        if n.get("example_fix"):
            a(f"**Example fix:** {n['example_fix']}")
            a("")

    a("## The 18 controls")
    a("")
    a("| # | Control | Status | Conf. | Evidence | Note |")
    a("|---|---|---|---|---|---|")
    by_id = {i["id"]: i for i in model["checklist"]}
    return_md_checklist(lines, rr, by_id)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
