"""Pydantic request/response schemas for the NewsLetter API."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────

class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CmbAgentMode(str, Enum):
    """Mode used to invoke mars_cmbagent for AI stages.

    ``planning_and_control`` is wired to cmbagent's
    ``planning_and_control_context_carryover`` workflow (the variant PaperPulse
    and NewsPulse use) — i.e. the planner+executor with cross-step memory.
    ``deep_research`` is cmbagent's multi-step research workflow (planner →
    reviewer → iterative executor with full context carryover). It is the
    strongest — and slowest — mode; reserved for Stage-4 ``deep`` sections
    where the user asked for genuine research-grade depth.
    """
    ONE_SHOT = "one_shot"
    PLANNING_AND_CONTROL = "planning_and_control"
    DEEP_RESEARCH = "deep_research"


class SourceMode(str, Enum):
    """Where Stage 2 sources its raw material from."""
    USER_LINKS_ONLY = "user_links_only"
    DDGS_ONLY = "ddgs_only"
    COMBINED = "combined"


# ──────────────────────────────────────────────────────────────────────────────
# Industry selection
# ──────────────────────────────────────────────────────────────────────────────

class IndustrySelection(BaseModel):
    """A single industry pick + its chosen sub-domains."""
    industry: str = Field(..., description="Industry name (must exist in the taxonomy)")
    sub_domains: List[str] = Field(default_factory=list, description="One or more sub-domains under this industry")

    @field_validator("sub_domains")
    @classmethod
    def _at_least_one_sub_domain(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("At least one sub_domain is required for each industry")
        return v


# ──────────────────────────────────────────────────────────────────────────────
# Stage mode configuration
# ──────────────────────────────────────────────────────────────────────────────

class StageModelOverrides(BaseModel):
    """Per-stage model overrides forwarded to cmbagent kwargs.

    All fields are optional. Field names below mirror cmbagent's own kwargs so
    the dict can be splatted directly into ``one_shot`` / ``planning_and_control``.
    Empty values are dropped at dispatch time so cmbagent defaults take over.
    """
    # Used by both modes
    model: Optional[str] = Field(None, description="Primary agent model. In one_shot it is the researcher/engineer; in planning_and_control it is the executor (engineer_model).")
    researcher_model: Optional[str] = Field(None, description="Researcher model (planning_and_control)")
    engineer_model: Optional[str] = Field(None, description="Engineer / executor model")
    web_surfer_model: Optional[str] = Field(None, description="Web surfer model (DDGS / web tools)")
    formatter_model: Optional[str] = Field(None, description="Response formatter model")

    # Planning-and-control roles
    planner_model: Optional[str] = Field(None)
    plan_reviewer_model: Optional[str] = Field(None)
    idea_maker_model: Optional[str] = Field(None)
    idea_hater_model: Optional[str] = Field(None)
    orchestration_model: Optional[str] = Field(None, description="Orchestration / default LLM model fallback")

    def as_overrides(self) -> Dict[str, str]:
        """Return only the fields the user actually set."""
        return {k: v for k, v in self.model_dump().items() if v}


class StageIterationLimits(BaseModel):
    """Per-stage cmbagent iteration knobs.

    Maps directly to ``planning_and_control_context_carryover`` parameters and
    to ``one_shot``'s ``max_rounds`` / ``max_n_attempts``. Anything left unset
    means "use cmbagent's default".
    """
    n_plan_reviews: Optional[int] = Field(None, ge=0, le=10, description="Plan-review iterations (planning_and_control)")
    max_plan_steps: Optional[int] = Field(None, ge=1, le=20, description="Cap on the planner's emitted step count")
    max_n_attempts: Optional[int] = Field(None, ge=1, le=20, description="Per-step retry cap")
    max_rounds_planning: Optional[int] = Field(None, ge=1, le=200, description="Max rounds during planning phase")
    max_rounds_control: Optional[int] = Field(None, ge=1, le=2000, description="Max rounds during control / execution phase")
    max_rounds: Optional[int] = Field(None, ge=1, le=200, description="one_shot only: total round cap")

    def as_overrides(self) -> Dict[str, int]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class StageModeConfig(BaseModel):
    """Per-stage cmbagent invocation mode + model overrides + iteration limits.

    Stage 1 is pure inputs and ignores all of this. Stages 2–5 each get their
    own mode/models/limits — every cmbagent knob is reachable from the UI.
    Defaults are tuned for production newsletter quality:

    * All stages default to ``one_shot`` (reliable, fast, zero planner
      overhead). Planning-and-control is still available via the UI but is
      slower and requires a well-tuned iteration budget.
    * Stage 5 (review/quality) runs as a LangGraph post-processor regardless
      of this setting.
    * Stage 2 has an explicit ``top_companies_count`` so we discover the top-N
      companies in the chosen industries first, then drill into per-company news.

    NOTE: per-stage *mode* now defaults to ``None`` so the backend ``.env``
    (``NEWSLETTER_STAGE_{n}_MODE`` / ``NEWSLETTER_DEFAULT_MODE``) is the single
    source of truth for invocation strategy. The per-stage strategy UI was
    removed; a value here (if ever supplied) still wins for backward compat.
    """
    stage_2_mode: Optional[CmbAgentMode] = Field(default=None)
    stage_3_mode: Optional[CmbAgentMode] = Field(default=None)
    stage_4_mode: Optional[CmbAgentMode] = Field(default=None)
    stage_5_mode: Optional[CmbAgentMode] = Field(default=None)

    # Stage-2 specific knobs
    stage_2_top_companies_count: int = Field(default=12, ge=0, le=30, description="Top-N companies to discover via web search before per-company news extraction. 0 disables the company discovery substep.")
    stage_2_min_sources: int = Field(default=30, ge=10, le=200, description="Minimum total sources Stage 2 must collect. The planner enforces this in its instructions.")
    stage_2_enrich_with_llm: bool = Field(default=True, description="When user_links_only mode is in use, optionally enrich the validated user URLs into structured items.")

    stage_2_models: StageModelOverrides = Field(default_factory=StageModelOverrides)
    stage_3_models: StageModelOverrides = Field(default_factory=StageModelOverrides)
    stage_4_models: StageModelOverrides = Field(default_factory=StageModelOverrides)
    stage_5_models: StageModelOverrides = Field(default_factory=StageModelOverrides)

    stage_2_limits: StageIterationLimits = Field(default_factory=StageIterationLimits)
    stage_3_limits: StageIterationLimits = Field(default_factory=StageIterationLimits)
    stage_4_limits: StageIterationLimits = Field(default_factory=StageIterationLimits)
    stage_5_limits: StageIterationLimits = Field(default_factory=StageIterationLimits)


# ──────────────────────────────────────────────────────────────────────────────
# Setup (Stage 1) request
# ──────────────────────────────────────────────────────────────────────────────

class NewsletterCreateRequest(BaseModel):
    """POST /api/newsletter/create — captures Stage 1 (Setup) input."""
    title: Optional[str] = Field(None, description="Optional human-readable title for this newsletter run")
    industries: List[IndustrySelection] = Field(..., description="One or more industries with their sub-domain picks")

    date_from: str = Field(..., description="ISO date (YYYY-MM-DD) — start of coverage window")
    # date_to is always overridden to today server-side (see _coverage_window_is_sane).
    # The frontend sends today's date; even if it doesn't, we coerce it here.
    date_to: str = Field(default="", description="ISO date (YYYY-MM-DD) — end of coverage window (always today)")

    source_mode: SourceMode = Field(default=SourceMode.COMBINED)
    user_urls: List[str] = Field(default_factory=list, description="URLs supplied directly by the user")

    analyze_user_links: bool = Field(
        default=False,
        description="When true, the user's own links are first-class analysis targets: they are "
        "auto-pinned, never skipped/filtered at any stage, and Stage 4 produces a dedicated "
        "analysis of their content. Use this when the user's organisation has authorised access "
        "to these sources and wants them analysed rather than merely cited.",
    )

    executive_grade: bool = Field(
        default=False,
        description="When true, Stage 4 auto-elevates the hero sections a CEO/CTO reads first "
        "(Executive Summary, Top Story, Focus Topic Deep Dive, Trend Intelligence, "
        "Forward-Looking / Strategic) to a mars_cmbagent deep_research pre-pass for "
        "research-grade synthesis, without the user marking each section 'deep' in Gate B.",
    )

    audience: Optional[str] = Field(None, description="Free-text audience hint (e.g. 'CXOs at industrial firms')")

    # ── Enhanced Stage-1 input (redesign) ──────────────────────────────────────
    focus_prompt: Optional[str] = Field(
        None,
        description="Free-text description of what the user actually cares about — "
        "drives Stage 2 discovery queries and Stage 4 analysis emphasis.",
    )
    tone: Optional[str] = Field(
        None,
        description="Desired editorial tone (e.g. 'analytical', 'executive briefing', 'technical deep-dive').",
    )
    pinned_urls: List[str] = Field(
        default_factory=list,
        description="URLs the user trusts and wants preserved end-to-end. These bypass "
        "the Stage-3 drop filter and are always cited if relevant.",
    )
    shape_hint: Optional[str] = Field(
        None,
        description="Free-text hint about the desired newsletter shape/structure, used as the "
        "default when the user does not supply an explicit Stage-4 section template.",
    )

    mode_config: StageModeConfig = Field(default_factory=StageModeConfig)

    work_dir: Optional[str] = Field(None, description="Override the base work directory")

    @field_validator("industries")
    @classmethod
    def _at_least_one_industry(cls, v: List[IndustrySelection]) -> List[IndustrySelection]:
        if not v:
            raise ValueError("At least one industry must be selected")
        return v

    @field_validator("user_urls")
    @classmethod
    def _user_urls_basic(cls, v: List[str]) -> List[str]:
        cleaned: List[str] = []
        for url in v:
            url = (url or "").strip()
            if not url:
                continue
            if not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError(f"URL must start with http:// or https://: {url}")
            cleaned.append(url)
        return cleaned

    @field_validator("pinned_urls")
    @classmethod
    def _pinned_urls_basic(cls, v: List[str]) -> List[str]:
        cleaned: List[str] = []
        for url in v:
            url = (url or "").strip()
            if not url:
                continue
            if not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError(f"Pinned URL must start with http:// or https://: {url}")
            cleaned.append(url)
        return cleaned

    @field_validator("date_from", "date_to")
    @classmethod
    def _is_iso_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Date must be ISO format YYYY-MM-DD, got {v!r}") from e
        return v

    @model_validator(mode="after")
    def _coverage_window_is_sane(self) -> "NewsletterCreateRequest":
        today = date.today()
        # Always coerce date_to to today — the UI only exposes start date.
        self.date_to = today.isoformat()
        d_from = date.fromisoformat(self.date_from)
        if d_from > today:
            raise ValueError(f"date_from ({self.date_from}) cannot be in the future (today is {today.isoformat()})")
        return self


# ──────────────────────────────────────────────────────────────────────────────
# Per-stage execute / content
# ──────────────────────────────────────────────────────────────────────────────

class NewsletterExecuteRequest(BaseModel):
    """POST /api/newsletter/{task_id}/stages/{num}/execute — per-run overrides."""
    config_overrides: Optional[Dict[str, Any]] = Field(None, description="Per-stage model overrides")
    mode_override: Optional[CmbAgentMode] = Field(None, description="Override the cmbagent mode for this stage only")


class NewsletterContentUpdateRequest(BaseModel):
    """PUT /api/newsletter/{task_id}/stages/{num}/content"""
    content: str
    field: str = Field("default", description="shared_state key to update; 'default' picks the stage's primary key")


# ──────────────────────────────────────────────────────────────────────────────
# Gate A — Link prioritization (between Stage 2 and Stage 3)
# ──────────────────────────────────────────────────────────────────────────────

class LinkAction(str, Enum):
    """User decision on a discovered source link before curation."""
    PIN = "pin"          # must survive curation and be cited if relevant
    BOOST = "boost"      # rank higher during curation
    NORMAL = "normal"    # default treatment
    EXCLUDE = "exclude"  # drop before curation


class LinkPriority(BaseModel):
    """A single user decision applied to one discovered link."""
    url: str = Field(..., description="The source URL this decision applies to")
    action: LinkAction = Field(default=LinkAction.NORMAL)
    weight: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Optional explicit relevance weight (0-1) overriding the discovered score.",
    )


class LinkPrioritiesRequest(BaseModel):
    """POST /api/newsletter/{task_id}/gate/links — user link prioritization (Gate A).

    Applied to the Stage-2 verified source list before Stage 3 curation runs.
    """
    priorities: List[LinkPriority] = Field(default_factory=list)
    add_urls: List[str] = Field(
        default_factory=list,
        description="Extra URLs the user wants injected (auto-pinned + fetch-verified).",
    )
    min_relevance: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Curation drop threshold override. Lower keeps more sources (relaxes over-filtering).",
    )

    @field_validator("add_urls")
    @classmethod
    def _add_urls_basic(cls, v: List[str]) -> List[str]:
        cleaned: List[str] = []
        for url in v:
            url = (url or "").strip()
            if not url:
                continue
            if not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError(f"URL must start with http:// or https://: {url}")
            cleaned.append(url)
        return cleaned


# ──────────────────────────────────────────────────────────────────────────────
# Gate B — Section template selection (between Stage 3 and Stage 4)
# ──────────────────────────────────────────────────────────────────────────────

class SectionDepth(str, Enum):
    """How much analytical effort Stage 4 spends on a section."""
    LIGHT = "light"        # one_shot summary (~180 words)
    STANDARD = "standard"  # one_shot with structured analysis (~340 words)
    DEEP = "deep"          # cmbagent deep_research multi-step analysis (~650 words)


class SectionSpecRequest(BaseModel):
    """A single user-chosen report section (Gate B)."""
    title: str = Field(..., description="Section heading as it should appear in the report")
    depth: SectionDepth = Field(default=SectionDepth.STANDARD)
    points: Optional[int] = Field(
        None, ge=1, le=20,
        description="How many distinct key points/items this section should cover "
        "(e.g. 5 trends). Each point is expanded to the requested depth.",
    )
    guidance: Optional[str] = Field(
        None, description="Free-text instructions for what this section should analyse/cover.",
    )
    word_count: Optional[int] = Field(
        None, ge=50, le=2000,
        description="Custom word-count target for this section. Overrides the depth-derived "
        "budget when provided (use alongside depth='standard' for precise control).",
    )


class ReportTemplateRequest(BaseModel):
    """POST /api/newsletter/{task_id}/gate/template — user report template (Gate B).

    Replaces the fixed 22 canonical sections. Applied before Stage 4 generation.
    """
    sections: List[SectionSpecRequest] = Field(
        ..., description="Ordered list of sections the user wants generated.",
    )
    tone: Optional[str] = Field(None, description="Override editorial tone for this report.")
    audience: Optional[str] = Field(None, description="Override audience for this report.")

    @field_validator("sections")
    @classmethod
    def _at_least_one_section(cls, v: List[SectionSpecRequest]) -> List[SectionSpecRequest]:
        if not v:
            raise ValueError("At least one section is required")
        return v


# ──────────────────────────────────────────────────────────────────────────────
# Responses
# ──────────────────────────────────────────────────────────────────────────────

class NewsletterStageResponse(BaseModel):
    stage_number: int
    stage_name: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    mode: Optional[str] = None
    cost_usd: Optional[float] = None


class NewsletterCreateResponse(BaseModel):
    task_id: str
    work_dir: str
    stages: List[NewsletterStageResponse]


class LinkValidationResult(BaseModel):
    url: str
    reachable: bool
    status_code: Optional[int] = None
    final_url: Optional[str] = None
    domain: Optional[str] = None
    is_authentic: bool = False
    authority_tier: str = Field("unknown", description="official | authority | neutral | unknown")
    notes: Optional[str] = None


class StageContentResponse(BaseModel):
    stage_number: int
    stage_name: str
    status: str
    content: Optional[str] = None
    shared_state: Optional[Dict[str, Any]] = None
    output_files: Optional[List[str]] = None
    link_validation: Optional[List[LinkValidationResult]] = None


class NewsletterTaskStateResponse(BaseModel):
    task_id: str
    title: Optional[str] = None
    status: str
    work_dir: Optional[str] = None
    created_at: Optional[str] = None
    stages: List[NewsletterStageResponse]
    current_stage: Optional[int] = None
    progress_percent: float = 0.0
    setup: Optional[Dict[str, Any]] = None
    total_cost_usd: float = 0.0


class NewsletterRecentTaskResponse(BaseModel):
    task_id: str
    title: Optional[str] = None
    status: str
    created_at: Optional[str] = None
    current_stage: Optional[int] = None
    progress_percent: float = 0.0


class TaxonomyResponse(BaseModel):
    """GET /api/newsletter/taxonomy — taxonomy + domain hints used by the UI pickers."""
    industries: List[Dict[str, Any]]
    authentic_domain_hints: Dict[str, List[str]]
    neutral_authority_domains: List[str]
    version: str


class CompilePdfResponse(BaseModel):
    pdf_path: Optional[str] = None
    success: bool
    backend_used: Optional[str] = None
    error: Optional[str] = None
