#!/usr/bin/env python3
"""Install these skills where non-Claude agents discover them.

The skills in this repo use the open [Agent Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills)
format (skills/<name>/SKILL.md). Claude Code installs them via the plugin
marketplace, reading from `skills/`. Other standard-compliant agents — OpenAI
Codex, Gemini CLI, Cursor, VS Code, and ~30 others — discover skills from a
`.agents/skills/` directory, the shared cross-tool alias.

The catch: those tools look in `.agents/skills/`, not `skills/`, and several
(notably Gemini CLI, GitHub issue #16247) do NOT follow symlinks. So we can't
symlink one tree to both paths — we copy real files.

This script copies the canonical `skills/` tree into a target skills directory.
The canonical source stays `skills/`; the copy is disposable (and .gitignored
at the default in-repo destination).

Usage:
    python3 tools/sync_skills.py                 # -> ./.agents/skills (this repo's workspace)
    python3 tools/sync_skills.py --user          # -> ~/.agents/skills (all your repos)
    python3 tools/sync_skills.py --dest DIR       # -> DIR (e.g. ~/.claude/skills)
    python3 tools/sync_skills.py ar-ap-aging close-pulse   # only these skills
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

IGNORE = shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc")


def available_skills() -> list[str]:
    return sorted(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "skills",
        nargs="*",
        help="Skill names to sync (default: all). See skills/ for the list.",
    )
    dest = parser.add_mutually_exclusive_group()
    dest.add_argument(
        "--user",
        action="store_true",
        help="Install to ~/.agents/skills (discovered across all your repos).",
    )
    dest.add_argument(
        "--dest",
        type=Path,
        help="Explicit destination skills directory (e.g. ~/.claude/skills).",
    )
    args = parser.parse_args()

    if args.dest is not None:
        target = args.dest.expanduser()
    elif args.user:
        target = Path.home() / ".agents" / "skills"
    else:
        target = REPO_ROOT / ".agents" / "skills"

    all_skills = available_skills()
    if not all_skills:
        print("No skills found under skills/*/SKILL.md", file=sys.stderr)
        return 1

    selected = args.skills or all_skills
    unknown = [s for s in selected if s not in all_skills]
    if unknown:
        print(f"Unknown skill(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"Available: {', '.join(all_skills)}", file=sys.stderr)
        return 1

    target.mkdir(parents=True, exist_ok=True)
    for name in selected:
        src = SKILLS_DIR / name
        dst = target / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=IGNORE)

    print(f"Synced {len(selected)} skill(s) -> {target}")
    print("Connect the Numeric MCP, then your agent will discover them automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
