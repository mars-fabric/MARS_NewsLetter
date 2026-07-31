"""NewsLetter wizard endpoints — create task, execute stages, read content, list runs.

Persistence model: cmbagent's ORM (TaskStage, WorkflowRun) owns the canonical
stage status / output rows. The user-supplied Stage-1 setup payload is stored
on disk under the work directory (``setup.json``) via ``services.session_manager``
because it doesn't fit any existing cmbagent table.

Stage execution runs as a background asyncio task. Console output (stdout +
stderr from stage code) is captured to a thread-safe shared buffer per
``task_id:stage_num`` and a per-stage ``console.log`` file. The WebSocket
endpoint in ``main.py`` consumes the buffer and pushes events to the UI.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

from core.config import settings
from core.logging import bind_context, get_logger
from execution import console_capture
from execution.cost_collector import CostCollector
from models.newsletter_schemas import (
    CmbAgentMode,
    CompilePdfResponse,
    LinkPrioritiesRequest,
    NewsletterContentUpdateRequest,
    NewsletterCreateRequest,
    NewsletterCreateResponse,
    NewsletterExecuteRequest,
    NewsletterRecentTaskResponse,
    NewsletterStageResponse,
    NewsletterTaskStateResponse,
    ReportTemplateRequest,
    StageContentResponse,
)
from services import session_manager, taxonomy_service
from task_framework.newsletter import helpers as nl
from task_framework.newsletter.pdf_generator import render_pdf

logger = get_logger(__name__)

router = APIRouter(prefix="/api/newsletter", tags=["Newsletter"])

# In-memory tracking of running background tasks keyed by "task_id:stage_num".
_running: Dict[str, asyncio.Task] = {}
_running_lock = threading.Lock()

_db_initialized = False
_db_init_lock = threading.Lock()


# ──────────────────────────────────────────────────────────────────────────────
# DB plumbing — lazy-initialised so cmbagent isn't required for unit imports
# ──────────────────────────────────────────────────────────────────────────────

def _get_db():
    global _db_initialized
    if not _db_initialized:
        with _db_init_lock:
            if not _db_initialized:
                from cmbagent.database.base import init_database  # type: ignore
                init_database()
                _db_initialized = True
    from cmbagent.database.base import get_db_session  # type: ignore
    return get_db_session()


def _stage_repo(db, session_id: str = "newsletter"):
    """Wrap cmbagent's TaskStageRepository with the (parent_run_id, stage_number)
    update API the router was written against.

    cmbagent only ships ``update_stage_status(stage_id, status, **kwargs)`` —
    we need a (run_id, stage_number) → set fields variant. Wrapping at the
    factory keeps the call sites in this router unchanged and the cmbagent
    package un-monkeypatched.
    """
    from cmbagent.database.repository import TaskStageRepository  # type: ignore

    repo = TaskStageRepository(db, session_id=session_id)

    def _update_stage(*, parent_run_id: str, stage_number: int, **fields):
        stage = next(
            (s for s in repo.list_stages(parent_run_id=parent_run_id)
             if s.stage_number == stage_number),
            None,
        )
        if stage is None:
            return None
        for key, value in fields.items():
            if hasattr(stage, key):
                setattr(stage, key, value)
        repo.db.commit()
        return stage

    repo.update_stage = _update_stage  # type: ignore[attr-defined]
    return repo


def _ensure_workflow_run(db, task_id: str, session_id: str, title: Optional[str]) -> None:
    """Insert a placeholder ``WorkflowRun`` for the newsletter task.

    cmbagent's ``WorkflowRun`` requires ``mode``, ``agent``, and ``model`` to be
    NOT NULL. Newsletter doesn't fit a single mode (stages 3/4/5 each pick their
    own), so we record sensible placeholders that satisfy the schema and read
    naturally in any downstream cmbagent UI: ``mode='newsletter_pipeline'``,
    ``agent='newsletter'``, ``model='multi'``.
    """
    from cmbagent.database.models import WorkflowRun  # type: ignore
    from cmbagent.database.base import init_database  # type: ignore
    init_database()
    existing = db.query(WorkflowRun).filter(WorkflowRun.id == task_id).first()
    if existing:
        return
    _ensure_session_row(db, session_id)
    run = WorkflowRun(
        id=task_id,
        session_id=session_id,
        mode="newsletter_pipeline",
        agent="newsletter",
        model="multi",
        status="created",
        meta={"product": "newsletter", "title": title} if title else {"product": "newsletter"},
    )
    db.add(run)
    db.commit()


def _ensure_session_row(db, session_id: str) -> None:
    """The ``WorkflowRun.session_id`` FK requires a row in ``sessions``.

    Best-effort upsert — if the cmbagent Session model schema changes we just
    let the FK error surface instead of silently masking it.
    """
    try:
        from cmbagent.database.models import Session as CmbSession  # type: ignore
    except Exception:
        return
    existing = db.query(CmbSession).filter(CmbSession.id == session_id).first()
    if existing:
        return
    try:
        db.add(CmbSession(id=session_id, name=session_id))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def _work_dir_for(task_id: str, session_id: str, base: Optional[str]) -> str:
    base_dir = os.path.expanduser(base or settings.default_work_dir)
    return os.path.join(base_dir, "sessions", session_id, "tasks", task_id)


def _run_created_at(run) -> Optional[str]:
    """cmbagent's WorkflowRun model uses ``started_at`` (no ``created_at``).

    The router previously read ``run.created_at`` and crashed every list call.
    Centralised here so any future column rename only needs touching once.
    """
    ts = getattr(run, "started_at", None) or getattr(run, "created_at", None)
    return ts.isoformat() if ts else None


def _stage_to_response(stage) -> NewsletterStageResponse:
    out = stage.output_data or {}
    return NewsletterStageResponse(
        stage_number=stage.stage_number,
        stage_name=stage.stage_name,
        status=stage.status,
        started_at=stage.started_at.isoformat() if stage.started_at else None,
        completed_at=stage.completed_at.isoformat() if stage.completed_at else None,
        error=stage.error_message,
        mode=out.get("mode") if out else None,
        cost_usd=out.get("cost_usd"),
    )


def _build_shared_state(task_id: str, up_to_stage: int, db, session_id: str) -> Dict[str, Any]:
    repo = _stage_repo(db, session_id=session_id)
    stages = repo.list_stages(parent_run_id=task_id)
    shared: Dict[str, Any] = {}
    for stage in sorted(stages, key=lambda s: s.stage_number):
        if stage.stage_number < up_to_stage and stage.status == "completed":
            data = (stage.output_data or {}).get("shared") or {}
            shared.update(data)
    return shared


# ──────────────────────────────────────────────────────────────────────────────
# Create
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/create", response_model=NewsletterCreateResponse)
async def create_task(req: NewsletterCreateRequest) -> NewsletterCreateResponse:
    # Validate taxonomy choices first so we fail fast if something is off.
    sel = [(i.industry, i.sub_domains) for i in req.industries]
    errors = taxonomy_service.validate_selection(sel)
    if errors:
        raise HTTPException(status_code=400, detail={"taxonomy_errors": errors})

    session_id = "newsletter"
    task_id = uuid.uuid4().hex
    work_dir = _work_dir_for(task_id, session_id, req.work_dir)
    os.makedirs(work_dir, exist_ok=True)

    bind_context(task_id=task_id, session_id=session_id, run_id=task_id)
    logger.info("create_newsletter", title=req.title, industries=[i.industry for i in req.industries])

    setup_payload = req.model_dump(mode="json")
    setup_payload["task_id"] = task_id
    setup_payload["session_id"] = session_id
    session_manager.save_setup(work_dir, setup_payload)

    db = _get_db()
    try:
        _ensure_workflow_run(db, task_id, session_id, req.title)
        repo = _stage_repo(db, session_id=session_id)
        for sd in nl.STAGE_DEFS:
            repo.create_stage(
                parent_run_id=task_id,
                stage_number=sd["number"],
                stage_name=sd["name"],
                status="pending",
            )
        # Stage 1 is "auto-completed" on create — it is just the persisted setup.
        shared, primary, files = await nl.run_stage_1(work_dir=work_dir, setup_payload=setup_payload)
        repo.update_stage(
            parent_run_id=task_id, stage_number=1, status="completed",
            # ``primary`` is the rendered setup summary markdown — store it so
            # GET /content can return a string for ``content`` (the shared map's
            # "setup" key holds the raw dict, which is not serialisable as str).
            output_data={
                "shared": shared,
                "files": files,
                "mode": "deterministic",
                "primary_preview": (primary or "")[:5000],
            },
            completed_at=datetime.now(timezone.utc),
        )
        stages = repo.list_stages(parent_run_id=task_id)
    finally:
        db.close()

    return NewsletterCreateResponse(
        task_id=task_id,
        work_dir=work_dir,
        stages=[_stage_to_response(s) for s in sorted(stages, key=lambda x: x.stage_number)],
    )


# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# Canonical section list (Gate B helper)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/canonical-sections")
async def get_canonical_sections() -> Dict[str, Any]:
    """Return the 22 canonical section headings and their drafting guidance.

    The frontend uses this to populate the Gate B "add from predefined" picker
    so users don't have to type common section names from scratch.
    """
    from task_framework.newsletter.stage4.sections import CANONICAL_SECTIONS
    return {
        "sections": [
            {
                "number": s.number,
                "heading": s.heading,
                "guidance": s.guidance,
                "target_words": s.target_words,
            }
            for s in CANONICAL_SECTIONS
        ]
    }


# ──────────────────────────────────────────────────────────────────────────────
# Gates — user decisions between stages (Gate A: links, Gate B: template)
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_work_dir(task_id: str) -> str:
    db = _get_db()
    try:
        from cmbagent.database.models import WorkflowRun  # type: ignore
        run = db.query(WorkflowRun).filter(WorkflowRun.id == task_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail="task not found")
        return _work_dir_for(task_id, run.session_id, base=None)
    finally:
        db.close()


@router.post("/{task_id}/gate/links", response_model=NewsletterStageResponse)
async def set_link_priorities(task_id: str, req: LinkPrioritiesRequest) -> NewsletterStageResponse:
    """Gate A — persist user link prioritization applied before Stage 3 curation."""
    work_dir = _resolve_work_dir(task_id)
    excluded = [p.url for p in req.priorities if p.action.value == "exclude"]
    priorities = [
        {"url": p.url, "action": p.action.value, "weight": p.weight}
        for p in req.priorities
    ]
    changes: Dict[str, Any] = {
        "link_priorities": priorities,
        "excluded_urls": excluded,
    }
    if req.add_urls:
        # Auto-pin user-injected URLs so they survive curation.
        priorities.extend({"url": u, "action": "pin", "weight": 1.0} for u in req.add_urls)
        changes["link_priorities"] = priorities
    if req.min_relevance is not None:
        changes["min_relevance"] = req.min_relevance
    session_manager.update_setup(work_dir, **changes)
    logger.info("gate_links_saved", task_id=task_id, priorities=len(priorities), excluded=len(excluded))
    return NewsletterStageResponse(
        stage_number=3, stage_name="curation", status="gate_saved",
    )


@router.post("/{task_id}/gate/template", response_model=NewsletterStageResponse)
async def set_report_template(task_id: str, req: ReportTemplateRequest) -> NewsletterStageResponse:
    """Gate B — persist the user's section template applied before Stage 4 generation."""
    work_dir = _resolve_work_dir(task_id)
    template = [
        {
            "title": s.title,
            "depth": s.depth.value,
            "points": s.points,
            "guidance": s.guidance,
            "word_count": s.word_count,
        }
        for s in req.sections
    ]
    changes: Dict[str, Any] = {"report_template": template}
    if req.tone is not None:
        changes["template_tone"] = req.tone
    if req.audience is not None:
        changes["template_audience"] = req.audience
    session_manager.update_setup(work_dir, **changes)
    logger.info("gate_template_saved", task_id=task_id, sections=len(template))
    return NewsletterStageResponse(
        stage_number=4, stage_name="generation", status="gate_saved",
    )


@router.get("/{task_id}/gate")
async def get_gate_state(task_id: str) -> Dict[str, Any]:
    """Return the currently persisted gate decisions for the UI to rehydrate."""
    work_dir = _resolve_work_dir(task_id)
    setup = session_manager.load_setup(work_dir) or {}
    return {
        "link_priorities": setup.get("link_priorities", []),
        "excluded_urls": setup.get("excluded_urls", []),
        "min_relevance": setup.get("min_relevance"),
        "report_template": setup.get("report_template", []),
        "template_tone": setup.get("template_tone"),
        "template_audience": setup.get("template_audience"),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Execute a stage
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/{task_id}/stages/{stage_num}/execute", response_model=NewsletterStageResponse)
async def execute_stage(task_id: str, stage_num: int, req: NewsletterExecuteRequest, bg: BackgroundTasks) -> NewsletterStageResponse:
    if stage_num < 1 or stage_num > len(nl.STAGE_DEFS):
        raise HTTPException(status_code=400, detail="invalid stage number")
    if stage_num == 1:
        raise HTTPException(status_code=400, detail="Stage 1 is the setup; edit via PUT /content instead")

    db = _get_db()
    try:
        from cmbagent.database.models import WorkflowRun  # type: ignore
        run = db.query(WorkflowRun).filter(WorkflowRun.id == task_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail="task not found")
        session_id = run.session_id

        repo = _stage_repo(db, session_id=session_id)
        stage = next((s for s in repo.list_stages(parent_run_id=task_id) if s.stage_number == stage_num), None)
        if stage is None:
            raise HTTPException(status_code=404, detail="stage not found")

        # Disallow re-running a stage that is already running.
        bg_key = f"{task_id}:{stage_num}"
        with _running_lock:
            existing = _running.get(bg_key)
            if existing is not None and not existing.done():
                raise HTTPException(status_code=409, detail="stage is already running")

        repo.update_stage(
            parent_run_id=task_id, stage_number=stage_num, status="running",
            started_at=datetime.now(timezone.utc), completed_at=None, error_message=None,
        )
        # Reset any later stages to pending — they need to re-run on top of the new output.
        for later in [s for s in repo.list_stages(parent_run_id=task_id) if s.stage_number > stage_num]:
            repo.update_stage(parent_run_id=task_id, stage_number=later.stage_number, status="pending",
                              started_at=None, completed_at=None, error_message=None)

        work_dir = _work_dir_for(task_id, session_id, base=None)
    finally:
        db.close()

    # Reset console buffer for this stage.
    console_capture.clear(f"{task_id}:{stage_num}")

    task = asyncio.create_task(_run_stage_background(
        task_id=task_id, session_id=session_id, stage_num=stage_num,
        work_dir=work_dir, mode_override=req.mode_override,
        config_overrides=req.config_overrides,
    ))
    with _running_lock:
        _running[f"{task_id}:{stage_num}"] = task

    return NewsletterStageResponse(
        stage_number=stage_num,
        stage_name=nl.stage_def(stage_num)["name"],
        status="running",
        started_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


async def _run_stage_background(
    *, task_id: str, session_id: str, stage_num: int,
    work_dir: str, mode_override: Optional[CmbAgentMode],
    config_overrides: Optional[Dict[str, Any]],
) -> None:
    bind_context(task_id=task_id, session_id=session_id, run_id=task_id)
    buf_key = f"{task_id}:{stage_num}"

    db = _get_db()
    cost_collector = CostCollector(db_session=db, session_id=session_id, run_id=task_id)

    def cost_callback(payload: Dict[str, Any]) -> None:
        # Cmbagent callbacks fire from worker threads — keep this side-effect-only.
        try:
            cost_collector.collect_from_callback(payload)
        except Exception as exc:  # pragma: no cover — never crash the workflow
            logger.debug("cost_callback_failed", error=str(exc))

    try:
        repo = _stage_repo(db, session_id=session_id)
        try:
            shared = _build_shared_state(task_id, up_to_stage=stage_num, db=db, session_id=session_id)
            setup = shared.get("setup") or session_manager.load_setup(work_dir) or {}
            # Merge gate decisions (Gate A link priorities, Gate B report
            # template) persisted to disk after Stage 1 — the stage-1 shared
            # payload predates them, so disk wins for these keys.
            disk_setup = session_manager.load_setup(work_dir) or {}
            for _gk in (
                "link_priorities", "min_relevance", "excluded_urls",
                "report_template", "template_tone", "template_audience",
            ):
                if _gk in disk_setup:
                    setup[_gk] = disk_setup[_gk]
            mode_for_record = (mode_override.value if mode_override else
                               setup.get("mode_config", {}).get(f"stage_{stage_num}_mode"))

            with console_capture.ConsoleCapture(buf_key=buf_key, work_dir=work_dir, stage_num=stage_num):
                logger.info("stage_starting", stage_num=stage_num, mode=mode_for_record)
                if stage_num == 2:
                    new_shared, primary, files = await nl.run_stage_2(
                        work_dir=work_dir, setup=setup,
                        mode_override=mode_override, config_overrides=config_overrides,
                        cost_callback=cost_callback,
                    )
                elif stage_num == 3:
                    new_shared, primary, files = await nl.run_stage_3(
                        work_dir=work_dir, setup=setup,
                        raw_sources=shared.get("raw_sources", ""),
                        mode_override=mode_override, config_overrides=config_overrides,
                        cost_callback=cost_callback,
                    )
                elif stage_num == 4:
                    new_shared, primary, files = await nl.run_stage_4(
                        work_dir=work_dir, setup=setup,
                        curated=shared.get("curated", ""),
                        seed_companies=shared.get("top_companies"),
                        mode_override=mode_override, config_overrides=config_overrides,
                        cost_callback=cost_callback,
                    )
                elif stage_num == 5:
                    new_shared, primary, files = await nl.run_stage_5(
                        work_dir=work_dir, setup=setup,
                        draft=shared.get("draft", ""),
                        curated=shared.get("curated", ""),
                        mode_override=mode_override, config_overrides=config_overrides,
                        cost_callback=cost_callback,
                    )
                else:
                    raise ValueError(f"unhandled stage {stage_num}")
                logger.info("stage_done", stage_num=stage_num, files_written=len(files))

            # Some cmbagent paths (notably one_shot) write cost JSON on disk
            # *after* the workflow returns. Sweep ``work_dir/cost/`` once more
            # so we don't miss the final tally.
            try:
                cost_collector.collect_from_work_dir(work_dir)
            except Exception:
                pass

            stage_cost = _stage_cost_total(db, session_id=session_id, run_id=task_id, stage_num=stage_num)
            repo.update_stage(
                parent_run_id=task_id, stage_number=stage_num, status="completed",
                output_data={
                    "shared": new_shared,
                    "files": files,
                    "mode": mode_for_record,
                    "primary_preview": (primary or "")[:5000],
                    "cost_usd": stage_cost,
                },
                completed_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.exception("stage_failed", stage_num=stage_num)
            repo.update_stage(
                parent_run_id=task_id, stage_number=stage_num, status="failed",
                error_message=str(exc), completed_at=datetime.now(timezone.utc),
            )
    finally:
        db.close()
        with _running_lock:
            _running.pop(buf_key, None)


def _stage_cost_total(db, *, session_id: str, run_id: str, stage_num: int) -> float:
    """Return per-stage cost accumulated since this stage was launched.

    cmbagent's CostRecord doesn't carry a stage number, so we approximate by
    summing every cost record for this task and subtracting what was already
    accounted for in earlier completed stages. Best-effort — never throws.
    """
    try:
        from cmbagent.database.models import CostRecord  # type: ignore
        rows = db.query(CostRecord).filter(CostRecord.run_id == run_id).all()
        total = sum(float(r.cost_usd or 0) for r in rows)
        # Subtract stages that have already recorded their own cost.
        repo = _stage_repo(db, session_id=session_id)
        prior = 0.0
        for s in repo.list_stages(parent_run_id=run_id):
            if s.stage_number < stage_num and s.output_data:
                prior += float(s.output_data.get("cost_usd") or 0)
        delta = max(0.0, total - prior)
        return round(delta, 6)
    except Exception:
        return 0.0


def _task_cost_total(db, *, run_id: str) -> float:
    try:
        from cmbagent.database.models import CostRecord  # type: ignore
        rows = db.query(CostRecord).filter(CostRecord.run_id == run_id).all()
        return round(sum(float(r.cost_usd or 0) for r in rows), 6)
    except Exception:
        return 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Read stage content
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/{task_id}/stages/{stage_num}/content", response_model=StageContentResponse)
async def get_stage_content(task_id: str, stage_num: int) -> StageContentResponse:
    if stage_num < 1 or stage_num > len(nl.STAGE_DEFS):
        raise HTTPException(status_code=400, detail="invalid stage number")

    db = _get_db()
    try:
        from cmbagent.database.models import WorkflowRun  # type: ignore
        run = db.query(WorkflowRun).filter(WorkflowRun.id == task_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail="task not found")

        repo = _stage_repo(db, session_id=run.session_id)
        stage = next((s for s in repo.list_stages(parent_run_id=task_id) if s.stage_number == stage_num), None)
        if stage is None:
            raise HTTPException(status_code=404, detail="stage not found")

        out = stage.output_data or {}
        shared = out.get("shared") or {}
        files = out.get("files") or []
        # Find the primary content for this stage. The shared-state map stores
        # raw structures (e.g. stage 1's "setup" key holds the setup dict), so
        # the response's ``content: Optional[str]`` field can only accept the
        # value when it's actually a string — otherwise fall back to the
        # ``primary_preview`` markdown stored at completion time, or render the
        # stage's on-disk markdown file as a last resort. This avoids the
        # HTTP 500 we used to hit for stage 1 (dict-as-string Pydantic error).
        sd = nl.stage_def(stage_num)
        raw_primary = shared.get(sd["shared_key"])
        primary_text = raw_primary if isinstance(raw_primary, str) else None
        if not primary_text:
            preview = out.get("primary_preview")
            if isinstance(preview, str):
                primary_text = preview
        if not primary_text and sd.get("file"):
            work_dir = _work_dir_for(task_id, run.session_id, base=None)
            md_path = os.path.join(work_dir, f"stage_{stage_num}", sd["file"])
            if os.path.isfile(md_path):
                try:
                    with open(md_path, "r", encoding="utf-8") as f:
                        primary_text = f.read()
                except OSError:
                    primary_text = None
        primary_text = primary_text or ""

        return StageContentResponse(
            stage_number=stage.stage_number,
            stage_name=stage.stage_name,
            status=stage.status,
            content=primary_text,
            shared_state=shared,
            output_files=files,
            link_validation=shared.get("link_validation") if stage_num == 2 else None,
        )
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────────────────────
# Console polling (REST fallback, PaperPulse-style)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/{task_id}/stages/{stage_num}/console")
async def get_stage_console(task_id: str, stage_num: int, since: int = 0) -> Dict[str, Any]:
    """Incremental console log fetch for a (task, stage) pair.

    The frontend polls this every ~1s with the running ``next_index`` so it
    receives only the new lines since the last call. It is the source of
    truth for streaming logs — the WebSocket is reserved for low-rate state
    transitions (``stage_completed`` / ``stage_failed``).

    ``is_done`` is set when the stage row's status is no longer ``running``,
    so the client can stop polling without an extra round-trip.
    """
    if stage_num < 1 or stage_num > len(nl.STAGE_DEFS):
        raise HTTPException(status_code=400, detail="invalid stage number")

    buf_key = f"{task_id}:{stage_num}"
    lines = console_capture.get_lines(buf_key, since_index=since)

    is_done = False
    status = "pending"
    error: Optional[str] = None
    db = _get_db()
    try:
        from cmbagent.database.models import WorkflowRun  # type: ignore
        run = db.query(WorkflowRun).filter(WorkflowRun.id == task_id).first()
        if run is not None:
            repo = _stage_repo(db, session_id=run.session_id)
            stage = next(
                (s for s in repo.list_stages(parent_run_id=task_id) if s.stage_number == stage_num),
                None,
            )
            if stage is not None:
                status = stage.status
                error = stage.error_message
                is_done = stage.status in ("completed", "failed")
    finally:
        db.close()

    return {
        "lines": lines,
        "next_index": since + len(lines),
        "stage_num": stage_num,
        "status": status,
        "is_done": is_done,
        "error": error,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Update stage content (manual edits)
# ──────────────────────────────────────────────────────────────────────────────

@router.put("/{task_id}/stages/{stage_num}/content", response_model=NewsletterStageResponse)
async def update_stage_content(task_id: str, stage_num: int, req: NewsletterContentUpdateRequest) -> NewsletterStageResponse:
    if stage_num < 1 or stage_num > len(nl.STAGE_DEFS):
        raise HTTPException(status_code=400, detail="invalid stage number")

    db = _get_db()
    try:
        from cmbagent.database.models import WorkflowRun  # type: ignore
        run = db.query(WorkflowRun).filter(WorkflowRun.id == task_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail="task not found")

        session_id = run.session_id
        repo = _stage_repo(db, session_id=session_id)
        stage = next((s for s in repo.list_stages(parent_run_id=task_id) if s.stage_number == stage_num), None)
        if stage is None:
            raise HTTPException(status_code=404, detail="stage not found")

        sd = nl.stage_def(stage_num)
        key = sd["shared_key"] if req.field == "default" else req.field

        out = stage.output_data or {}
        shared = out.get("shared") or {}
        shared[key] = req.content
        out["shared"] = shared

        # Persist to disk so resume / re-run picks up the manual edit.
        work_dir = _work_dir_for(task_id, session_id, base=None)
        if sd.get("file"):
            stage_dir = os.path.join(work_dir, f"stage_{stage_num}")
            os.makedirs(stage_dir, exist_ok=True)
            with open(os.path.join(stage_dir, sd["file"]), "w", encoding="utf-8") as f:
                f.write(req.content)

        # Mark all later stages stale.
        for later in [s for s in repo.list_stages(parent_run_id=task_id) if s.stage_number > stage_num]:
            repo.update_stage(parent_run_id=task_id, stage_number=later.stage_number, status="pending",
                              started_at=None, completed_at=None, error_message=None)

        repo.update_stage(parent_run_id=task_id, stage_number=stage_num, output_data=out)
        return _stage_to_response(stage)
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────────────────────
# Task list / state / pdf
# ──────────────────────────────────────────────────────────────────────────────

# NOTE: ``/recent`` MUST be declared before ``/{task_id}`` — FastAPI matches
# routes top-to-bottom and ``/{task_id}`` would otherwise swallow the literal
# string "recent" as a task id and return 404.
@router.get("/recent", response_model=List[NewsletterRecentTaskResponse])
async def list_recent(limit: int = 25) -> List[NewsletterRecentTaskResponse]:
    db = _get_db()
    try:
        from cmbagent.database.models import WorkflowRun  # type: ignore
        runs = (
            db.query(WorkflowRun)
              .filter(WorkflowRun.session_id == "newsletter")
              .order_by(WorkflowRun.started_at.desc())
              .limit(max(1, min(limit, 200)))
              .all()
        )
        out: List[NewsletterRecentTaskResponse] = []
        for run in runs:
            repo = _stage_repo(db, session_id=run.session_id)
            stages = repo.list_stages(parent_run_id=run.id)
            completed = sum(1 for s in stages if s.status == "completed")
            total = max(1, len(stages))
            running_stage = next((s.stage_number for s in stages if s.status == "running"), None)
            next_pending = next((s.stage_number for s in stages if s.status == "pending"), None)
            progress_pct = (completed / total) * 100
            all_done = completed == total and total == len(nl.STAGE_DEFS)
            if not all_done and progress_pct >= 100:
                progress_pct = 99.0
            out.append(NewsletterRecentTaskResponse(
                task_id=run.id,
                title=(run.meta or {}).get("title") if isinstance(run.meta, dict) else None,
                status=run.status,
                created_at=_run_created_at(run),
                current_stage=running_stage or next_pending,
                progress_percent=round(progress_pct, 1),
            ))
        return out
    finally:
        db.close()


@router.get("/{task_id}", response_model=NewsletterTaskStateResponse)
async def get_task_state(task_id: str) -> NewsletterTaskStateResponse:
    db = _get_db()
    try:
        from cmbagent.database.models import WorkflowRun  # type: ignore
        run = db.query(WorkflowRun).filter(WorkflowRun.id == task_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail="task not found")

        repo = _stage_repo(db, session_id=run.session_id)
        stages = sorted(repo.list_stages(parent_run_id=task_id), key=lambda s: s.stage_number)

        completed = sum(1 for s in stages if s.status == "completed")
        total = max(1, len(stages))

        work_dir = _work_dir_for(task_id, run.session_id, base=None)
        setup = session_manager.load_setup(work_dir)

        running_stage = next((s.stage_number for s in stages if s.status == "running"), None)
        next_pending = next((s.stage_number for s in stages if s.status == "pending"), None)

        # Progress should only hit 100% once *every* stage is completed —
        # otherwise we're partway through the pipeline (e.g. stage 5 still
        # rendering its score card / PDF after the LLM call). Clamp at 99%
        # while anything is still running or pending so the UI never lies
        # about completion.
        progress_pct = (completed / total) * 100
        all_done = completed == total and total == len(nl.STAGE_DEFS)
        if not all_done and progress_pct >= 100:
            progress_pct = 99.0

        return NewsletterTaskStateResponse(
            task_id=task_id,
            title=(run.meta or {}).get("title") if isinstance(run.meta, dict) else None,
            status=run.status,
            work_dir=work_dir,
            created_at=_run_created_at(run),
            stages=[_stage_to_response(s) for s in stages],
            current_stage=running_stage or next_pending,
            progress_percent=round(progress_pct, 1),
            setup=setup,
            total_cost_usd=_task_cost_total(db, run_id=task_id),
        )
    finally:
        db.close()


@router.delete("/{task_id}")
async def delete_task(task_id: str) -> Dict[str, Any]:
    """Delete a task: remove DB rows (WorkflowRun + TaskStages) and the work_dir on disk."""
    db = _get_db()
    try:
        from cmbagent.database.models import TaskStage, WorkflowRun  # type: ignore
        run = db.query(WorkflowRun).filter(WorkflowRun.id == task_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail="task not found")

        session_id = run.session_id
        work_dir = _work_dir_for(task_id, session_id, base=None)

        db.query(TaskStage).filter(TaskStage.parent_run_id == task_id).delete(synchronize_session=False)
        db.delete(run)
        db.commit()
    finally:
        db.close()

    if os.path.isdir(work_dir):
        try:
            shutil.rmtree(work_dir)
        except OSError as exc:
            logger.warning("delete_task_workdir_failed", task_id=task_id, error=str(exc))

    with _running_lock:
        for key in [k for k in _running.keys() if k.startswith(f"{task_id}:")]:
            t = _running.pop(key, None)
            if t and not t.done():
                t.cancel()

    return {"task_id": task_id, "deleted": True}


@router.post("/{task_id}/regenerate-pdf", response_model=CompilePdfResponse)
async def regenerate_pdf(task_id: str) -> CompilePdfResponse:
    """Re-run the PDF renderer on the latest Stage-5 markdown without re-running the LLM."""
    db = _get_db()
    try:
        from cmbagent.database.models import WorkflowRun  # type: ignore
        run = db.query(WorkflowRun).filter(WorkflowRun.id == task_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail="task not found")
        work_dir = _work_dir_for(task_id, run.session_id, base=None)
        setup = session_manager.load_setup(work_dir) or {}
    finally:
        db.close()

    md_path = os.path.join(work_dir, "stage_5", nl.stage_def(5)["file"])
    if not os.path.isfile(md_path):
        raise HTTPException(status_code=400, detail="Stage 5 has not been completed yet")
    with open(md_path, "r", encoding="utf-8") as f:
        md = f.read()

    industry_titles = ", ".join(i["industry"] for i in setup.get("industries", [])) or "Newsletter"
    title = f"{industry_titles} — {setup.get('date_from')} to {setup.get('date_to')}"
    pdf = render_pdf(markdown_text=md, output_dir=os.path.join(work_dir, "stage_5"), title=title, setup=setup)
    return CompilePdfResponse(
        pdf_path=pdf.pdf_path,
        success=pdf.success,
        backend_used=pdf.backend,
        error=pdf.error,
    )
