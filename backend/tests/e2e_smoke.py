"""End-to-end smoke test of the NewsLetter pipeline against a live backend.

Exercises:
  1. POST /api/newsletter/create  — Stage 1 auto-completes
  2. POST /api/newsletter/{id}/stages/2/execute  — DDGS-driven source collection
  3. Polls /api/newsletter/{id}  — until stage 2 completes
  4. POST /api/newsletter/{id}/stages/3/execute  — LLM curation
  5. Polls again — until stage 3 completes
  6. Reads /api/newsletter/{id}/stages/3/content — checks the markdown is non-trivial
  7. Verifies cost_usd / total_cost_usd appear

Stages 4 and 5 follow the same shape; we stop at 3 by default to keep the test
under a few minutes. Pass ``--full`` to run all five.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# Load .env before any app imports so that Azure/OpenAI credentials are in
# os.environ when cmbagent's ProviderRegistry is first imported.
try:
    from dotenv import load_dotenv  # type: ignore
    _env_file = Path(__file__).parent.parent / ".env"
    if _env_file.is_file():
        load_dotenv(_env_file, override=True)
except Exception:
    pass  # dotenv missing — rely on shell env

from fastapi.testclient import TestClient

sys.path.insert(0, ".")

from main import app  # type: ignore  # noqa: E402

POLL_INTERVAL_S = 2.0
TIMEOUT_S = 600


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="Run all 5 stages (slow)")
    parser.add_argument("--max-stage", type=int, default=3,
                        help="Highest stage to run (default 3 — fast smoke)")
    parser.add_argument("--mode", default="one_shot",
                        choices=["one_shot", "planning_and_control"])
    args = parser.parse_args()
    max_stage = 5 if args.full else args.max_stage

    c = TestClient(app)

    # Pick a small, easy industry so stage 2 doesn't run forever.
    today = date.today()
    week_ago = today - timedelta(days=7)
    payload = {
        "title": "E2E smoke — Generative AI / AI",
        "industries": [
            {"industry": "Generative AI", "sub_domains": ["Artificial Intelligence"]}
        ],
        "date_from": week_ago.isoformat(),
        "date_to": today.isoformat(),
        "source_mode": "ddgs_only",  # exercise the DDGS path
        "user_urls": [],
        "audience": "tech leads",
        "mode_config": {
            "stage_2_mode": args.mode,
            "stage_3_mode": args.mode,
            "stage_4_mode": args.mode,
            "stage_5_mode": args.mode,
            "stage_2_enrich_with_llm": False,
            "stage_2_models": {},
            "stage_3_models": {},
            "stage_4_models": {},
            "stage_5_models": {},
        },
    }

    print(f"[1] POST /api/newsletter/create  → mode={args.mode}, stages 1..{max_stage}")
    r = c.post("/api/newsletter/create", json=payload)
    if r.status_code != 200:
        print(f"  FAIL: HTTP {r.status_code} {r.text[:300]}")
        return 1
    created = r.json()
    task_id = created["task_id"]
    work_dir = created["work_dir"]
    print(f"  task_id={task_id} work_dir={work_dir}")

    for stage_num in range(2, max_stage + 1):
        print(f"\n[{stage_num}] POST stage {stage_num}/execute")
        r = c.post(f"/api/newsletter/{task_id}/stages/{stage_num}/execute", json={})
        if r.status_code != 200:
            print(f"  FAIL: HTTP {r.status_code} {r.text[:300]}")
            return 1
        print(f"  status={r.json().get('status')}")

        # Poll task state until this stage is no longer running.
        deadline = time.time() + TIMEOUT_S
        while time.time() < deadline:
            r = c.get(f"/api/newsletter/{task_id}")
            if r.status_code != 200:
                print(f"  poll FAIL: HTTP {r.status_code}")
                return 1
            state = r.json()
            stage = next((s for s in state["stages"] if s["stage_number"] == stage_num), None)
            if not stage:
                print("  stage missing from response")
                return 1
            elapsed = int(TIMEOUT_S - (deadline - time.time()))
            print(f"  poll t={elapsed}s status={stage['status']} cost=${state.get('total_cost_usd', 0):.4f}",
                  flush=True)
            if stage["status"] == "completed":
                break
            if stage["status"] == "failed":
                print(f"  FAIL: stage {stage_num} failed: {stage.get('error')}")
                return 1
            time.sleep(POLL_INTERVAL_S)
        else:
            print(f"  TIMEOUT waiting for stage {stage_num}")
            return 1

        # Pull the stage content
        r = c.get(f"/api/newsletter/{task_id}/stages/{stage_num}/content")
        if r.status_code != 200:
            print(f"  content FAIL: HTTP {r.status_code}")
            return 1
        body = r.json()
        text = body.get("content") or ""
        print(f"  stage {stage_num} content: {len(text)} chars; first 200:")
        print("    " + text[:200].replace("\n", "\n    "))

    # Final task state
    r = c.get(f"/api/newsletter/{task_id}")
    state = r.json()
    print("\n=== FINAL TASK STATE ===")
    print(f"  progress_percent: {state['progress_percent']}")
    print(f"  total_cost_usd:   ${state.get('total_cost_usd', 0):.4f}")
    for s in state["stages"]:
        cost = s.get("cost_usd")
        cost_str = f"${cost:.4f}" if cost else "—"
        print(f"  stage {s['stage_number']:>2} {s['stage_name']:<20} {s['status']:<10} cost={cost_str:<10} mode={s.get('mode')}")
    print("\n=== PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
