#!/usr/bin/env python3
"""costkit: measurement, checks, scoring and reporting for the skill-cost-optimizer skill.
Run it; there is no need to read it. Standard library only (Python 3.9+; openpyxl only for .xlsx outputs).

  costkit.py init WORK --skill SKILL --request TEXT --outcome-unit TEXT --mode assess|optimize [--account A.json] [--env E] [--force]
  costkit.py static SKILL [--save WORK]                         checks on the skill's files (no run needed)
  costkit.py env                                                whether this chat has session records, so cost can be measured
  costkit.py turns [--skill NAME] [--transcript F]             the person's messages in this chat, and a suggested run window
  costkit.py assess WORK --skill SKILL --outcomes N --start S [--end E] [--transcript F]   measure and record a real run
  costkit.py measure (--agent-id ID | --transcript F | --sdk-result F) [--save WORK --round R]   measure a test run
  costkit.py compare-outputs OUT_A OUT_B [--save WORK --round R]  files and numbers in two output folders
  costkit.py record WORK --round R --skill SKILL --outcomes N [--output-check not_compared --reason TEXT]
                    [--reviewer-edits N] [--tested-change model|effort]
  costkit.py decide WORK                                        keep, revert or stop after the latest test round
  costkit.py ceiling WORK [--budget-usd X]                      write the cost ceiling into the candidate copy
  costkit.py check WORK --skill SKILL --outcomes N (--agent-id ID | --transcript F | --sdk-result F)
  costkit.py mark WORK --id ID [ID ...] --status STATUS [--round R]
  costkit.py judge WORK --id ID --decision TEXT --note TEXT
  costkit.py review WORK --file ITEMS.json                     save the qualitative review (reference/review.md); replaces the last one
  costkit.py report WORK                                        write WORK/report.html

Rounds: real-<date> (assess), baseline, round2, round3 (optimize), check-<date> (quarterly test check).
Costs are list prices from ../prices.json, applied per request. Exit codes: 0 success, 1 usage or input error,
3 a check failed or decide reverted.
"""
import argparse, datetime, glob, hashlib, html, json, math, os, re, shutil, sys

# Price ratios relative to one uncached input token of the same model. Output, cache writes and the default cache
# read are the same for current models; the cache-read ratio differs by model (pricing page), so it is chosen from
# the model name. Override in WORK/config.json ("weights", "cache_read_by_model").
DEFAULT_WEIGHTS = {"input": 1.0, "cache_write_5m": 1.25, "cache_write_1h": 2.0, "cache_read": 0.1, "output": 5.0}
CACHE_READ_BY_MODEL = [{"match": "fable", "ratio": 0.025}, {"match": r"(opus|sonnet)-5-5", "ratio": 0.05}]
LARGE_RESULT_CHARS = 20000      # about 5,000 tokens; a result this size is resent on every later request
CACHE_TTL_SECONDS = 300         # the 5-minute cache; a longer gap between requests usually means a cache miss
REPEAT_CALLS_FOR_BATCH = 5      # this many calls to one tool with the same parameters and different values
GENERIC_TOOLS = {"Read", "Bash", "Grep", "Glob", "Edit", "Write", "ToolSearch", "TaskCreate", "TaskUpdate", "Agent", "Task"}
MIN_SAVING = 0.10               # a round that saves less than this against the best run stops the loop
MAX_RUNS = 3                    # baseline plus two change rounds; each run costs a full run of the target
CEILING_FACTOR = 1.5            # ceiling = baseline tool calls (and requests) x this factor, rounded up
RECHECK_DAYS = 91
ROUND_RE = re.compile(r"^(baseline|round\d+|check-\d{4}-\d{2}-\d{2}|real-\d{4}-\d{2}-\d{2}(-\d+)?)$")
LEVERS = ("batching", "caching", "effort", "model_per_step")
VERDICTS = ["failed", "unnecessary", "misplaced", "excessive", "appropriate"]   # most serious first; the first that fits wins
STATUSES = ["approved", "applied", "not applied", "needs API access", "declined by the person"]


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def load_json(path, default=None):
    if not os.path.isfile(path):
        if default is not None:
            return default
        die(f"not found: {path}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1)


def tok(chars):
    return max(0, round(chars / 4))


def stable_id(cid, key):
    """The same finding keeps the same id when the checks run again (the key is text, not a line number)."""
    return f"{cid}-{hashlib.sha1(key.encode()).hexdigest()[:6]}"


def read(path):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def cfg_of(w):
    return load_json(os.path.join(w, "config.json"))


def candidate_of(w, cfg):
    return os.path.join(w, "candidate", os.path.basename(cfg["skill"]))


# ---------------------------------------------------------------- init
def detect_env():
    """cowork or claude-code, from the entrypoint the app writes into this chat's session file."""
    files = [f for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))]
    if not files:
        return "chat" if os.path.isdir("/mnt/skills") else "claude-code"   # the claude.ai sandbox keeps skills there
    for r in read_rows(max(files, key=os.path.getmtime))[:50]:
        if r.get("entrypoint"):
            return "cowork" if "cowork" in r["entrypoint"] or r["entrypoint"] == "local-agent" else "claude-code"
    return "claude-code"


def cmd_env(a):
    files = [f for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")) if "/subagents/" not in f]
    if files:
        print(f"session records found; environment {detect_env()}; cost can be measured here")
    else:
        print(f"no session records; environment {detect_env()}. Cost cannot be measured and changes cannot be tested here: "
              "only the file checks and the qualitative review work.")


def check_steps(path):
    try:
        steps = load_json(path).get("steps")
    except (ValueError, AttributeError) as ex:
        die(f"account file {path} is not valid JSON with a steps list: {ex}")
    if not isinstance(steps, list):
        die(f"account file {path} has no steps list")
    for i, st in enumerate(steps):
        if not isinstance(st, dict) or "step" not in st or "match" not in st:
            die(f"account file {path}: step {i + 1} needs \"step\" and \"match\"")
        try:
            re.compile(st["match"])
        except re.error as ex:
            die(f"account file {path}: step {st['step']!r} has a bad pattern: {ex}")


def cmd_init(a):
    w, skill = os.path.abspath(a.work), os.path.abspath(a.skill)
    if not os.path.isfile(os.path.join(skill, "SKILL.md")):
        die(f"{skill} has no SKILL.md")
    if w == skill or w.startswith(skill + os.sep):
        die("the work folder must be beside the skill, not the skill folder or inside it")
    old = load_json(os.path.join(w, "config.json"), {}) if os.path.isfile(os.path.join(w, "config.json")) else None
    if old and not a.force:
        die(f"{w} is already set up. Reuse it as it is; pass --force to change the mode, request or account file, which "
            "archives this session's working files under sessions/ (metrics.jsonl and the candidate copy are kept)")
    acct = os.path.abspath(a.account) if a.account else (old or {}).get("account")
    if acct:
        if not os.path.isfile(acct):
            die(f"account file not found: {acct}")
        check_steps(acct)
    cand = os.path.join(w, "candidate", os.path.basename(skill))
    if old:   # archive the old session so its comparisons, marks, judgments and snapshots cannot leak into the new one
        arch = os.path.join(w, "sessions", datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        os.makedirs(arch)
        for x in ("runs", "kept", "applied.json", "judgments.json", "ceiling.json", "findings_static.json", "findings_run.json",
                  "report.html", "config.json", "review.json") + (("candidate",) if a.fresh_candidate else ()):
            if os.path.exists(os.path.join(w, x)):
                shutil.move(os.path.join(w, x), os.path.join(arch, x))
        print(f"archived the previous session's working files to {arch}")
    save_json(os.path.join(w, "config.json"), {"skill": skill, "request": a.request, "outcome_unit": a.outcome_unit,
                                               "env": a.env or detect_env(), "mode": a.mode, "account": acct, "weights": DEFAULT_WEIGHTS,
                                               "cache_read_by_model": CACHE_READ_BY_MODEL, "created": str(datetime.date.today())})
    if not os.path.isdir(cand):
        shutil.copytree(skill, cand, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    print(f"work folder {w}\ncandidate copy {cand}\nenvironment {a.env or detect_env()}; account file {acct or 'none (costs grouped by tool name)'}")


# ---------------------------------------------------------------- static checks
REC = {
    "S1": "Move detail that only some runs need out of SKILL.md into a reference file with a when-to-read cue.",
    "S2": "Shorten the description to what the skill does and when to use it; it is loaded in every session.",
    "S3": "Link the file from SKILL.md with a when-to-read cue, or remove it from the skill.",
    "S4": "Add a contents list at the top so the model can read one section instead of the whole file.",
    "S5": "Move development material (tests, fixtures, old versions, READMEs) out of the runtime skill.",
    "S6": "Keep this text in one place and point to it from the others.",
    "S7": "Move this code into a script the skill runs; a run script's code never enters the context.",
    "S8": "Move this table into a data file that a script reads and filters.",
    "S9": "Tell the model to run the script, not to read it; only a run script's output enters the context.",
    "S10": "Add a when-to-read cue to the line that links this file, so it is read only when a step needs it.",
    "S11": "Add a cost ceiling (costkit ceiling) so a run that goes over its limit stops and reports.",
    "S12": "Move this calculation into a script; the model should only write the sentences around the result.",
    "S13": "In Claude Code only, set effort (or model) in the frontmatter; these keys make the upload fail on claude.ai and the Skills API.",
}


def frontmatter(text):
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text
    fm, key = {}, None
    for ln in lines[1:end]:
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", ln)
        if m:
            key = m.group(1)
            fm[key] = m.group(2).strip().strip("\"'")
        elif key and ln.startswith((" ", "\t")):
            fm[key] = (fm[key] + " " + ln.strip()).strip()
    return fm, "\n".join(lines[end + 1:])


def skill_files(d):
    out = []
    for root, dirs, names in os.walk(d):
        dirs[:] = [x for x in dirs if x not in (".git", "__pycache__", "node_modules")]
        out += [os.path.relpath(os.path.join(root, n), d) for n in names if not n.endswith(".pyc")]
    return sorted(out)


def prose_lines(text):
    """Lines with fenced code blocks blanked (numbering kept), plus the blocks as (start line, length, first line)."""
    lines, blocks, inside, start, out = text.split("\n"), [], False, 0, []
    for i, ln in enumerate(lines, 1):
        if ln.strip().startswith("```"):
            if inside:
                blocks.append((start, i - start - 1, lines[start] if start < len(lines) else ""))
            else:
                start = i
            inside = not inside
            out.append("")
            continue
        out.append("" if inside else ln)
    return out, blocks


def static_checks(d, env=None):
    d = os.path.abspath(d)
    sk = os.path.join(d, "SKILL.md")
    if not os.path.isfile(sk):
        die(f"{d} has no SKILL.md")
    text = read(sk)
    fm, body = frontmatter(text)
    files = skill_files(d)
    texts = {f: read(os.path.join(d, f)) for f in files if f.endswith((".md", ".py", ".json", ".txt", ".sh", ".yaml", ".yml", ".csv"))}
    md = {f: t for f, t in texts.items() if f.endswith(".md")}
    F = []

    def add(cid, where, key, evidence, est, judgment=False):
        F.append({"id": stable_id(cid, key), "check": cid, "where": where, "evidence": evidence, "est_tokens_per_run": int(est),
                  "recommendation": REC[cid], "found_by": "script", "needs_judgment": judgment, "kind": "skill"})

    moved = 0   # tokens that S7 and S8 already count, so S1 does not count them twice
    for f, t in md.items():
        pl, blocks = prose_lines(t)
        for start, n, first in blocks:
            if n > 40:
                est = tok(len("\n".join(t.split("\n")[start:start + n])))
                moved += est if f == "SKILL.md" else 0
                add("S7", f"{f}:{start}", f + first + str(n // 50), f"fenced code block of {n} lines in the instructions", est)
        rows, first_row = 0, ""
        for i, ln in enumerate(pl + [""], 1):
            if ln.strip().startswith("|"):
                first_row = first_row or ln
                rows += 1
            else:
                if rows > 30:
                    est = tok(len("\n".join(pl[i - 1 - rows:i - 1])))
                    moved += est if f == "SKILL.md" else 0
                    add("S8", f"{f}:{i - rows}", f + first_row, f"markdown table of {rows} rows", est)
                rows, first_row = 0, ""
        for i, ln in enumerate(pl, 1):
            if re.search(r"(?i)\b(read|open|review|look at)\b[^.\n]{0,40}\b[\w/.-]+\.(py|sh|js)\b", ln) and not re.search(r"(?i)\brun\b", ln):
                m = re.search(r"[\w/.-]+\.(py|sh|js)", ln)
                size = tok(len(texts.get(m.group(0), ""))) if m else 0
                add("S9", f"{f}:{i}", f + ln.strip(), f"the instructions tell the model to read a script: {ln.strip()[:100]}", size, True)
            if re.search(r"(?i)\b(calculate|compute|sum (of|up)|add up|total (the|up)|multiply|divide|percentage of|variance (of|between)|average)\b", ln) \
                    and not re.search(r"(?i)(\.py|\.sh|script|costkit|python3)", ln):
                add("S12", f"{f}:{i}", f + ln.strip(), f"possible arithmetic left to the model: {ln.strip()[:100]}", 0, True)
    nlines, btok = body.count("\n") + 1, tok(len(body))
    if nlines > 500 or btok > 5000:
        add("S1", "SKILL.md", "SKILL.md body", f"body is {nlines} lines and about {btok:,} tokens (aim: under 500 lines and about 5,000 tokens)",
            max(0, btok - 5000 - moved))
    desc = (fm.get("description", "") + " " + fm.get("when_to_use", "")).strip()
    if len(desc) > 1024:
        add("S2", "SKILL.md frontmatter", "description", f"description is {len(desc)} characters (limit 1,024; listing cut at 1,536)", tok(len(desc)) - 256)
    for f in files:
        if f == "SKILL.md":
            continue
        base = os.path.basename(f)
        if not (f in text or base in text):
            via = [o for o, t in md.items() if o != f and (f in t or base in t)]
            add("S3", f, f, ("linked only from " + via[0] + " (two levels deep)") if via else "not named in SKILL.md (orphan)",
                tok(len(texts.get(f, ""))) if via else 0)
            continue
        if f.endswith(".md"):
            cue_lines = [ln for ln in text.split("\n") if (f in ln or base in ln)]
            if cue_lines and not any(re.search(r"(?i)\b(when|only if|if you|if the|before|after|for (a|an|the|each))\b", ln) for ln in cue_lines):
                add("S10", f, f, f"linked from SKILL.md with no when-to-read cue ({tok(len(texts.get(f, ''))):,} tokens if read every run)",
                    tok(len(texts.get(f, ""))), True)
    for f, t in md.items():
        if f != "SKILL.md" and t.count("\n") > 100:
            head = "\n".join(t.split("\n")[:30]).lower()
            if "contents" not in head and len(re.findall(r"^\s*[-*\d.]+\s*\[", head, re.M)) < 3:
                add("S4", f, f, f"{t.count(chr(10))} lines and no contents list near the top", tok(len(t)) // 2)
    for f in files:
        if re.search(r"(^|/)(README|CHANGELOG)[^/]*$|(^|/)(tests?|fixtures|evals|old|archive)/|\.(bak|orig)$", f, re.I):
            add("S5", f, f, "development material inside the runtime skill", 0)
    seen = {}
    for f, t in md.items():
        pl, _ = prose_lines(t)
        for i, ln in enumerate(pl, 1):
            norm = re.sub(r"\W+", " ", ln).strip().lower()
            if len(norm) >= 80:
                seen.setdefault(norm, []).append(f"{f}:{i}")
    for norm, where in seen.items():
        if len(where) > 1:
            add("S6", ", ".join(where[:4]), norm, f"the same {len(norm)}-character line appears {len(where)} times", tok(len(norm)) * (len(where) - 1))
    if "<!-- cost-ceiling-start -->" not in text and not re.search(r"(?im)^#+\s*cost ceiling", text):
        add("S11", "SKILL.md", "ceiling", "no cost-ceiling section", 0)
    if env == "claude-code" and not fm.get("model") and not fm.get("effort"):
        add("S13", "SKILL.md frontmatter", "frontmatter", "no model or effort set", 0, True)
    return {"summary": {"skill": d, "skill_md_body_tokens": btok, "skill_md_body_lines": nlines,
                        "description_tokens_every_session": tok(len(desc)), "files": len(files)}, "findings": F}


def cmd_static(a):
    env = load_json(os.path.join(a.save, "config.json"))["env"] if a.save else a.env
    res = static_checks(a.skill_dir, env)
    if not a.save:
        print(json.dumps(res, indent=1))
        return
    p = os.path.join(a.save, "findings_static.json")
    old = load_json(p, {"findings": []})["findings"]
    now = {f["id"] for f in res["findings"]}
    for f in old:   # a finding from an earlier check that is gone now is kept and marked resolved
        if f["id"] not in now:
            f["resolved"] = True
            res["findings"].append(f)
    save_json(p, res)
    live = [f for f in res["findings"] if not f.get("resolved")]
    print(f"{len(live)} findings ({sum(f['needs_judgment'] for f in live)} need judgment), "
          f"{len(res['findings']) - len(live)} resolved since an earlier check; saved to {p}")
    for f in sorted(live, key=lambda f: -f["est_tokens_per_run"]):
        print(f"  {f['id']:10} {f['est_tokens_per_run']:>8,}  {'J ' if f['needs_judgment'] else '  '}{f['where']}: {f['evidence'][:90]}")


# ---------------------------------------------------------------- measure
def find_agent_transcript(agent_id):
    hits = glob.glob(os.path.expanduser(f"~/.claude/projects/**/subagents/agent-{agent_id}.jsonl"), recursive=True)
    if not hits:
        die(f"no transcript found for agent {agent_id} under ~/.claude/projects/**/subagents/")
    return max(hits, key=os.path.getmtime)


def parse_ts(s):
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def load_prices():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prices.json")
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return {"models": {}}


def weights_for(model, cfg):
    """Price ratios to one input token of the same model: from prices.json when the model is listed there, otherwise
    the defaults with the cache-read ratio chosen by model name."""
    pr = (load_prices().get("models") or {}).get(model or "")
    if pr and pr.get("input"):
        return {k: pr[k] / pr["input"] for k in DEFAULT_WEIGHTS if k in pr}
    w = dict(cfg.get("weights", DEFAULT_WEIGHTS))
    for rule in cfg.get("cache_read_by_model", CACHE_READ_BY_MODEL):
        if model and re.search(rule["match"], model):
            w["cache_read"] = rule["ratio"]
            break
    return w


def zero():
    return {"input": 0, "cache_write_5m": 0, "cache_write_1h": 0, "cache_read": 0, "output": 0, "thinking": 0}


def read_rows(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                if ln.strip():
                    try:
                        rows.append(json.loads(ln))
                    except ValueError:
                        pass
    except OSError as ex:
        die(f"cannot read transcript {path}: {ex}")
    return rows


def step_of(name, inp, steps):
    text = name + " " + json.dumps(inp)[:4000]
    return next((s["step"] for s in steps if re.search(s["match"], text)), "other: " + name)


def parse_transcript(path, label, steps, since=None, until=None, main_only=False, parent_step=None, depth=0):
    """Usage per request, tool calls (with their step from the account's step map) and results for one transcript,
    and for every sub-agent it started (found by the Agent call's id in the sub-agent's .meta.json). A sub-agent's
    tokens are counted under the step of the Agent call that started it."""
    rows = []
    for r in read_rows(path):
        t = parse_ts(r.get("timestamp"))
        if (since and t and t < since) or (until and t and t > until):
            continue
        if main_only and r.get("isSidechain"):
            continue
        rows.append(r)
    usage, model_of, first_ts, calls, results, efforts, human_ts = {}, {}, {}, [], {}, [], []
    for r in rows:
        if r.get("effort"):
            efforts.append(r["effort"])
        msg = r.get("message") or {}
        if r.get("type") == "assistant" and isinstance(msg, dict):
            mid = msg.get("id") or r.get("uuid")
            if msg.get("usage") and not str(msg.get("model", "")).startswith("<"):
                usage[mid] = msg["usage"]          # repeated rows carry the same usage; the last one is kept
            model_of[mid] = msg.get("model") or model_of.get(mid)
            first_ts.setdefault(mid, parse_ts(r.get("timestamp")))
            for c in msg.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    inp = c.get("input") or {}
                    calls.append({"id": c.get("id"), "name": c.get("name"), "input": inp, "req": mid, "agent": label,
                                  "step": parent_step or step_of(c.get("name", ""), inp, steps), "start": parse_ts(r.get("timestamp"))})
        elif r.get("type") == "user" and isinstance(msg.get("content"), list):
            for c in msg["content"]:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    body = c.get("content")
                    results[c.get("tool_use_id")] = {"chars": len(body) if isinstance(body, str) else len(json.dumps(body)),
                                                     "error": bool(c.get("is_error")), "end": parse_ts(r.get("timestamp"))}
            if not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in msg["content"]):
                human_ts.append(parse_ts(r.get("timestamp")))
        elif r.get("type") == "user":
            human_ts.append(parse_ts(r.get("timestamp")))
    req_steps = {}
    for c in calls:
        req_steps.setdefault(c["req"], []).append(c["step"])
    stamps = [s for s in (r.get("timestamp") for r in rows) if s]
    part = {"label": label, "calls": calls, "results": results, "reqs": list(usage), "first_ts": first_ts, "usage": usage,
            "model_of": model_of, "req_steps": req_steps, "efforts": efforts, "parent_step": parent_step, "human_ts": [t for t in human_ts if t],
            "start": min(stamps) if stamps else None, "end": max(stamps) if stamps else None,
            "cost_state": [r for r in rows if r.get("type") == "cost-state"],
            "compactions": sum(1 for r in rows if r.get("type") == "system" and r.get("subtype") == "compact_boundary"),
            "api_errors": sum(1 for r in rows if r.get("isApiErrorMessage") or r.get("apiError"))}
    parts = [part]
    agents = {c["id"]: c["step"] for c in calls if c["name"] in ("Agent", "Task")}
    if agents and depth < 5:
        dirs = {os.path.dirname(path), os.path.splitext(path)[0] + os.sep + "subagents"}
        for d in dirs:
            for meta in glob.glob(os.path.join(d, "agent-*.meta.json")):
                try:
                    mt = json.load(open(meta))
                except (OSError, ValueError):
                    continue
                if mt.get("toolUseId") in agents:
                    child = meta[:-len(".meta.json")] + ".jsonl"
                    if os.path.isfile(child):
                        parts += parse_transcript(child, f"sub-agent {os.path.basename(child)[6:-6]}", steps,
                                                  parent_step=parent_step or agents[mt["toolUseId"]], depth=depth + 1)
    return parts


def usage_tokens(u):
    cc = u.get("cache_creation") or {}
    w5, w1 = cc.get("ephemeral_5m_input_tokens"), cc.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:
        w5, w1 = u.get("cache_creation_input_tokens", 0), 0
    return {"input": u.get("input_tokens", 0) or 0, "cache_write_5m": w5 or 0, "cache_write_1h": w1 or 0,
            "cache_read": u.get("cache_read_input_tokens", 0) or 0, "output": u.get("output_tokens", 0) or 0,
            "thinking": (u.get("output_tokens_details") or {}).get("thinking_tokens", 0) or 0}


def add_component(comps, model, u, t):
    pr = (load_prices().get("models") or {}).get(model or "", {})
    lc = pr.get("long_context") or {}
    prompt = t["input"] + t["cache_write_5m"] + t["cache_write_1h"] + t["cache_read"]
    tier = "long" if lc and prompt > lc.get("over_prompt_tokens", 10 ** 12) else "standard"
    key = "|".join([model or "unknown", "fast" if u.get("speed") == "fast" else "standard",
                    "us" if u.get("inference_geo") == "us" else "global", tier])
    c = comps.setdefault(key, zero() | {"web_search": 0})
    for k in zero():
        c[k] += t[k]
    c["web_search"] += ((u.get("server_tool_use") or {}).get("web_search_requests") or 0)


def price_components(comps, prices=None):
    """List-price dollars for a set of pricing buckets, at the current prices.json; None if a model has no price.
    Thinking is part of output_tokens, so it is not added again."""
    prices = prices or load_prices()
    models, mods = prices.get("models") or {}, prices.get("modifiers") or {}
    total, missing = 0.0, set()
    for key, c in comps.items():
        model, speed, geo, tier = key.split("|")
        pr = models.get(model)
        if not pr:
            missing.add(model)
            continue
        table = (pr.get("long_context") or {}).get("prices") if tier == "long" else pr
        mult = (mods.get("fast_mode", {}).get("multiplier", 2.0) if speed == "fast" else 1.0) * \
               (mods.get("inference_geo_us", {}).get("multiplier", 1.1) if geo == "us" else 1.0)
        total += mult * sum(c[k] * table[k] for k in ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")) / 1e6
        total += c.get("web_search", 0) * mods.get("web_search_per_1000", 10.0) / 1000
    return (None, sorted(missing)) if missing else (round(total, 6), [])


def measure_transcript(path, cfg, steps=(), since=None, until=None, main_only=False):
    parts = parse_transcript(path, "main", list(steps), since, until, main_only)
    if not parts[0]["usage"]:
        die(f"no assistant usage found in {path}" + (" in that time window" if since or until else "")
            + "; the transcript is empty or not a Claude Code transcript")
    by_model, by_step, comps = {}, {}, {}
    for p in parts:
        for mid, u in p["usage"].items():
            mdl = p["model_of"].get(mid) or "unknown"
            t = usage_tokens(u)
            acc = by_model.setdefault(mdl, zero())
            for k in acc:
                acc[k] += t[k]
            add_component(comps, mdl, u, t)
            one = {}
            add_component(one, mdl, u, t)
            usd, _ = price_components(one)
            w = weights_for(mdl, cfg)
            weighted = sum(t[k] * w[k] for k in w)
            sts = p["req_steps"].get(mid) or [p["parent_step"] or "replies and reasoning (no tool call)"]
            for s in sts:   # a request that made several calls is split evenly across their steps
                row = by_step.setdefault(s, {"weighted_tokens": 0.0, "usd": 0.0, "tool_calls": 0, "minutes": 0.0, "errors": 0})
                row["weighted_tokens"] += weighted / len(sts)
                row["usd"] = None if usd is None or row["usd"] is None else row["usd"] + usd / len(sts)
        for c in p["calls"]:
            if p["parent_step"]:
                continue   # a sub-agent's calls run inside its parent's Agent call, whose time is already counted
            row = by_step.setdefault(c["step"], {"weighted_tokens": 0.0, "usd": 0.0, "tool_calls": 0, "minutes": 0.0, "errors": 0})
            row["tool_calls"] += 1
            res = p["results"].get(c["id"], {})
            row["errors"] += 1 if res.get("error") else 0
            if c["start"] and res.get("end"):
                row["minutes"] += (res["end"] - c["start"]).total_seconds() / 60
    main = parts[0]
    last = main["usage"][main["reqs"][-1]]
    t0, t1 = parse_ts(main["start"]), parse_ts(main["end"])
    efforts = main["efforts"]
    m = {"source": "transcript" + (f" plus {len(parts) - 1} sub-agent transcript(s)" if len(parts) > 1 else ""), "path": path,
         "window": {"since": since.isoformat() if since else None, "until": until.isoformat() if until else None},
         "models": sorted(by_model), "effort": max(set(efforts), key=efforts.count) if efforts else "unknown",
         "requests": sum(len(p["reqs"]) for p in parts), "tool_calls": sum(len(p["calls"]) for p in parts),
         "main_requests": len(main["reqs"]), "main_tool_calls": len(main["calls"]), "components": comps,
         "duration_s": round((t1 - t0).total_seconds()) if t0 and t1 else None,
         "final_context_tokens": last.get("input_tokens", 0) + last.get("cache_creation_input_tokens", 0) + last.get("cache_read_input_tokens", 0),
         "tokens_by_model": by_model, "subtype": None,
         "compactions": sum(p["compactions"] for p in parts), "api_errors": sum(p["api_errors"] for p in parts)}
    cs = main["cost_state"]
    if cs:
        mu = cs[-1].get("modelUsage") or {}
        m["app_cost_record"] = {"cost_usd": round(cs[-1].get("totalCostUSD") or 0, 4),
                                "by_model": {k: round(v.get("costUSD") or 0, 4) for k, v in mu.items()},
                                "note": "the app's own record for the whole chat, written from time to time, so it can lag the run "
                                        "and can include usage that no transcript shows"}
    finish(m, cfg)
    m["cost_usd"], m["unpriced_models"] = price_components(comps)
    priced = m["cost_usd"] is not None
    key = "usd" if priced else "weighted_tokens"
    total = sum(r[key] for r in by_step.values()) or 1
    m["by_step_unit"] = "usd" if priced else "weighted tokens (mixed units: a model has no price in prices.json)"
    m["by_step"] = sorted(({"step": s, "weighted_tokens": round(r["weighted_tokens"]), "usd": round(r["usd"], 4) if priced else None,
                            "share": round(r[key] / total, 3), "tool_calls": r["tool_calls"], "minutes": round(r["minutes"], 1), "errors": r["errors"]}
                           for s, r in by_step.items()), key=lambda r: -r["share"])
    m["runtime_findings"], m["levers"] = runtime_checks(parts, m)
    return m


def finish(m, cfg):
    """Totals, weighted tokens (each model in its own input-token units) and the cache hit rate."""
    tot = zero()
    m["weights_by_model"], m["weighted_by_model"] = {}, {}
    for mdl, t in m["tokens_by_model"].items():
        w = weights_for(mdl, cfg)
        m["weights_by_model"][mdl] = w
        m["weighted_by_model"][mdl] = round(sum(t[k] * w[k] for k in w))
        for k in tot:
            tot[k] += t[k]
    m["tokens"] = tot
    m["weighted_tokens"] = sum(m["weighted_by_model"].values())
    m["total_tokens_processed"] = sum(tot[k] for k in ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output"))
    denom = tot["cache_read"] + tot["cache_write_5m"] + tot["cache_write_1h"] + tot["input"]
    m["cache_hit_rate"] = round(tot["cache_read"] / denom, 3) if denom else None


def runtime_checks(parts, m):
    F = []

    def add(cid, where, key, evidence, est, rec, judgment=False):
        F.append({"id": stable_id(cid, key), "check": cid, "where": where, "evidence": evidence, "est_tokens_per_run": int(est),
                  "recommendation": rec, "found_by": "script", "needs_judgment": judgment, "kind": "run"})

    gaps_all, batch_all = [], []
    for p in parts:
        lab = "" if p["label"] == "main" else p["label"] + ": "
        mods = [x for x in p["model_of"].values() if x]
        cr = weights_for(max(set(mods), key=mods.count) if mods else None, {}).get("cache_read", 0.1)
        w1 = sum((u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0 for u in p["usage"].values())
        w5 = sum((u.get("cache_creation") or {}).get("ephemeral_5m_input_tokens") or 0 for u in p["usage"].values())
        ttl = 3600 if w1 > w5 else CACHE_TTL_SECONDS
        calls, results, reqs = p["calls"], p["results"], p["reqs"]
        order = {r: i for i, r in enumerate(reqs)}
        reads = {}
        for c in calls:
            path = c["input"].get("file_path") or c["input"].get("path")
            if c["name"] in ("Read", "read_file", "View") and path:
                reads.setdefault(path, []).append(c)
        for path, cs in reads.items():
            if len(cs) > 1:
                add("R1", lab + path, lab + path, f"read {len(cs)} times in one run",
                    sum(tok(results.get(c["id"], {}).get("chars", 0)) for c in cs[1:]), "Read the file once, or give the step the part it needs.")
        sig = {}
        for c in calls:
            sig.setdefault((c["name"], json.dumps(c["input"], sort_keys=True)), []).append(c)
        for (name, inp), cs in sig.items():
            if len(cs) > 1 and name not in ("Read", "read_file", "View"):
                add("R2", lab + name, lab + name + inp, f"the same call was made {len(cs)} times with the same input ({inp[:80]})",
                    sum(tok(results.get(c["id"], {}).get("chars", 0)) for c in cs[1:]), "Remove the repeated call and reuse the first result.")
        errs = [c for c in calls if results.get(c["id"], {}).get("error")]
        if errs:
            names = ", ".join(sorted({c["name"] for c in errs}))[:120]
            add("R3", lab + names, lab + "errors" + names, f"{len(errs)} tool calls failed", 0,
                "Fix the instruction or input that made these calls fail.", True)
        for c in calls:
            ch = results.get(c["id"], {}).get("chars", 0)
            if ch > LARGE_RESULT_CHARS:
                later = len(reqs) - 1 - order.get(c["req"], len(reqs) - 1)
                inp = json.dumps(c["input"], sort_keys=True)
                add("R4", lab + c["name"], lab + c["name"] + inp, f"one result of about {tok(ch):,} tokens ({inp[:80]}), resent as context on {later} later requests",
                    tok(ch) * (1 + later * cr),
                    "Filter or summarize at the source (a narrower query, a script, or a sub-agent that returns only the answer).")
        agents = [c for c in calls if c["name"] in ("Agent", "Task")]
        if agents:
            add("R5", lab + "Agent", lab + "agents", f"{len(agents)} sub-agents started; their usage is included in the totals", 0,
                "Check whether one step could replace these agents, or run them on a cheaper model.", True)
        by_name = {}
        for c in calls:
            if c["name"] not in GENERIC_TOOLS:
                by_name.setdefault((c["name"], tuple(sorted(c["input"]))), []).append(c)
        for (name, keys), cs in by_name.items():
            if len(cs) >= REPEAT_CALLS_FOR_BATCH and len({json.dumps(c["input"], sort_keys=True) for c in cs}) == len(cs):
                batch_all.append(f"{lab}{name} x{len(cs)}")
        ft = p["first_ts"]
        for x, y in zip(reqs, reqs[1:]):   # a gap that holds one of the person's messages is their reply time, not the skill's
            if ft.get(x) and ft.get(y) and (ft[y] - ft[x]).total_seconds() > ttl and not any(ft[x] < h < ft[y] for h in p["human_ts"]):
                gaps_all.append(round((ft[y] - ft[x]).total_seconds()))
    if gaps_all:
        add("R6", "requests", "gaps", f"{len(gaps_all)} gaps longer than the cache window, with no message from the person in between ({gaps_all[:5]} seconds)", 0,
            "Avoid idle waits inside a run; a request after the cache expires pays full price for the whole context.")
    t = m["tokens"]
    out = t["output"] or 1
    levers = {
        "batching": {"status": "needs_judgment" if batch_all else "not indicated",
                     "evidence": ("the same tool with the same parameters and different values: " + ", ".join(batch_all)[:200])
                     if batch_all else "no repeated per-item calls found"},
        "caching": {"status": "measured", "evidence": f"cache hit rate {m['cache_hit_rate']}; {len(gaps_all)} gaps over the cache window"},
        "effort": {"status": "needs_judgment" if t["thinking"] / out > 0.5 else "not indicated",
                   "evidence": f"thinking was {t['thinking']:,} of {t['output']:,} output tokens; effort {m['effort']}"},
        "model_per_step": {"status": "needs_judgment", "evidence": f"models {', '.join(m['models'])}; a script cannot tell which steps are simple"},
    }
    return F, levers


def measure_sdk(path, cfg):
    r = load_json(path)
    by_model = {}
    mu = r.get("modelUsage") or r.get("model_usage")
    if mu:   # includes sub-agents; the plain "usage" field does not
        for mdl, v in mu.items():
            t = by_model.setdefault(mdl, zero())
            t["input"] += v.get("inputTokens", v.get("input_tokens", 0))
            t["output"] += v.get("outputTokens", v.get("output_tokens", 0))
            t["cache_read"] += v.get("cacheReadInputTokens", v.get("cache_read_input_tokens", 0))
            t["cache_write_5m"] += v.get("cacheCreationInputTokens", v.get("cache_creation_input_tokens", 0))
        src = "sdk modelUsage (includes sub-agents)"
    else:
        u = r.get("usage") or {}
        t = by_model.setdefault("unknown", zero())
        t["input"], t["output"] = u.get("input_tokens", 0), u.get("output_tokens", 0)
        t["cache_read"], t["cache_write_5m"] = u.get("cache_read_input_tokens", 0), u.get("cache_creation_input_tokens", 0)
        src = "sdk usage (excludes sub-agents: undercounts if the run started agents)"
    comps = {f"{mdl}|standard|global|standard": t | {"web_search": 0} for mdl, t in by_model.items()}
    m = {"source": src, "path": path, "models": sorted(by_model), "effort": "unknown", "requests": r.get("num_turns"), "components": comps,
         "main_requests": r.get("num_turns"), "main_tool_calls": None,
         "tool_calls": None, "duration_s": round(r["duration_ms"] / 1000) if r.get("duration_ms") else None,
         "tokens_by_model": by_model, "sdk_total_cost_usd_estimate": r.get("total_cost_usd"), "subtype": r.get("subtype"),
         "runtime_findings": [], "levers": {}}
    finish(m, cfg)
    m["cost_usd"], m["unpriced_models"] = price_components(comps)
    return m


def steps_of(cfg):
    return (load_json(cfg["account"]).get("steps") or []) if cfg.get("account") else []


def do_measure(a, cfg):
    if a.sdk_result:
        return measure_sdk(a.sdk_result, cfg)
    return measure_transcript(a.transcript or find_agent_transcript(a.agent_id), cfg, steps_of(cfg))


def save_run_findings(w, m):
    """The run findings and levers that the judgments and approvals refer to: from the latest real run or baseline."""
    mods = m.get("tokens_by_model") or {}
    main_model = max(mods, key=lambda k: mods[k]["output"]) if mods else None
    save_json(os.path.join(w, "findings_run.json"), {"from": m.get("path"), "findings": m.get("runtime_findings", []),
                                                     "levers": m.get("levers", {}), "by_step": m.get("by_step", []),
                                                     "by_step_unit": m.get("by_step_unit"), "main_model": main_model,
                                                     "main_requests": m.get("main_requests")})


def cmd_measure(a):
    cfg = cfg_of(os.path.abspath(a.save)) if a.save else {}
    m = do_measure(a, cfg)
    if not a.save:
        print(json.dumps(m, indent=1))
        return
    if not a.round or not ROUND_RE.match(a.round):
        die("--save needs --round: baseline, round2, round3, ...")
    p = os.path.join(a.save, "runs", a.round, "measure.json")
    save_json(p, m)
    if a.round == "baseline" and not os.path.isfile(os.path.join(a.save, "findings_run.json")):
        save_run_findings(a.save, m)
    print(f"{a.round}: {m['weighted_tokens']:,} weighted tokens, {m['total_tokens_processed']:,} processed, {m['tool_calls']} tool calls, "
          f"{m['requests']} requests, models {m['models']}, effort {m['effort']}, cache hit rate {m['cache_hit_rate']}; "
          f"{len(m['runtime_findings'])} run findings; saved to {p}")


# ---------------------------------------------------------------- compare outputs
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AaPp][Mm])?\b")
NUM_RE = re.compile(r"(?<![\w.])(-?)(\(?)\$?(\d[\d,]*(?:\.\d+)?)(\)?)\s?(%|[KkMmBb]n?\b|mm\b)?")
SCALE = {"k": 1e3, "m": 1e6, "mm": 1e6, "b": 1e9, "bn": 1e9}


def numbers(text):
    out = []
    for neg, lp, digits, rp, suf in NUM_RE.findall(DATE_RE.sub(" ", text)):
        try:
            v = float(digits.replace(",", ""))
        except ValueError:
            continue
        if neg or (lp and rp):
            v = -v
        s = (suf or "").lower()
        v = v / 100 if s == "%" else v * SCALE.get(s, 1)
        out.append(float(f"{v:.6g}"))
    return out


def file_text(path):
    low = path.lower()
    if low.endswith((".xlsx", ".xlsm")):
        try:
            from openpyxl import load_workbook
        except ImportError:
            return None
        vals, forms = load_workbook(path, data_only=True), load_workbook(path)
        lines = []
        for ws in forms.worksheets:
            wv = vals[ws.title]
            for row in ws.iter_rows():
                cells = []
                for c in row:
                    cached = wv[c.coordinate].value
                    f = c.value if isinstance(c.value, str) and c.value.startswith("=") else None
                    cells.append(("" if cached is None else str(cached)) + (f" {f}" if f else ""))
                lines.append(",".join(cells))
        return "\n".join(lines)
    with open(path, "rb") as fh:
        raw = fh.read()
    if b"\0" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="ignore")


def compare_outputs(a, b):
    res = {"only_in_a": [], "only_in_b": [], "files": []}
    for side, d in (("a", a), ("b", b)):
        if not os.path.isdir(d) or not [f for f in skill_files(d) if not os.path.basename(f).startswith("_")]:
            res["verdict"], res["reason"] = "fail", f"output folder {side} ({d}) is missing or empty"
            return res
    fa = {f for f in skill_files(a) if not os.path.basename(f).startswith("_")}
    fb = {f for f in skill_files(b) if not os.path.basename(f).startswith("_")}
    res["only_in_a"], res["only_in_b"] = sorted(fa - fb), sorted(fb - fa)
    for f in sorted(fa & fb):
        pa, pb = os.path.join(a, f), os.path.join(b, f)
        if open(pa, "rb").read() == open(pb, "rb").read():
            res["files"].append({"file": f, "result": "identical"})
            continue
        ta, tb = file_text(pa), file_text(pb)
        if ta is None or tb is None:
            res["files"].append({"file": f, "result": "binary_differs"})
        elif sorted(numbers(ta)) != sorted(numbers(tb)):
            na, nb = numbers(ta), numbers(tb)
            res["files"].append({"file": f, "result": "numbers_differ", "only_in_a": sorted(set(na) - set(nb))[:10],
                                 "only_in_b": sorted(set(nb) - set(na))[:10]})
        else:
            res["files"].append({"file": f, "result": "text_differs_numbers_match"})
    kinds = {x["result"] for x in res["files"]}
    if res["only_in_a"] or "numbers_differ" in kinds:
        res["verdict"] = "fail"
    elif res["only_in_b"] or kinds & {"text_differs_numbers_match", "binary_differs"}:
        res["verdict"] = "needs_judgment"
    else:
        res["verdict"] = "pass"
    return res


def cmd_compare(a):
    res = compare_outputs(os.path.abspath(a.out_a), os.path.abspath(a.out_b))
    if a.save:
        if not a.round:
            die("--save needs --round")
        save_json(os.path.join(a.save, "runs", a.round, "compare.json"), res)
    print(json.dumps(res, indent=1))
    if res["verdict"] == "needs_judgment":
        print(f"\nRead the files listed above in both folders, then log: costkit judge WORK --id output:{a.round or 'ROUND'} "
              "--decision equivalent|\"not equivalent\" --note \"...\"")
    sys.exit(3 if res["verdict"] == "fail" else 0)


# ---------------------------------------------------------------- record, score, decide
def skill_hash(d):
    h = hashlib.sha256()
    for f in skill_files(d):
        h.update(f.encode())
        with open(os.path.join(d, f), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:8]


def records(w):
    p = os.path.join(w, "metrics.jsonl")
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def write_records(w, recs):
    with open(os.path.join(w, "metrics.jsonl"), "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in recs)


def baseline_of(recs):
    """The latest baseline: a new baseline starts a new session."""
    bs = [r for r in recs if r["round"] == "baseline"]
    return bs[-1] if bs else None


def session_of(recs):
    """Test-run records since the latest baseline, without quarterly checks or real runs."""
    i = max(i for i, r in enumerate(recs) if r["round"] == "baseline")
    return [r for r in recs[i:] if not r["round"].startswith(("check-", "real-"))]


def reals_of(recs):
    """Real runs (measured from a chat where the skill ran for real), scored against the first real run."""
    return [r for r in recs if r["round"].startswith("real-")]


def output_verdict(w, rnd, given, reason):
    if given == "not_compared":
        if not reason:
            die("--output-check not_compared needs --reason (why the outputs could not be compared)")
        return "not_compared"
    if rnd == "baseline":
        return "baseline"
    c = load_json(os.path.join(w, "runs", rnd, "compare.json"), {})
    if not c:
        die(f"no comparison for {rnd}: run costkit compare-outputs WORK/runs/baseline/out WORK/runs/{rnd}/out --save WORK --round {rnd}")
    if c["verdict"] != "needs_judgment":
        return c["verdict"]
    j = load_json(os.path.join(w, "judgments.json"), {}).get(f"output:{rnd}")
    if not j:
        die(f"the comparison for {rnd} needs judgment: log costkit judge WORK --id output:{rnd} --decision equivalent|\"not equivalent\" first")
    return "pass" if j["decision"] == "equivalent" else "fail"


def make_record(w, cfg, rnd, skill, outcomes, verdict, reason, reviewer_edits, tested):
    m = load_json(os.path.join(w, "runs", rnd, "measure.json"))
    if outcomes <= 0:
        die("--outcomes must be at least 1 (the number of outcome units the run produced)")
    recs = records(w)
    real = rnd.startswith("real-")
    if not real and rnd != "baseline" and any(r["round"] == rnd for r in (session_of(recs) if baseline_of(recs) else recs)):
        die(f"{rnd} is already recorded in this session; use the next round name")
    if real and any(r["round"] == rnd for r in recs):
        die(f"{rnd} is already recorded")
    if not real and rnd != "baseline" and not baseline_of(recs):
        die("record the baseline first")
    ceil = load_json(os.path.join(w, "ceiling.json"), {})
    env = "sdk" if m["source"].startswith("sdk") else cfg["env"]
    rec = {"date": str(datetime.date.today()), "round": rnd, "series": "real" if real else "test", "skill_hash": skill_hash(skill),
           "models": m["models"], "effort": m.get("effort", "unknown"), "environment": env, "tested_change": tested,
           "tokens": m["tokens"], "total_tokens_processed": m["total_tokens_processed"], "weighted_tokens": m["weighted_tokens"],
           "components": m.get("components") or {}, "tool_calls": m.get("tool_calls"), "main_tool_calls": m.get("main_tool_calls"),
           "requests": m.get("requests"), "main_requests": m.get("main_requests"), "duration_s": m.get("duration_s"), "outcomes": outcomes,
           "weighted_tokens_per_outcome": round(m["weighted_tokens"] / outcomes), "cache_hit_rate": m.get("cache_hit_rate"),
           "reviewer_edits": reviewer_edits, "output_check": verdict, "output_reason": reason, "measure_source": m["source"],
           "by_step": m.get("by_step"), "by_step_unit": m.get("by_step_unit")}
    usd, missing = price_components(rec["components"]) if rec["components"] else (None, ["no usage buckets"])
    rec["cost_usd"], rec["unpriced_models"] = usd, missing
    rec["est_cost_per_outcome_usd"] = round(usd / outcomes, 4) if usd is not None else None
    base = rec if rnd == "baseline" or (real and not reals_of(recs)) else (reals_of(recs)[0] if real else baseline_of(recs))
    gates = {}
    if rnd != "baseline" and not real:
        gates["output_check"] = verdict == "pass" or (rnd.startswith("check-") and verdict == "not_compared")
        if reviewer_edits is not None and base.get("reviewer_edits") is not None:
            gates["reviewer_edits"] = reviewer_edits <= base["reviewer_edits"]
        calls = rec["main_tool_calls"] if rec["main_tool_calls"] is not None else rec["tool_calls"]
        if ceil.get("tool_calls") and calls is not None:
            gates["under_ceiling"] = calls <= ceil["tool_calls"]
        if ceil.get("max_turns") and rec["tool_calls"] is None and rec["requests"] is not None:
            gates["under_ceiling"] = rec["requests"] <= ceil["max_turns"]
    if m.get("subtype") in ("error_max_turns", "error_max_budget_usd"):
        gates["finished_within_limits"] = False
    rec["gates"] = gates
    # Scored in list-price dollars per outcome, both sides re-priced at today's prices.json, so a price change moves
    # neither side and runs on different models are comparable. Without a price for every model, the score falls back to
    # weighted tokens, which are only comparable on the same models.
    base_usd, _ = price_components(base.get("components") or {}) if base.get("components") else (None, [])
    basis = "dollars" if usd is not None and base_usd is not None else "tokens"
    diffs = [k for k in ("models", "effort", "environment") if rec[k] != base[k]]
    if real:
        blocked = [d for d in diffs if d == "environment" or (d == "models" and basis == "tokens")]
    else:
        blocked = [d for d in diffs if not (d == "effort" and tested == "effort") and not (d == "models" and tested == "model" and basis == "dollars")]
    rec["score_basis"] = basis
    failed = [g for g, ok in gates.items() if not ok]
    if failed:
        rec["score"], rec["score_label"] = None, "failed the gate: " + ", ".join(failed)
    elif blocked:
        why = ", ".join(blocked) + (" differ from the first real run's" if real else " differ from the baseline's")
        if "models" in blocked and basis == "tokens":
            why += f" (add prices for {', '.join(missing) or 'the baseline models'} to prices.json to compare in dollars)"
        rec["score"], rec["score_label"] = None, "not comparable: " + why
    else:
        num = usd / outcomes if basis == "dollars" else rec["weighted_tokens_per_outcome"]
        den = base_usd / base["outcomes"] if basis == "dollars" else base["weighted_tokens_per_outcome"]
        rec["score"] = round(100 * num / den, 1)
        rec["score_label"] = str(rec["score"])
    with open(os.path.join(w, "metrics.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def cmd_record(a):
    w = os.path.abspath(a.work)
    cfg = cfg_of(w)
    if not ROUND_RE.match(a.round) or a.round.startswith("check-"):
        die("--round must be baseline, round2, round3, ... (quarterly checks use costkit check)")
    if a.round == "baseline" and baseline_of(records(w)) and not a.force:
        die("a baseline is already recorded; pass --force to start a new session with a new baseline")
    verdict = output_verdict(w, a.round, a.output_check, a.reason)
    rec = make_record(w, cfg, a.round, a.skill, a.outcomes, verdict, a.reason, a.reviewer_edits, a.tested_change)
    print(f"{rec['round']}: score {rec['score_label']} ({rec['weighted_tokens_per_outcome']:,} weighted tokens per outcome; "
          f"output check {rec['output_check']}; gates {rec['gates']})")


def open_items(w):
    """Findings and levers that are not resolved, decided, applied or declined."""
    marks = load_json(os.path.join(w, "applied.json"), {})
    judg = load_json(os.path.join(w, "judgments.json"), {})
    base = load_json(os.path.join(w, "findings_run.json"), {})
    items = load_json(os.path.join(w, "findings_static.json"), {"findings": []})["findings"] + base.get("findings", [])
    out = [f["id"] for f in items if not f.get("resolved") and f["id"] not in marks
           and judg.get(f["id"], {}).get("decision") != "not a finding" and (f["est_tokens_per_run"] > 0 or f["needs_judgment"])]
    for k, v in (base.get("levers") or {}).items():
        lid = "lever:" + k
        if lid in marks:
            continue
        d = judg.get(lid, {}).get("decision")
        if (v["status"] == "needs_judgment" and not d) or d == "applies":
            out.append(lid)
    return out


def ceiling_block(c):
    return (f"{CEILING_START}\n## Cost ceiling\n\n"
            f"- This skill normally finishes in about {c['baseline_tool_calls']} tool calls. If a run reaches {c['tool_calls']} tool calls, "
            "stop, report what is finished and what remains, and do not continue without the person's approval.\n"
            f"- When the skill runs through the Agent SDK or the command line, set `--max-turns {c['max_turns']}`"
            + (f" and `--max-budget-usd {c['budget_usd']}`" if c.get("budget_usd") else "")
            + ", which the runtime enforces. A turn is one request, which can hold several tool calls.\n"
            f"{CEILING_END}")


CEILING_START, CEILING_END = "<!-- cost-ceiling-start -->", "<!-- cost-ceiling-end -->"


def write_ceiling(skill_dir, c):
    sk = os.path.join(skill_dir, "SKILL.md")
    text = read(sk)
    block = ceiling_block(c)
    if CEILING_START in text:
        text = re.sub(re.escape(CEILING_START) + r".*?" + re.escape(CEILING_END), lambda _: block, text, flags=re.S)
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    with open(sk, "w", encoding="utf-8") as fh:
        fh.write(text)


def cmd_decide(a):
    w = os.path.abspath(a.work)
    recs = records(w)
    if not baseline_of(recs):
        die("no baseline recorded")
    session = session_of(recs)
    if len(session) < 2:
        die("decide needs the baseline and at least one later round")
    latest = session[-1]
    if latest.get("decision"):
        die(f"{latest['round']} is already decided ({latest['decision']}); run and record the next round first")
    kept = [r for r in session[:-1] if r["round"] == "baseline" or r.get("decision") == "keep"]
    best = min((r for r in kept if r.get("score") is not None), key=lambda r: r["score"])
    at_limit = len(session) >= MAX_RUNS
    if latest.get("score") is None:
        decision, reason = "revert", f"{latest['round']} {latest['score_label']}"
    elif latest["score"] >= best["score"]:
        decision, reason = "revert", f"{latest['round']} scored {latest['score']}, which is not below the best kept run ({best['score']})"
    else:
        decision = "keep"
        saving = 1 - latest["score"] / best["score"]
        reason = f"{latest['round']} was kept: it saved {saving:.0%} against the best run"
    stop = False
    if at_limit:
        stop, reason = True, f"{MAX_RUNS} runs have been made, the limit for one session ({reason})"
    elif decision == "keep" and 1 - latest["score"] / best["score"] < MIN_SAVING:
        stop, reason = True, reason + f", which is under {MIN_SAVING:.0%}"
    cfg = cfg_of(w)
    cand, snap = candidate_of(w, cfg), os.path.join(w, "kept", "latest")
    if decision == "keep":
        if os.path.isdir(snap):
            shutil.rmtree(snap)
        shutil.copytree(cand, snap)
    else:
        shutil.rmtree(cand)
        shutil.copytree(snap if os.path.isdir(snap) else cfg["skill"], cand, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        ceil = load_json(os.path.join(w, "ceiling.json"), {})
        if ceil:
            write_ceiling(cand, ceil)   # the ceiling is kept even when the round it arrived with is reverted
        marks = load_json(os.path.join(w, "applied.json"), {})
        for k, v in marks.items():
            if v == f"applied in {latest['round']}":
                marks[k] = f"reverted after {latest['round']}"
        save_json(os.path.join(w, "applied.json"), marks)
    if decision == "keep" and not stop and not open_items(w):
        stop, reason = True, reason + "; nothing is left to change"
    recs[recs.index(latest)].update({"decision": decision, "stop": stop, "decision_reason": reason})
    write_records(w, recs)
    print(json.dumps({"decision": decision, "stop": stop, "reason": reason, "open_items": open_items(w)}, indent=1))
    sys.exit(3 if decision == "revert" else 0)


# ---------------------------------------------------------------- ceiling, check, mark, judge
def cmd_ceiling(a):
    w = os.path.abspath(a.work)
    cfg = cfg_of(w)
    recs = records(w)
    base = baseline_of(recs) or (reals_of(recs)[-1] if reals_of(recs) else None)
    if not base:
        die("record a baseline or a real run first; the ceiling is set from it")
    calls = base.get("main_tool_calls") or base["tool_calls"] or base["requests"]
    reqs = base.get("main_requests") or base["requests"]
    if not calls or not reqs:
        die("the baseline has no tool-call or request count to set a ceiling from")
    c = {"baseline_tool_calls": calls, "tool_calls": math.ceil(calls * CEILING_FACTOR),
         "max_turns": math.ceil(reqs * CEILING_FACTOR), "budget_usd": a.budget_usd, "set_from": base["round"],
         "enforced": "an instruction in Cowork; enforced by --max-turns in the Agent SDK or the command line"}
    write_ceiling(candidate_of(w, cfg), c)
    save_json(os.path.join(w, "ceiling.json"), c)
    print(f"ceiling of {c['tool_calls']} tool calls (max turns {c['max_turns']}) written to the candidate copy")


def cmd_check(a):
    w = os.path.abspath(a.work)
    cfg = cfg_of(w)
    if not baseline_of(records(w)):
        die("no baseline recorded; a quarterly check compares with it")
    rnd = f"check-{datetime.date.today()}"
    m = do_measure(a, cfg)
    save_json(os.path.join(w, "runs", rnd, "measure.json"), m)
    rec = make_record(w, cfg, rnd, a.skill, a.outcomes, "not_compared", "quarterly check: live inputs differ from the baseline's", None, None)
    kept = [r for r in session_of(records(w)) if r["round"] == "baseline" or r.get("decision") == "keep"]
    last = kept[-1]
    print(f"{rnd}: score {rec['score_label']} against the baseline; the last kept run ({last['round']}) scored {last.get('score')}")


def find_session(given=None):
    """This chat's session file. With more than one session file on the machine, the person or the model must name it."""
    if given:
        if not os.path.isfile(given):
            die(f"session file not found: {given}")
        return given
    files = [f for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")) if "/subagents/" not in f]
    if not files:
        die("no session record found under ~/.claude/projects; this chat keeps no session file, so a real run cannot be measured")
    if len(files) > 1:
        die("more than one session file was found; pass --transcript with this chat's file:\n  "
            + "\n  ".join(sorted(files, key=os.path.getmtime, reverse=True)[:10]))
    return files[0]


SYNTHETIC = ("[Request interrupted", "<local-command", "<command-", "<task-notification", "Caveat:", "This session is being continued")


def user_turns(path, skill=None):
    """The person's messages in the chat with their times (tool results, reminders, interrupts, compaction summaries
    and command output left out), and, when a skill name is given, a suggested window: from the message before the
    first tool call that touches the skill to the first message after the last one."""
    out, first_touch, last_touch = [], None, None
    for r in read_rows(path):
        if r.get("isSidechain"):
            continue
        msg = r.get("message") or {}
        if skill and r.get("type") == "assistant" and isinstance(msg, dict):
            for c in msg.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use" and skill in json.dumps(c.get("input") or {}):
                    first_touch = len(out) if first_touch is None else first_touch
                    last_touch = len(out)
        if r.get("type") != "user" or r.get("isMeta") or r.get("isCompactSummary"):
            continue
        c = msg.get("content")
        if isinstance(c, list):
            if any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
                continue
            c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
        text = re.sub(r"<system-reminder>.*?</system-reminder>", "", str(c or ""), flags=re.S).strip()
        if text and not text.startswith(SYNTHETIC):
            out.append({"n": len(out) + 1, "at": r.get("timestamp"), "text": text[:120].replace("\n", " ")})
    suggest = None
    if skill and first_touch is not None:
        suggest = {"start": max(first_touch, 1), "end": last_touch + 1 if last_touch + 1 <= len(out) else None}
    return out, suggest


def cmd_turns(a):
    path = find_session(a.transcript)
    turns, suggest = user_turns(path, a.skill)
    for t in turns:
        print(f"{t['n']:>3}  {t['at']}  {t['text']}")
    print(f"\nsession file: {path}")
    if a.skill:
        print(("suggested window: --start {start}".format(**suggest) + (f" --end {suggest['end']}" if suggest["end"] else
               " (no message after the run yet; use the message that asked for this assessment as --end)")) if suggest
              else f"no tool call in this chat touches {a.skill!r}; pick the window by hand")


def cmd_assess(a):
    """Measure a run that already happened in this chat, between two of the person's messages, and record it."""
    w = os.path.abspath(a.work)
    cfg = cfg_of(w)
    path = find_session(a.transcript)
    turns, _ = user_turns(path)
    if not 1 <= a.start <= len(turns):
        die(f"--start must be a message number from costkit turns (1 to {len(turns)})")
    if a.end is not None and not a.start < a.end <= len(turns):
        die(f"--end must be a later message number than --start, at most {len(turns)}")
    since = parse_ts(turns[a.start - 1]["at"])
    until = parse_ts(turns[a.end - 1]["at"]) if a.end else None
    m = measure_transcript(path, cfg, steps_of(cfg), since, until, main_only=True)
    rnd = f"real-{datetime.date.today()}"
    recs = records(w)
    n = 2
    while any(r["round"] == rnd for r in recs):
        rnd, n = f"real-{datetime.date.today()}-{n}", n + 1
    save_json(os.path.join(w, "runs", rnd, "measure.json"), m)
    save_run_findings(w, m)
    rec = make_record(w, cfg, rnd, a.skill, a.outcomes, "real run", None, a.reviewer_edits, None)
    cost = f"${m['cost_usd']:,.2f} at list prices" if m.get("cost_usd") is not None else f"no dollar figure ({', '.join(m.get('unpriced_models') or [])} has no price in prices.json)"
    print(f"{rnd}: {cost}; {rec['score_label']} against the first real run; {m['tool_calls']} tool calls, {m['requests']} requests, "
          f"models {m['models']}, {m['compactions']} compactions, {m['api_errors']} API errors; {len(m['runtime_findings'])} run findings")
    for st in m["by_step"][:8]:
        cost = "" if st.get("usd") is None else f"${st['usd']:>8,.2f}"
        print(f"  {st['share']:>6.1%}  {cost}  {st['tool_calls']:>4} calls  {st['minutes']:>6} min  {st['step']}")
    if m.get("app_cost_record"):
        print(f"app cost record for the whole chat (a cross-check that can lag): ${m['app_cost_record']['cost_usd']}")


def known_ids(w):
    base = load_json(os.path.join(w, "findings_run.json"), {})
    ids = {f["id"] for f in load_json(os.path.join(w, "findings_static.json"), {"findings": []})["findings"]}
    ids |= {f["id"] for f in base.get("findings", [])}
    return ids | {"lever:" + k for k in LEVERS}


def cmd_mark(a):
    w = os.path.abspath(a.work)
    unknown = [i for i in a.id if i not in known_ids(w)]
    if unknown:
        die(f"unknown id(s): {unknown}")
    if a.status == "applied" and not ROUND_RE.match(a.round or ""):
        die("--status applied needs --round (the round whose run will test the change)")
    p = os.path.join(w, "applied.json")
    j = load_json(p, {})
    for i in a.id:
        j[i] = f"applied in {a.round}" if a.status == "applied" else a.status
    save_json(p, j)
    print(f"marked {len(a.id)} item(s) as {a.status}")


def cmd_judge(a):
    w = os.path.abspath(a.work)
    if not (a.id in known_ids(w) or re.match(r"^output:(round\d+)$", a.id)):
        die(f"unknown id {a.id}")
    p = os.path.join(w, "judgments.json")
    j = load_json(p, {})
    j[a.id] = {"decision": a.decision, "note": a.note, "date": str(datetime.date.today())}
    save_json(p, j)
    print(f"logged judgment for {a.id}")


def cmd_review(a):
    """Save the whole review from one JSON file: a list of {kind, item, verdict, note, fix}. It replaces the last review,
    so a review always describes one run."""
    w = os.path.abspath(a.work)
    cfg_of(w)
    try:
        items = load_json(a.file)
    except ValueError as ex:
        die(f"{a.file} is not valid JSON: {ex}")
    if not isinstance(items, list) or not items:
        die(f"{a.file} must hold a list of items")
    seen = set()
    for i, x in enumerate(items, 1):
        if not isinstance(x, dict):
            die(f"item {i} is not an object")
        for k in ("kind", "item", "verdict", "note"):
            if not str(x.get(k) or "").strip():
                die(f"item {i} has no {k}")
        if x["kind"] not in ("run", "skill"):
            die(f"item {i}: kind must be run or skill")
        if x["verdict"] not in VERDICTS:
            die(f"item {i}: verdict must be one of {', '.join(VERDICTS)}")
        if x["verdict"] != "appropriate" and not str(x.get("fix") or "").strip():
            die(f"item {i} ({x['item']}): a verdict other than appropriate needs a fix")
        if (x["kind"], x["item"]) in seen:
            die(f"item {i}: {x['item']!r} appears twice")
        seen.add((x["kind"], x["item"]))
    save_json(os.path.join(w, "review.json"), [{k: x.get(k) for k in ("kind", "item", "verdict", "note", "fix")} | {"date": str(datetime.date.today())}
                                               for x in items])
    counts = {v: sum(x["verdict"] == v for x in items) for v in VERDICTS}
    print(f"saved {len(items)} items: " + ", ".join(f"{n} {v}" for v, n in counts.items() if n))


# ---------------------------------------------------------------- report
CSS = """:root{--bg:#fff;--fg:#1b1d21;--muted:#6b7078;--line:#e3e5e8;--accent:#0f766e;--callout:#eef7f6;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#15171a;--fg:#e7e9ec;--muted:#9aa0a8;--line:#2c3036;--accent:#5eead4;--callout:#16302d;--bad:#f97066}}
body{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif;max-width:900px;margin:0 auto;padding:24px 16px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.muted{color:var(--muted)}.callout{background:var(--callout);border-left:3px solid var(--accent);padding:10px 14px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.wrap{overflow-x:auto}.card{border:1px solid var(--line);border-radius:6px;padding:10px 14px;margin:10px 0}
.card p{margin:3px 0}.fail{color:var(--bad)}"""


def run_rows(rs, e, test):
    return "".join(
        f"<tr><td>{e(r['round'])}, {e(r['date'])}</td><td>{r['weighted_tokens_per_outcome']:,}</td>"
        f"<td>{'-' if r.get('est_cost_per_outcome_usd') is None else '$' + format(r['est_cost_per_outcome_usd'], ',.4f')}</td>"
        f"<td>{r['total_tokens_processed']:,}</td><td>{'-' if r['tool_calls'] is None else r['tool_calls']}</td>"
        f"<td>{'-' if r['cache_hit_rate'] is None else r['cache_hit_rate']}</td><td>{'-' if r['reviewer_edits'] is None else r['reviewer_edits']}</td>"
        + (f"<td>{e(r['output_check'])}</td>" if test else "")
        + f"<td class='{'' if r['score'] is not None else 'fail'}'>{e(r['score_label'])}" + (" (dollar basis)" if r.get("score_basis") == "dollars" else "") + "</td>"
        + (f"<td>{e(r.get('decision', 'baseline' if r['round'] == 'baseline' else '-'))}</td>" if test else "") + "</tr>" for r in rs)


def cmd_report(a):
    w = os.path.abspath(a.work)
    cfg = cfg_of(w)
    recs = records(w)
    reals = reals_of(recs)
    review = load_json(os.path.join(w, "review.json"), [])
    if not baseline_of(recs) and not reals and not review:
        die("no runs recorded and no review logged")
    e = html.escape
    static = load_json(os.path.join(w, "findings_static.json"), {"findings": []})
    judg = load_json(os.path.join(w, "judgments.json"), {})
    ceil = load_json(os.path.join(w, "ceiling.json"), {})
    marks = load_json(os.path.join(w, "applied.json"), {})
    run_f = load_json(os.path.join(w, "findings_run.json"), {})
    base = baseline_of(recs)
    session = session_of(recs) if base else []
    checks = [r for r in recs if r["round"].startswith("check-")]
    unit = e(cfg["outcome_unit"])
    s = []
    if reals:
        first, last = reals[0], reals[-1]
        s.append(f"The latest real run ({e(last['round'])}) cost "
                 + (f"${last['est_cost_per_outcome_usd']:,.2f} per {unit} at list prices" if last.get("est_cost_per_outcome_usd") is not None
                    else f"{last['weighted_tokens_per_outcome']:,} weighted tokens per {unit} (no dollar figure: {e(', '.join(last.get('unpriced_models') or []))} has no price)")
                 + ("." if last is first else (f", and scores {last['score']} against the first real run ({e(first['round'])})." if last["score"] is not None
                    else f". It was not scored against the first real run ({e(first['round'])}): {e(last['score_label'])}.")))
        top = (last.get("by_step") or [])[:1]
        if top:
            s.append(f"The most expensive step was {e(top[0]['step'])}, at {top[0]['share']:.0%} of the run's "
                     + ("cost." if top[0].get("usd") is not None else "weighted tokens."))
    if base:
        kept = [r for r in session if (r["round"] == "baseline" or r.get("decision") == "keep") and r.get("score") is not None]
        best = min(kept, key=lambda r: r["score"])
        stop_reason = next((r.get("decision_reason") for r in reversed(session) if r.get("stop")), None)
        s.append("The test baseline cost " + (f"${base['est_cost_per_outcome_usd']:,.2f}" if base.get("est_cost_per_outcome_usd") is not None
                                              else f"{base['weighted_tokens_per_outcome']:,} weighted tokens") + f" per {unit}. "
                 + (f"The best kept test run, {e(best['round'])}, scores {best['score']} against the baseline's 100, a reduction of {100 - best['score']:.0f}%."
                    if best is not base else "No change round has improved on the baseline yet.")
                 + (f" The loop stopped because {e(stop_reason)}." if stop_reason else ""))
    if recs:
        s.append(f"The skill has a ceiling of {ceil['tool_calls']} tool calls, which is {e(ceil['enforced'])}." if ceil else "The skill has no cost ceiling yet.")
    else:   # nothing measured: a ceiling needs a measured run, so its finding cannot be acted on here
        static["findings"] = [f for f in static["findings"] if f["check"] != "S11"]
    if checks:
        s.append(f"The latest quarterly test check ({e(checks[-1]['round'][6:])}) scored {e(checks[-1]['score_label'])}.")
    th_test = ("<tr><th>Run</th><th>Weighted tokens per outcome</th><th>List-price cost per outcome</th><th>Tokens processed</th><th>Tool calls</th>"
               "<th>Cache hit rate</th><th>Reviewer edits</th><th>Output check</th><th>Score</th><th>Decision</th></tr>")
    th_real = ("<tr><th>Run</th><th>Weighted tokens per outcome</th><th>List-price cost per outcome</th><th>Tokens processed</th><th>Tool calls</th>"
               "<th>Cache hit rate</th><th>Reviewer edits</th><th>Score</th></tr>")
    tables = ""
    if reals:
        tables += ("<h3>Real runs (measured from the chat where the skill ran; scored against the first real run)</h3>"
                   f"<div class=wrap><table>{th_real}{run_rows(reals, e, False)}</table></div>")
    if base:
        tables += ("<h3>Test runs (run by the optimizer, read-only; scored against the test baseline)</h3>"
                   f"<div class=wrap><table>{th_test}{run_rows(session + checks, e, True)}</table></div>")
    steps = run_f.get("by_step") or []
    step_rows = "".join(f"<tr><td>{e(st['step'])}</td><td>{'-' if st.get('usd') is None else '$' + format(st['usd'], ',.2f')}</td>"
                        f"<td>{st['weighted_tokens']:,}</td><td>{st['share']:.0%}</td><td>{st['tool_calls']}</td>"
                        f"<td>{st['minutes']}</td><td>{st['errors']}</td></tr>" for st in steps)
    src_meas = {}
    if run_f.get("from"):
        latest = reals[-1]["round"] if reals else "baseline"
        src_meas = load_json(os.path.join(w, "runs", latest, "measure.json"), {})
    app = src_meas.get("app_cost_record")
    # One scale for every estimate: weighted tokens per run at the main model's price ratios, then dollars. A static
    # finding's tokens sit in the context, so they are written to the cache once and read on every later request.
    mm = run_f.get("main_model")
    wr = weights_for(mm, cfg)
    reqs = run_f.get("main_requests") or 1
    in_price = ((load_prices().get("models") or {}).get(mm or "") or {}).get("input")
    for f in static["findings"]:
        f["est_weighted"] = round(f["est_tokens_per_run"] * (wr["cache_write_5m"] + (reqs - 1) * wr["cache_read"])) if run_f else f["est_tokens_per_run"]
    for f in run_f.get("findings", []):
        f["est_weighted"] = f["est_tokens_per_run"]
    findings = sorted(static["findings"] + run_f.get("findings", []), key=lambda f: -f["est_weighted"])
    cards = []
    for f in findings:
        j = judg.get(f["id"])
        st = marks.get(f["id"], "not applied") + ("; no longer found by the latest check" if f.get("resolved") else "")
        if j and j["decision"] == "not a finding":
            st = "not a finding (model judgment)"
        found = "script, then model judgment" if j else ("script; needs model judgment, not yet made" if f["needs_judgment"] else "script")
        cards.append(f"<div class=card><p><b>{e(f['id'])}: {e(f['recommendation'])}</b></p><p>Where: {e(f['where'])}.</p>"
                     f"<p>Evidence: {e(f['evidence'])}.</p><p>Estimated saving: "
                     + ("not estimated by the script" if not f["est_weighted"] else
                        (f"about ${f['est_weighted'] * in_price / 1e6:,.2f} per run ({f['est_weighted']:,} weighted tokens)" if in_price and run_f
                         else f"{f['est_weighted']:,} tokens per run"))
                     + f".</p><p>Status: {e(st)}.</p>"
                     f"<p>Found by: {found}" + (f" ({e(j['note'])})" if j else "") + ".</p></div>")
    lv = run_f.get("levers", {})
    lever_rows = "".join(f"<tr><td>{e(k.replace('_', ' '))}</td><td>{e(judg.get('lever:' + k, {}).get('decision', v['status']))}"
                         + (f"; {e(marks['lever:' + k])}" if 'lever:' + k in marks else "") + f"</td><td>{e(v['evidence'])}"
                         + (f"; {e(judg['lever:' + k]['note'])}" if 'lever:' + k in judg else "") + "</td></tr>" for k, v in lv.items())
    not_tested = []
    if not lv:
        not_tested.append("Run-time checks (wasted calls, large results, caching, cost by step) were not run, because no run was measured from a transcript.")
    if not cfg.get("account"):
        not_tested.append("No account file with a step map was given, so cost by step is grouped by tool name only.")
    if any(r["output_check"] == "not_compared" for r in session):
        not_tested.append("Some test rounds were not compared with the baseline's output; they cannot be kept.")
    if all(r["reviewer_edits"] is None for r in session + reals):
        not_tested.append("Reviewer edits were not recorded, so review effort is not part of any gate.")
    known = set((load_prices().get("models") or {}))
    unpriced = sorted({mdl for r in reals + session for mdl in r["models"]} - known)
    if unpriced:
        not_tested.append(f"No list price is set for {', '.join(unpriced)}, so dollar figures are missing for runs that used it; add it to prices.json.")
    if base:
        not_tested.append("Test runs could read connected sources but not write to them, so steps that post or submit were not exercised in those runs.")
    if cfg.get("mode") == "assess" and not base:
        not_tested.append("This was an assessment only: no change was tested, so the estimated savings are not yet measured.")
    nxt = datetime.date.fromisoformat(recs[-1]["date"] if recs else str(datetime.date.today())) + datetime.timedelta(days=RECHECK_DAYS)
    rv = sorted(review, key=lambda x: (VERDICTS.index(x["verdict"]), x["kind"]))
    review_rows = "".join(f"<tr><td>{e(x['kind'])}</td><td>{e(x['item'])}</td><td>{e(x['verdict'])}</td><td>{e(x['note'])}</td>"
                          f"<td>{e(x.get('fix') or '')}</td></tr>" for x in rv)
    if review:
        counts = {v: sum(x["verdict"] == v for x in review) for v in VERDICTS}
        s.append(f"The qualitative review ({e(review[0]['date'])}) rated {counts['appropriate']} of {len(review)} items appropriate"
                 + "".join(f", {n} {v}" for v, n in counts.items() if n and v != "appropriate") + ".")
    # A page with no measured run (a claude.ai chat, or a review alone) leaves out every section about cost.
    title = "Skill cost report" if recs else "Skill review"
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{title}</title><style>{CSS}h3{{font-size:15px;margin:18px 0 6px}}</style></head><body>
<h1>{title}: {e(os.path.basename(cfg['skill']))}</h1>
<p class=muted>Mode: {e(cfg.get('mode', 'optimize'))}. Request: {e(cfg['request'])}. {f'Outcome unit: {unit}. ' if recs else ''}Environment: {e(cfg['env'])}.</p>
<h2>Summary</h2><div class=callout>{' '.join(s)}</div>
"""
    if recs:
        page += f"""<h2>Measurements by run</h2>
<p>Each request is priced at list price from its own usage fields: its model, cache writes and reads, fast mode, US-only inference, Haiku's long-prompt tier and web searches. The score is the cost per outcome as an index against the reference run's 100, with both runs priced at today's prices.json, so a price change moves neither side; lower is better. Real runs and test runs are scored separately, because a real run includes the interview, corrections and delivery steps that a test run leaves out. Weighted tokens (each model's tokens in its own input-token units) are shown for reference. (source: transcript usage fields, read by costkit; prices: {e(load_prices().get('source') or 'prices.json')})</p>
{tables}
<h2>Cost by step</h2>
<p>Each request's cost is counted under the step of the tool call it made, and a sub-agent's cost under the step that started it. Shares are in {e(run_f.get('by_step_unit') or 'usd')}. Minutes are tool time only; the model's own time between calls is not split by step. (source: {e(run_f.get('from') or 'not measured')})</p>
<div class=wrap><table><tr><th>Step</th><th>List-price cost</th><th>Weighted tokens</th><th>Share</th><th>Tool calls</th><th>Tool minutes</th><th>Errors</th></tr>{step_rows or '<tr><td colspan=7>Not measured.</td></tr>'}</table></div>
{(f"<p>The app's own cost record for the whole chat shows ${app['cost_usd']} (" + ", ".join(f"{e(k)} ${v}" for k, v in (app.get('by_model') or {}).items()) + "). It covers the whole chat, is written from time to time and can include usage that no transcript shows, so it is a cross-check, not the figure above.</p>") if app else ""}
{f"<p>Context compactions: {src_meas.get('compactions', 0)}. API errors: {src_meas.get('api_errors', 0)}.</p>" if src_meas else ""}
"""
    page += f"""{f"<h2>Qualitative review</h2><p>The model's judgment of each step of the run and each part of the skill, against reference/review.md: whether it was needed, in the right place and the right size. Items that need a change come first.</p><div class=wrap><table><tr><th>Kind</th><th>Item</th><th>Verdict</th><th>Why</th><th>Fix</th></tr>{review_rows}</table></div>" if review else ""}
<h2>Findings, ranked by estimated tokens saved per run</h2>{''.join(cards) or '<p>No findings.</p>'}
"""
    page += f"""<h2>How the skill runs</h2><div class=wrap><table><tr><th>Lever</th><th>Status</th><th>Evidence</th></tr>{lever_rows or '<tr><td colspan=3>Not measured.</td></tr>'}</table></div>
<p>Batching and prompt caching are API features. In Cowork and the chat app, caching is automatic and the lever is not breaking it; batching needs a script that sends the per-item step through the Batch API.</p>
<h2>Controls</h2><p>{(f"Ceiling: {ceil['tool_calls']} tool calls, or {ceil['max_turns']} turns through the SDK or command line. It is {e(ceil['enforced'])}.") if ceil else "No ceiling has been set."}</p>
<h2>Not tested</h2><ul>{''.join(f'<li>{e(x)}</li>' for x in not_tested) or '<li>Nothing outside the scope above.</li>'}</ul>
<h2>Next check</h2><p>Assess the next real run on or after {nxt}, or sooner if a new model ships, in the chat where that run happens. It is scored against the first real run.</p>
""" if recs else ("<h2>Cost</h2><p>Cost was not measured: this chat keeps no usage records and cannot start "
                                         "a test run. To measure cost and test changes, run this skill in Claude Code or Cowork.</p>")
    page += "</body></html>"
    out = os.path.join(w, "report.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("init"); p.add_argument("work"); p.add_argument("--skill", required=True); p.add_argument("--request", required=True)
    p.add_argument("--outcome-unit", required=True); p.add_argument("--env", choices=["cowork", "claude-code", "sdk", "chat"])
    p.add_argument("--mode", choices=["assess", "optimize"], required=True); p.add_argument("--account"); p.add_argument("--force", action="store_true")
    p.add_argument("--fresh-candidate", action="store_true", help="with --force: archive the candidate copy too and start from the original")
    p = sp.add_parser("static"); p.add_argument("skill_dir"); p.add_argument("--save"); p.add_argument("--env", default="cowork")

    def src(p):
        g = p.add_mutually_exclusive_group(required=True)
        g.add_argument("--agent-id"); g.add_argument("--transcript"); g.add_argument("--sdk-result")
    p = sp.add_parser("measure"); src(p); p.add_argument("--save"); p.add_argument("--round")
    p = sp.add_parser("compare-outputs"); p.add_argument("out_a"); p.add_argument("out_b"); p.add_argument("--save"); p.add_argument("--round")
    p = sp.add_parser("record"); p.add_argument("work"); p.add_argument("--round", required=True); p.add_argument("--skill", required=True)
    p.add_argument("--outcomes", type=int, required=True); p.add_argument("--output-check", choices=["not_compared"]); p.add_argument("--reason")
    p.add_argument("--reviewer-edits", type=int); p.add_argument("--tested-change", choices=["model", "effort"]); p.add_argument("--force", action="store_true")
    p = sp.add_parser("decide"); p.add_argument("work")
    p = sp.add_parser("ceiling"); p.add_argument("work"); p.add_argument("--budget-usd", type=float)
    p = sp.add_parser("check"); p.add_argument("work"); p.add_argument("--skill", required=True); p.add_argument("--outcomes", type=int, required=True); src(p)
    sp.add_parser("env")
    p = sp.add_parser("turns"); p.add_argument("--transcript"); p.add_argument("--skill", help="the target skill's folder name, to suggest the window")
    p = sp.add_parser("assess"); p.add_argument("work"); p.add_argument("--skill", required=True); p.add_argument("--outcomes", type=int, required=True)
    p.add_argument("--start", type=int, required=True); p.add_argument("--end", type=int); p.add_argument("--transcript"); p.add_argument("--reviewer-edits", type=int)
    p = sp.add_parser("mark"); p.add_argument("work"); p.add_argument("--id", nargs="+", required=True)
    p.add_argument("--status", choices=STATUSES, required=True); p.add_argument("--round")
    p = sp.add_parser("judge"); p.add_argument("work"); p.add_argument("--id", required=True); p.add_argument("--decision", required=True); p.add_argument("--note", required=True)
    p = sp.add_parser("review"); p.add_argument("work"); p.add_argument("--file", required=True)
    p = sp.add_parser("report"); p.add_argument("work")
    a = ap.parse_args()
    if getattr(a, "budget_usd", None) is not None and a.budget_usd <= 0:
        die("--budget-usd must be above 0")
    {"init": cmd_init, "static": cmd_static, "measure": cmd_measure, "compare-outputs": cmd_compare, "record": cmd_record,
     "decide": cmd_decide, "ceiling": cmd_ceiling, "check": cmd_check, "turns": cmd_turns, "env": cmd_env, "assess": cmd_assess, "mark": cmd_mark, "judge": cmd_judge, "review": cmd_review, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
