"""
scrape_arc_templates.py — download ARC docs `.md` companions + OpenAPI spec.

ARC's docs site (Mintlify) exposes a `.md` view of every page. We download all
of them into `docs/_templates/` to use as adaptation references when authoring
HLG's own pages.

These files are NOT redistributed; they are reference templates only and live
under .gitignore. They give us:
  - exact Mintlify component usage (CardGroup, Note, Steps, Tabs, code-block tags)
  - the "Documentation Index" blockquote pattern
  - copy tone and section ordering per page

Run:
    uv run python scripts/scrape_arc_templates.py
"""
from __future__ import annotations
import ssl
import sys
import time
import urllib.request
from pathlib import Path

# Some corporate / sandbox environments inject a self-signed root cert into the
# chain. Disable verification: we are not transmitting credentials, and the
# downloaded files are reference templates, not executable payloads.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "docs" / "_templates"

ARC_PAGES = [
    "actions",
    "add_game",
    "agents-quickstart",
    "api-keys",
    "api-reference/commands/execute-complex-action-requires-xy",
    "api-reference/commands/execute-simple-action-1",
    "api-reference/commands/execute-simple-action-2",
    "api-reference/commands/execute-simple-action-3",
    "api-reference/commands/execute-simple-action-4",
    "api-reference/commands/execute-simple-action-5",
    "api-reference/commands/execute-simple-action-7",
    "api-reference/commands/start-or-reset-game-instance",
    "api-reference/games/list-available-games",
    "api-reference/scorecards/close-scorecard",
    "api-reference/scorecards/open-scorecard",
    "api-reference/scorecards/retrieve-scorecard",
    "api-reference/scorecards/retrieve-scorecard-one-game",
    "arc-agi-3",
    "arc-prize-2026",
    "available-games",
    "benchmarking-agent",
    "changelog",
    "contributing",
    "create-agent",
    "edit_games",
    "feature-requests",
    "full-play-test",
    "game-schema",
    "index",
    "llm_agents",
    "local-vs-online",
    "methodology",
    "partner_templates/agentops",
    "partner_templates/anthropic",
    "partner_templates/huggingface",
    "partner_templates/langchain",
    "rate_limits",
    "recordings",
    "rest_overview",
    "scorecards",
    "swarms",
    "toolkit/arc_agi",
    "toolkit/close-scorecard",
    "toolkit/competition_mode",
    "toolkit/create-scorecard",
    "toolkit/environment_wrapper",
    "toolkit/get-scorecard",
    "toolkit/list-actions",
    "toolkit/list-games",
    "toolkit/listen_and_serve",
    "toolkit/minimal",
    "toolkit/overview",
    "toolkit/render-games",
    "toolkit/submit-action",
    "vocabulary",
]

EXTRA_FILES = [
    ("llms.txt",                          "llms.txt"),
    ("arc3v1.yaml",                       "arc3v1.yaml"),
    ("api-reference/openapi.json",        "openapi.json"),
]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as r:
        return r.read()


def main() -> int:
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    base = "https://docs.arcprize.org"
    ok = 0
    fail = 0

    for slug in ARC_PAGES:
        url = f"{base}/{slug}.md"
        out = TEMPLATES_DIR / f"{slug}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = fetch(url)
            out.write_bytes(data)
            ok += 1
            print(f"  [ok]   {slug}.md  ({len(data)} bytes)")
        except Exception as exc:
            fail += 1
            print(f"  [fail] {slug}.md  -> {exc}", file=sys.stderr)
        time.sleep(0.05)

    for slug, fname in EXTRA_FILES:
        url = f"{base}/{slug}"
        out = TEMPLATES_DIR / fname
        try:
            data = fetch(url)
            out.write_bytes(data)
            ok += 1
            print(f"  [ok]   {fname}  ({len(data)} bytes)")
        except Exception as exc:
            fail += 1
            print(f"  [fail] {fname}  -> {exc}", file=sys.stderr)
        time.sleep(0.05)

    print(f"\nDone: {ok} ok, {fail} fail. Templates in {TEMPLATES_DIR}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
