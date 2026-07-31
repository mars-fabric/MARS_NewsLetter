"""One-shot end-to-end experiment driver for the newsletter pipeline.

Drives create → stage2 → gate B → stage3 → stage4 → stage5 over HTTP using the
34 user-provided links in `user_links_only` mode with executive_grade on.
Prints a quality summary at the end. Safe to delete afterwards.
"""

from __future__ import annotations

import sys
import time

import httpx

BASE = "http://localhost:5678/api/newsletter"

USER_URLS = [
    "https://openai.com/index/health-in-chatgpt",
    "https://openai.com/index/building-ai-infrastructure-with-the-effingham-county-community",
    "https://openai.com/index/how-news-organizations-are-using-ai",
    "https://openai.com/index/advancing-the-next-era-of-national-science",
    "https://openai.com/index/introducing-openai-presence",
    "https://openai.com/index/ntt-data",
    "https://openai.com/index/introducing-chatgpt-small-business-program",
    "https://openai.com/index/hugging-face-model-evaluation-security-incident",
    "https://openai.com/index/david-velez-robin-vince-join-openai-boards",
    "https://openai.com/index/safety-alignment-long-horizon-models",
    "https://blogs.nvidia.com/blog/ai-summit-korea-partners-and-nvidia/",
    "https://blogs.nvidia.com/blog/naval-postgraduate-school-dgx-ai-supercomputer",
    "https://blogs.nvidia.com/blog/wistron-manufacturing-texas",
    "https://blogs.nvidia.com/blog/vera-rubin",
    "https://blogs.nvidia.com/blog/siggraph-news-2026",
    "https://blogs.nvidia.com/blog/bristol-myers-squibb-building-life-science-industrys-most-advanced-ai-factory-on-nvidia-vera-rubin",
    "https://www.databricks.com/blog/how-fda-built-ai-platform-85-its-staff-now-use-daily",
    "https://www.databricks.com/blog/permission-isnt-purpose-intent-based-authorization-omnigent",
    "https://www.databricks.com/blog/provisioning-agentic-era-how-databricks-built-self-serve-infrastructure-vending-machine",
    "https://www.databricks.com/blog/why-frontier-data-agent-outperforms-general-coding-agents-quality-and-cost",
    "https://www.databricks.com/blog/connect-amazon-s3-data-databricks-delegated-iam-permissions",
    "https://www.databricks.com/blog/introducing-ai-spend-controls-unity-ai-gateway",
    "https://www.databricks.com/blog/simplify-ai-agent-orchestration-lakebase-postgres",
    "https://www.databricks.com/blog/last-mile-first-party-data-great-marketing",
    "https://www.databricks.com/blog/how-dow-built-carbon-footprint-ledger-databricks-accelerate-sustainability-scale",
    "https://www.databricks.com/blog/why-rd-data-belongs-lakehouse-and-why-agents-need-it-there",
    "https://huggingface.co/blog/nunchaku-diffusers",
    "https://huggingface.co/blog/grabette",
    "https://deepmind.google/blog/accelerating-the-frontiers-of-scientific-discovery-googles-40m-commitment-to-the-genesis-mission",
    "https://deepmind.google/blog/introducing-gemini-36-flash-35-flash-lite-and-35-flash-cyber",
    "https://blog.google/products-and-platforms/platforms/android/galaxy-unpacked-2026",
    "https://www.microsoft.com/en-us/microsoft-cloud/blog/2026/07/21/the-ai-strategy-roadmap-five-drivers-of-successful-ai-transformation",
    "https://www.microsoft.com/en-us/microsoft-cloud/blog/2026/07/23/ai-appreciation-day-impact-through-action",
]

SECTIONS = [
    {"title": "Executive Summary", "depth": "standard", "guidance": "The most important developments across the provided sources."},
    {"title": "Top Story of the Period", "depth": "deep", "guidance": "The single most significant development."},
    {"title": "Releases & Announcements", "depth": "standard", "guidance": "Product / platform launches and feature updates."},
    {"title": "Trend Intelligence", "depth": "deep", "guidance": "Emerging cross-vendor trends and market signals."},
    {"title": "Focus Topic Deep Dive", "depth": "deep", "guidance": "AI infrastructure and agentic platforms."},
    {"title": "Sources", "depth": "light", "guidance": "Consolidated list of all cited sources."},
]


def _p(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    client = httpx.Client(timeout=None)

    create_body = {
        "title": "AI Industry Intelligence — Client Edition",
        "industries": [{"industry": "Generative AI", "sub_domains": ["Artificial Intelligence", "Enterprise Platforms"]}],
        "date_from": "2026-07-01",
        "date_to": time.strftime("%Y-%m-%d"),
        "source_mode": "user_links_only",
        "user_urls": USER_URLS,
        "analyze_user_links": True,
        "executive_grade": True,
        "audience": "CEOs, CTOs and senior technology leaders",
        "focus_prompt": "Executive-grade weekly intelligence brief on AI industry developments for C-suite readers.",
    }

    _p("Creating task…")
    r = client.post(f"{BASE}/create", json=create_body)
    r.raise_for_status()
    task_id = r.json()["task_id"]
    _p(f"task_id={task_id}")

    def execute(stage: int) -> None:
        _p(f"Executing stage {stage}…")
        t0 = time.time()
        resp = client.post(f"{BASE}/{task_id}/stages/{stage}/execute", json={})
        resp.raise_for_status()
        # Stage runs in the background — poll the task state until it settles.
        while True:
            time.sleep(10)
            st = client.get(f"{BASE}/{task_id}").json()
            stages = {s["stage_number"]: s["status"] for s in st.get("stages", [])}
            status = stages.get(stage, "?")
            if status in ("completed", "failed", "error"):
                _p(f"stage {stage} {status} in {time.time()-t0:.0f}s")
                if status != "completed":
                    raise SystemExit(f"stage {stage} ended with status={status}")
                return
            _p(f"  … stage {stage} status={status} ({time.time()-t0:.0f}s elapsed)")

    execute(2)
    execute(3)

    _p("Saving Gate B template…")
    r = client.post(f"{BASE}/{task_id}/gate/template", json={
        "sections": SECTIONS,
        "tone": "authoritative, concise, implication-led",
        "audience": "CEOs, CTOs and senior technology leaders",
    })
    r.raise_for_status()

    execute(4)
    execute(5)

    _p("Fetching final content…")
    c = client.get(f"{BASE}/{task_id}/stages/5/content")
    c.raise_for_status()
    data = c.json()
    _p(f"Stage 5 files: {data.get('files')}")
    _p(f"work_dir task_id: {task_id}")
    print("\n===== SUMMARY =====")
    print(f"task_id: {task_id}")
    print("Inspect: backend/cmbdir/sessions/newsletter/tasks/%s/stage_5/" % task_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
