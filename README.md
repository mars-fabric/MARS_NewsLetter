# MARS-NewsLetter

![Python](https://img.shields.io/badge/Python-3.12%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-14%2B-black?logo=next.js&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

MARS-NewsLetter is a multi-agent AI application that produces publication-quality industry newsletters from live web intelligence. Users select one or more industries and sub-domains, specify a coverage window, and the system autonomously discovers the top companies in that space, collects and curates hundreds of source articles, drafts a structured 22-section newsletter, and then runs a quality-review and scoring pipeline before delivering a final Markdown document and a print-ready PDF.

The application is built on a FastAPI backend that orchestrates the [mars_cmbagent](https://pypi.org/project/mars-cmbagent/) multi-agent framework (importable as `cmbagent`) using AG2 (AutoGen 2) and litellm. Stage 2 (source collection) performs automatic web search via DDGS, accepts user-supplied URLs, or combines both. Stage 3 curates and deduplicates the raw material using an AI researcher. Stage 4 drafts the full newsletter section-by-section so that output-token limits are never hit. Stage 5 runs a LangGraph pipeline that performs URL verification, LLM-based critique, claim re-checking, editorial polish, and multi-dimensional quality scoring before rendering the PDF.

The frontend is a Next.js 14 TypeScript application that guides the user through the wizard, streams live stage logs over WebSocket, provides in-browser Markdown previews for each stage output, and displays the final quality dashboard including the score card, URL verification results, and critic report.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER (Browser)                              │
│  Next.js 14 · TypeScript · Tailwind CSS                             │
│  - Industry & date picker wizard                                    │
│  - Live log stream (WebSocket)                                      │
│  - Per-stage Markdown preview + edit                                │
│  - Quality dashboard (score card · URL check · critic report)       │
└────────────────────────┬────────────────────────────────────────────┘
                         │ HTTP / WebSocket  (localhost:3000 → :8000)
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend  (port 8000)                     │
│  POST /api/newsletter/create          → Stage 1 (Setup)            │
│  POST /api/newsletter/{id}/stages/N/execute                         │
│  GET  /api/newsletter/{id}/stages/N/content                         │
│  GET  /api/newsletter/{id}/dashboard                                │
│  WS   /ws/newsletter/{id}/{stage}     → real-time log push          │
└────────────┬───────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     5-Stage Pipeline                                │
│                                                                     │
│  Stage 1 ─ Setup (deterministic)                                    │
│    Persists user config; validates taxonomy; writes setup.md        │
│             │                                                       │
│             ▼                                                       │
│  Stage 2 ─ Source Collection  (cmbagent + DDGS)                    │
│    Auto-discover top companies → per-company DDGS queries           │
│    + industry-wide search + user URLs → dedup + link validation     │
│    → raw_sources.md  (30–200 sources)                               │
│             │                                                       │
│             ▼                                                       │
│  Stage 3 ─ Curation  (cmbagent researcher)                         │
│    Rank · deduplicate · tag · HEAD-verify URLs                      │
│    → curated.md                                                     │
│             │                                                       │
│             ▼                                                       │
│  Stage 4 ─ Generation  (cmbagent, section-by-section)              │
│    Analyst drafts outline → 22-section writer runs per section      │
│    → newsletter_draft.md  (~60–90 KB)                              │
│             │                                                       │
│             ▼                                                       │
│  Stage 5 ─ Review / Score  (LangGraph graph)                       │
│    URL verifier → LLM critic → DDGS claim re-check                  │
│    → editor → coverage checker → scorer → PDF renderer             │
│    → newsletter_final.md + score_card.json + newsletter.pdf        │
└─────────────────────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      LLM Provider (via litellm)                     │
│  OpenAI · Anthropic · Azure OpenAI · AWS Bedrock                    │
│  Google Gemini · Mistral · Enterprise Gateway                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

**Step 1 — Clone and install backend dependencies**

```bash
git clone <repo-url> MARS_NewsLetter
cd MARS_NewsLetter/backend
python3.12 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**Step 2 — Configure credentials**

```bash
cp .env.example .env
# Open .env and set at least one LLM provider block (see Configuration below).
```

**Step 3 — Start the backend and frontend**

```bash
# Terminal 1 — backend (from MARS_NewsLetter/backend/)
python run.py

# Terminal 2 — frontend (from MARS_NewsLetter/frontend/)
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.  
API documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs).

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.12 or newer |
| Node.js | 18 or newer |
| npm | 9 or newer |
| mars_cmbagent | 2.2.0 or newer |
| One LLM provider credential | Azure OpenAI, OpenAI, Anthropic, AWS Bedrock, Google Gemini, or Mistral |

`mars_cmbagent` is listed in `requirements.txt` and will be installed automatically by `pip install -r requirements.txt`. If you are developing against a local checkout of mars_cmbagent, install it as an editable package first:

```bash
pip install -e /path/to/mars_cmbagent[enterprise_gateway]
```

---

## Installation

### Backend

```bash
cd MARS_NewsLetter/backend

# Create and activate a virtual environment
python3.12 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# Install all dependencies (FastAPI, cmbagent, LLM SDKs, PDF renderers, etc.)
pip install -r requirements.txt

# Copy the environment template
cp .env.example .env

# Edit .env — fill in at minimum one LLM provider block
$EDITOR .env
```

### Frontend

```bash
cd MARS_NewsLetter/frontend

# Install Node dependencies
npm install

# Copy the frontend environment template (optional for localhost defaults)
cp .env.local.example .env.local
```

The frontend `.env.local` defaults point to `http://localhost:8000`, which matches the backend's default port. You only need to edit it when running against a remote backend.

---

## Configuration

### Minimal `.env` — Azure OpenAI

```dotenv
# backend/.env
HOST=0.0.0.0
PORT=8000

AZURE_OPENAI_API_KEY=your-azure-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-12-01-preview

# Optional: pin the model used for all roles
# CMBAGENT_DEFAULT_MODEL=azure/gpt-4o
```

### Minimal `.env` — OpenAI direct

```dotenv
# backend/.env
HOST=0.0.0.0
PORT=8000

OPENAI_API_KEY=sk-...
```

### Minimal `.env` — Anthropic

```dotenv
# backend/.env
HOST=0.0.0.0
PORT=8000

ANTHROPIC_API_KEY=sk-ant-...
```

### Single-model pin (`NEWSLETTER_DEFAULT_MODEL`)

Set `CMBAGENT_DEFAULT_MODEL` to a litellm model string to route all pipeline roles through one model without editing per-role overrides:

```dotenv
CMBAGENT_DEFAULT_MODEL=gpt-4o          # OpenAI
# CMBAGENT_DEFAULT_MODEL=azure/gpt-4o  # Azure OpenAI
# CMBAGENT_DEFAULT_MODEL=claude-3-5-sonnet-20241022  # Anthropic
```

Per-role overrides (`CMBAGENT_PLANNER_MODEL`, `CMBAGENT_RESEARCHER_MODEL`, etc.) take precedence over the default when set.

### Enterprise Gateway

For deployments that route all LLM traffic through an internal OAuth2-protected gateway, set `CMBAGENT_LLM_PROVIDER=enterprise_gateway` and fill in the `ENTERPRISE_LLM_*` block in `.env`. The adapter handles multi-stage token exchange, token caching, auto-refresh, and TLS against a corporate CA bundle. See [ENTERPRISE_SETUP.md](ENTERPRISE_SETUP.md) for the full reference.

---

## Running the Application

### Backend

```bash
cd MARS_NewsLetter/backend
source venv/bin/activate
python run.py
```

`run.py` loads `.env.local` (if present) then `.env`, resolves the work directory, and starts uvicorn. Key environment variables:

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Listen port |
| `NEWSLETTER_ENABLE_RELOAD` | `false` | Enable uvicorn auto-reload for development |
| `NEWSLETTER_DEFAULT_WORK_DIR` | `./cmbdir_newsletter` | Where stage outputs and logs are written |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

Stage outputs land under `NEWSLETTER_DEFAULT_WORK_DIR/sessions/newsletter/tasks/<task_id>/stage_N/`.

Interactive API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)

### Frontend

```bash
cd MARS_NewsLetter/frontend
npm run dev
```

The development server starts on port 3001 (webpack mode). Open [http://localhost:3001](http://localhost:3001).

For a production build:

```bash
npm run build
npm start        # starts on port 3000
```

---

## Pipeline Stages

| Stage | Name | Description | Typical Duration |
|---|---|---|---|
| 1 | Setup | Validates industry/sub-domain selection, persists configuration, writes `setup.md`. Completes immediately on task creation. | < 2 s |
| 2 | Source Collection | Discovers top companies in the selected industries via web search, runs per-company and industry-wide DDGS queries, accepts or combines user-supplied URLs, deduplicates results, and validates link health. Produces `raw_sources.md`. | 2–8 min |
| 3 | Curation | AI researcher ranks, deduplicates, and tags sources by topic, authority tier, and relevance. HEAD-verifies every URL and drops unreachable ones. Produces `curated.md`. | 3–6 min |
| 4 | Generation | An AI analyst drafts the newsletter outline, then a per-section writer generates each of the 22 canonical sections in a dedicated LLM call to stay within output-token limits. Produces `newsletter_draft.md`. | 10–25 min |
| 5 | Review / Score | A LangGraph graph runs URL verification, LLM-based criticism, DDGS claim re-checking, editorial revision, coverage checking, multi-dimensional quality scoring, and PDF rendering. Produces `newsletter_final.md`, `score_card.json`, and `newsletter.pdf`. | 5–15 min |

---

## API Reference

All endpoints are prefixed with `/api/newsletter`. Full interactive documentation is at `/docs`.

### Create a newsletter task

```
POST /api/newsletter/create
```

Validates the taxonomy selection, persists the setup configuration, and completes Stage 1 immediately. Returns a `task_id` and the initial stage list.

**Request body (key fields)**

```json
{
  "title": "FinTech Weekly — Q3 2025",
  "industries": [
    { "industry": "Financial Services", "sub_domains": ["Payments", "Banking"] }
  ],
  "date_from": "2025-07-01",
  "source_mode": "combined",
  "user_urls": [],
  "audience": "Product leaders at mid-size banks"
}
```

### Execute a stage

```
POST /api/newsletter/{task_id}/stages/{stage_num}/execute
```

Starts the specified stage as a background asyncio task. Returns immediately with status `running`. Poll `/stages/{stage_num}/console` for log lines or listen on the WebSocket.

**Request body (optional)**

```json
{
  "mode_override": "one_shot",
  "config_overrides": { "model": "gpt-4o" }
}
```

### Get task state

```
GET /api/newsletter/{task_id}
```

Returns all stage statuses, progress percentage, accumulated LLM cost (USD), and the original setup payload.

### Get stage content

```
GET /api/newsletter/{task_id}/stages/{stage_num}/content
```

Returns the stage's primary Markdown artifact (e.g., `curated.md` for Stage 3), output file list, and stage-specific extras: link validation results for Stage 2 and the score card for Stage 5.

### List recent tasks

```
GET /api/newsletter/recent?limit=25
```

Returns the 25 most recent newsletter tasks ordered by creation time, with progress and current-stage indicators.

### Console log polling (REST fallback)

```
GET /api/newsletter/{task_id}/stages/{stage_num}/console?since=0
```

Returns new log lines since the given index. Increment `since` with the returned `next_index` on each poll. `is_done` becomes `true` when the stage reaches `completed` or `failed`.

### WebSocket — real-time stage events

```
WS /ws/newsletter/{task_id}/{stage_num}
```

Emits JSON events for stage state transitions (`stage_completed`, `stage_failed`). Log streaming uses the REST console endpoint; the WebSocket carries low-rate lifecycle events only.

### Additional endpoints

| Method | Path | Description |
|---|---|---|
| `PUT` | `/api/newsletter/{task_id}/stages/{n}/content` | Save manual edits to a stage artifact; marks later stages as pending |
| `GET` | `/api/newsletter/{task_id}/dashboard` | Full Stage 5 quality dashboard payload (score card, URL checks, critic report, node timings) |
| `POST` | `/api/newsletter/{task_id}/regenerate-pdf` | Re-render the PDF from Stage 5 Markdown without re-running the LLM |
| `POST` | `/api/newsletter/{task_id}/repair-score-card` | Re-parse the score-card LLM output and refresh the score block in the final Markdown |
| `DELETE` | `/api/newsletter/{task_id}` | Delete all DB rows and the on-disk work directory |
| `GET` | `/api/newsletter/taxonomy` | Return the industry/sub-domain taxonomy used by the UI picker |

---

## Output Quality

Stage 5 produces a `score_card.json` alongside the final newsletter. The score card drives the Quality tab in the frontend dashboard.

| Field | Range | Meaning |
|---|---|---|
| `authenticity_score` | 0–100 | Overall signal-to-noise quality. High scores indicate factual, well-cited, non-hallucinated content. Below 70 typically warrants re-generation. |
| `citation_score` | 0–100 | Fraction of factual claims that are backed by an inline `[domain](url)` citation traceable to the curated source list. |
| `factual_fidelity_score` | 0–100 | Degree to which claims are supported by the curated sources rather than introduced by the model from its training data. |
| `coverage_score` | 0–100 | How well the newsletter covers the selected industries and sub-domains relative to the available curated material. |
| `structural_completeness_score` | 0–100 | Fraction of the 22 canonical sections present and non-empty in the final document. |
| `verdict` | string | `production-ready`, `needs-revision`, or `reject` — a single-word quality gate for automated pipelines. |
| `suggestions` | list | Concrete editor suggestions from the LLM critic, ordered by impact. |

Score cards for runs executed before the LangGraph Stage 5 was introduced can be refreshed in-place via `POST /api/newsletter/{task_id}/repair-score-card`.

---

## Extending with Custom Tools

The pipeline is built on cmbagent's AG2-based multi-agent framework, which supports custom tool registration via standard Python callables. Stage-specific tool sets are configured through the `mode_dispatcher` layer, and any cmbagent-compatible tool can be dropped into the pipeline without modifying the core framework. See [CUSTOM_TOOLS.md](CUSTOM_TOOLS.md) for a step-by-step guide to registering tools for a specific stage.

---

## Enterprise Deployment

MARS-NewsLetter supports enterprise deployments that route all LLM traffic through an internal OpenAI-wire-compatible gateway protected by a multi-stage OAuth2 authentication flow (password grant or client-credentials, with optional session-JWT exchange). The adapter caches tokens per-process, auto-refreshes on expiry, retries transparently on HTTP 401, verifies TLS against a corporate CA bundle, and supports HTTP(S) proxy configuration. Horizontal scaling is supported — each worker process manages its own token cache with no shared state required. See [ENTERPRISE_SETUP.md](ENTERPRISE_SETUP.md) for the full configuration reference.

---

## Project Structure

```
MARS_NewsLetter/
├── backend/                        # FastAPI application root
│   ├── run.py                      # Entry point — loads .env, starts uvicorn
│   ├── main.py                     # FastAPI app + WebSocket mount
│   ├── requirements.txt            # Python dependencies
│   ├── .env.example                # Annotated environment template
│   ├── core/                       # App config, logging, cmbagent patch
│   ├── routers/                    # FastAPI route handlers
│   │   ├── newsletter.py           # Main pipeline API (create / execute / content)
│   │   ├── providers.py            # LLM provider introspection
│   │   ├── taxonomy.py             # Industry taxonomy endpoint
│   │   ├── models.py               # Available model listing
│   │   ├── files.py                # Stage artifact download
│   │   └── health.py              # Health check
│   ├── models/                     # Pydantic request/response schemas
│   │   ├── newsletter_schemas.py   # Pipeline schemas + ScoreCard
│   │   └── provider_schemas.py     # Provider configuration schemas
│   ├── services/                   # Supporting services
│   │   ├── config_bridge.py        # .env → cmbagent config translation
│   │   ├── credential_vault.py     # Secure credential storage
│   │   ├── provider_bridge.py      # LLM provider abstraction
│   │   ├── session_manager.py      # Task setup persistence
│   │   └── taxonomy_service.py     # Industry taxonomy validation
│   ├── task_framework/             # Pipeline stage implementations
│   │   └── newsletter/
│   │       ├── helpers.py          # Stage runners (run_stage_1 … run_stage_5)
│   │       ├── constants.py        # 22 canonical section headings
│   │       ├── mode_dispatcher.py  # cmbagent one_shot / planning_and_control
│   │       ├── source_collector.py # DDGS + user-URL collection logic
│   │       ├── link_validator.py   # HTTP HEAD URL validation
│   │       ├── prompts/            # Stage prompt builders
│   │       ├── stage4/             # Section-by-section newsletter writer
│   │       └── stage5/             # LangGraph review + scoring graph
│   ├── execution/                  # Console capture + LLM cost tracking
│   ├── websocket/                  # WebSocket event definitions
│   ├── data/                       # Industry taxonomy JSON
│   └── tests/                     # Smoke tests
│
└── frontend/                       # Next.js 14 application
    ├── app/                        # Next.js App Router pages + layouts
    ├── hooks/                      # React hooks (newsletter task, providers, taxonomy)
    ├── contexts/                   # Theme context
    ├── lib/                        # Fetch utilities, date helpers, config
    ├── types/                      # TypeScript type definitions
    ├── styles/                     # Global CSS + MARS theme
    ├── package.json                # Node dependencies
    └── .env.local.example          # Frontend environment template
```

---

## Contributing

Contributions are welcome. Please open an issue to discuss any significant change before submitting a pull request. Ensure that new backend code passes the existing smoke tests (`backend/tests/e2e_smoke.py`) and that any new environment variables are documented in `backend/.env.example`.

---

## License

MIT — see [LICENSE](LICENSE) for details.
