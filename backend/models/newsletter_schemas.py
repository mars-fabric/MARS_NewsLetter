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
    and NewsPulse use) — i.e. the planner+executor with cross-step memory. We
    expose only the two-mode surface (``one_shot`` / ``planning_and_control``)
    in the API and UI for clarity.
    """
    ONE_SHOT = "one_shot"
    PLANNING_AND_CONTROL = "planning_and_control"


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
    """
    stage_2_mode: CmbAgentMode = Field(default=CmbAgentMode.ONE_SHOT)
    stage_3_mode: CmbAgentMode = Field(default=CmbAgentMode.ONE_SHOT)
    stage_4_mode: CmbAgentMode = Field(default=CmbAgentMode.ONE_SHOT)
    stage_5_mode: CmbAgentMode = Field(default=CmbAgentMode.ONE_SHOT)

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

    audience: Optional[str] = Field(None, description="Free-text audience hint (e.g. 'CXOs at industrial firms')")

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


class ScoreCard(BaseModel):
    """Stage 5 authenticity scorecard — sent to UI alongside final markdown."""
    authenticity_score: int = Field(..., ge=0, le=100, description="0-100 authenticity rating")
    verdict: str = Field(..., description="Short verdict: 'production-ready' | 'needs-revision' | 'reject'")
    suggestions: List[str] = Field(default_factory=list, description="Concrete final suggestions for improvement")
    coverage_score: Optional[int] = Field(None, ge=0, le=100)
    citation_score: Optional[int] = Field(None, ge=0, le=100)
    factual_fidelity_score: Optional[int] = Field(None, ge=0, le=100)
    structural_completeness_score: Optional[int] = Field(None, ge=0, le=100)
    notes: Optional[str] = None


class StageContentResponse(BaseModel):
    stage_number: int
    stage_name: str
    status: str
    content: Optional[str] = None
    shared_state: Optional[Dict[str, Any]] = None
    output_files: Optional[List[str]] = None
    link_validation: Optional[List[LinkValidationResult]] = None
    score_card: Optional[ScoreCard] = None


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
