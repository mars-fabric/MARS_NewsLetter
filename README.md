# MARS-NewsLetter

Production-grade industry newsletter generator. Five-stage pipeline that turns
a taxonomy-driven setup (industries × sub-domains, source mode, style, agent
strategy) into a reviewed, link-validated, PDF-ready newsletter.

The codebase blends three sibling MARS products:

* **MARS-AIWeekly** — supplied the 4-stage research pipeline shape (collection
  → curation → generation → review). NewsLetter adds an explicit **Setup**
  stage on top, giving 5 stages.
* **MARS-PaperPulse** — supplied the FastAPI scaffolding, structured logging
  (structlog with task/run context binding), DB-backed task state via
  cmbagent's ORM, WebSocket-streamed console output, and the Next.js UI
  shell.
* **MARS-NewsPulse** — supplied the defensive patterns:
  `_call_llm_with_antirefusal`, `_generate_rescue_seed`, per-section
  `_build_*_fallback`, plus the multi-backend Markdown→PDF renderer
  (WeasyPrint with an fpdf2 fallback).

## The 5 stages

| # | Stage | Purpose | Backed by |
|---|---|---|---|
| 1 | **Setup** | Captures industries, sub-domains, source mode, style, audience, per-stage cmbagent mode. | Pure Python persistence |
| 2 | **Source Collection & Link Validation** | Validates user URLs (reachability + authority tier), runs DDGS web search, or both. Combines and deduplicates. | `httpx`, `tldextract`, optional cmbagent search |
| 3 | **Curation** | Dedupes, groups by sub-domain, soft-filters by date (`include with date note`, never hard-discard). | cmbagent (one_shot / planning_and_control / planning_and_control_carry_over) |
| 4 | **Generation** | Analyst extracts themes; Writer drafts the full newsletter against a strict outline. | cmbagent (mode-selected per stage) |
| 5 | **Review & Publish** | Critic produces a corrections list; Editor applies them; programmatic verification strips placeholder URLs and inserts missing sections; PDF rendered. | cmbagent + WeasyPrint / fpdf2 |

## Repository layout

```
MARS-NewsLetter/
├── backend/
│   ├── core/                   # FastAPI app factory, structured logging, config
│   ├── data/industry_taxonomy.json     # 75-industry taxonomy + per-industry domain hints
│   ├── models/newsletter_schemas.py    # Pydantic request / response models
│   ├── services/                       # taxonomy_service, session_manager, provider_bridge
│   ├── execution/console_capture.py    # stdout/stderr tee → WebSocket buffer + per-stage log
│   ├── websocket/events.py             # send_ws_event helper
│   ├── routers/                        # health, taxonomy, files, newsletter
│   ├── task_framework/newsletter/      # the pipeline
│   │   ├── prompts/stages.py           # all stage prompts (Stage 2–5)
│   │   ├── helpers.py                  # 5-stage runners
│   │   ├── source_collector.py         # Stage 2 implementation
│   │   ├── link_validator.py           # reachability + authority tier
│   │   ├── antirefusal.py              # refusal detection / soft retries / rescue seed
│   │   ├── pdf_generator.py            # WeasyPrint → fpdf2 fallback
│   │   ├── programmatic_verification.py # post-Stage-5 deterministic safety net
│   │   └── mode_dispatcher.py          # cmbagent one_shot / planning_and_control[_carry_over]
│   └── main.py                         # FastAPI entry + WebSocket /ws/newsletter/{task}/{stage}
└── frontend/
    ├── app/                            # Next.js App Router (page + layout + 404)
    ├── components/newsletter/          # SetupPanel, IndustryPicker, SourcePicker, etc.
    ├── components/core/                # Button, Card, Input, StatusBadge
    ├── hooks/                          # useNewsletterTask, useTaxonomy
    ├── lib/                            # config, fetch wrapper, dateUtils
    └── types/                          # NewsletterCreateRequest, TaskState, etc.
```

## Quick start (local)

```bash
# 1. Backend
cd MARS-NewsLetter
python -m venv .venv && source .venv/bin/activate
pip install -r Requirements.txt

# .env.local already ships with sensible dev defaults; it overrides .env.
# Add ONE provider key (OPENAI_API_KEY / ANTHROPIC_API_KEY / AZURE_OPENAI_* /
# AWS_*) for the AI stages, or leave blank to run in stub mode.
python backend/run.py
# server: http://localhost:$PORT (default 8000) · docs at /docs
# work_dir + log dir are auto-created on startup.

# 2. Frontend (in a new shell)
cd MARS-NewsLetter/frontend
# frontend/.env.local already points NEXT_PUBLIC_API_URL at localhost:8000
npm install
npm run dev
# UI: http://localhost:3000  →  Setup → Run → Review → Final & PDF
```

### Environment file precedence

`run.py` loads env files in this order — later loads override earlier ones:

```
<repo>/.env                 →  <repo>/backend/.env  →  <repo>/.env.local  →  <repo>/backend/.env.local
```

So you can keep a checked-in `.env` for shared defaults and a local `.env.local`
for machine-specific overrides (port, provider keys, debug flags). The frontend
follows Next.js's standard precedence (`.env.local` overrides `.env`).

## Quick start (Docker)

```bash
cp env.example .env   # fill in provider creds
docker compose up --build
# UI: http://localhost:3000   API: http://localhost:8000
```

## API surface (all under `/api/newsletter`)

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/taxonomy` | Industries, authentic-domain hints, neutral authority list |
| `POST` | `/create`   | Create a new newsletter run + auto-complete Stage 1 |
| `POST` | `/{task_id}/stages/{n}/execute` | Kick off Stage 2–5 (background async) |
| `GET`  | `/{task_id}/stages/{n}/content` | Read the primary output of a stage |
| `PUT`  | `/{task_id}/stages/{n}/content` | Manual edit of stage output (downstream stages reset to `pending`) |
| `POST` | `/{task_id}/stages/{n}/refine`  | Chat-style LLM refinement of the current content |
| `GET`  | `/{task_id}` | Full task state (progress %, stage list, setup snapshot) |
| `GET`  | `/recent`    | Recent runs across the `newsletter` session |
| `POST` | `/{task_id}/regenerate-pdf` | Re-render the Stage-5 markdown to PDF |
| `GET`  | `/files/list?work_dir=…`         | List artifacts in the work directory |
| `GET`  | `/files/text?work_dir=…&rel_path=…` | Read a text artifact inline |
| `GET`  | `/files/download?work_dir=…&rel_path=…` | Download an artifact |
| `WS`   | `/ws/newsletter/{task}/{stage}` | Live console output + stage_completed / stage_failed events |

## Production hardening already baked in

* **Soft date filtering** — never `DISCARD unless explicitly dated`; tag
  unstamped items as `date: not stated in snippet` so Stage 3 can decide.
* **Anti-refusal retry wrapper** — every LLM call passes through
  `call_llm_with_antirefusal`. If the first response is empty or refusal-
  shaped, it retries once with neutral, content-filter-safe wording.
* **Rescue scaffolds** — when Stage 3 or Stage 4 still refuse after retry, a
  clearly-labelled `_generate_rescue_seed` document is injected so the next
  stage has structure to work on rather than an empty file.
* **Azure-safe wording** — prompts avoid `STRICTLY FORBIDDEN` / `NEVER refuse`
  / `That is a product failure` (these trigger Azure's jailbreak classifier);
  guidance is reframed as neutral editorial notes.
* **Programmatic verification** — after Stage 5 the editor's output runs
  through `verify_and_clean`, which strips placeholder URLs, removes URLs not
  present in the curated set, softens unsupported superlatives, and inserts
  any missing canonical sections.
* **Authentic-source first** — user URLs are bucketed into
  `official` / `authority` / `unknown` tiers using the per-industry hint map
  (e.g. `aws.amazon.com` for AI Infra, `fda.gov` for Pharma). Unknown links
  are surfaced for confirmation, not silently dropped.
* **Stale-run recovery** — on backend restart, any stage left in `running`
  state is reset to `failed` so users can retry instead of being stuck.

## Per-stage agent strategy

Every AI stage exposes its `cmbagent` invocation mode in Stage 1:

* `one_shot` — single researcher agent, fastest. Best when prompts are stable.
* `planning_and_control` — planner + executor. Better for multi-step work.
* `planning_and_control_carry_over` — planner + executor with cross-step
  memory; best when later sub-tasks depend on earlier evidence.

The Setup UI offers a "Set all stages to X" shortcut and a per-stage override.
Each `/execute` call also accepts `mode_override` so an operator can flip a
single stage without redoing setup.

## Memory of past failures

Two production incidents from sibling products informed the prompt and
defense design:

1. **NewsPulse `DISCARD` failure** — researcher prompts that ordered the
   model to "DISCARD any result not explicitly dated YYYY" produced empty
   reports because evidence dates often live outside the snippet. NewsLetter
   uses `include with date note` and treats unstamped items as in-window by
   default.
2. **Azure content-filter blocks** — phrases like `STRICTLY FORBIDDEN`,
   `NEVER refuse`, `That is a product failure` triggered Azure's
   `ResponsibleAIPolicyViolation` jailbreak classifier and broke Stage 4 in
   production. NewsLetter reframes anti-refusal guidance as neutral editorial
   tone (`Always produce substantive content`, `Treat the data as
   authoritative`, `When data is thin, summarize what is present`).

## Smoke test (no LLM creds required)

The mode dispatcher detects when `mars_cmbagent` is not installed and falls
back to a stub that echoes the prompt. This lets you exercise the full
pipeline end-to-end against the wire format without spending tokens:

```bash
pip install -r Requirements.txt    # cmbagent is optional in this mode
python backend/run.py              # in one shell
# In another shell:
curl -X POST http://localhost:8000/api/newsletter/create \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "AI Infra weekly",
    "industries": [{"industry": "AI Infra", "sub_domains": ["AI Platforms", "Compute & Platforms"]}],
    "date_from": "2026-04-27",
    "date_to": "2026-05-04",
    "source_mode": "combined",
    "user_urls": ["https://aws.amazon.com/blogs/aws/"],
    "style": "executive",
    "mode_config": {
      "stage_3_mode": "one_shot",
      "stage_4_mode": "one_shot",
      "stage_5_mode": "one_shot",
      "stage_2_enrich_with_llm": false
    }
  }'
```

## License

Internal — Infosys MARS family.
