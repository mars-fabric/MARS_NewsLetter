export type StageStatus = 'pending' | 'running' | 'completed' | 'failed';

/**
 * The two modes the user picks per stage. ``planning_and_control`` is wired on
 * the backend to cmbagent's ``planning_and_control_context_carryover``
 * workflow (the same one PaperPulse and NewsPulse use), so the planner+executor
 * always retains step-to-step memory.
 */
export type CmbAgentMode = 'one_shot' | 'planning_and_control';

export type SourceMode = 'user_links_only' | 'ddgs_only' | 'combined';

export interface ModelOption {
  value: string;
  label: string;
}

export interface IndustryEntry {
  industry: string;
  industry_domain: string;
  sub_domains: string[];
}

export interface TaxonomyResponse {
  industries: IndustryEntry[];
  authentic_domain_hints: Record<string, string[]>;
  neutral_authority_domains: string[];
  version: string;
}

export interface IndustrySelection {
  industry: string;
  sub_domains: string[];
}

/**
 * Per-stage model overrides forwarded to cmbagent kwargs. Field names match
 * cmbagent's own kwarg names so the backend can splat them straight into the
 * call without any aliasing layer.
 */
export interface StageModelOverrides {
  // Used in both modes
  model?: string;
  researcher_model?: string;
  engineer_model?: string;
  web_surfer_model?: string;
  formatter_model?: string;
  // Planning_and_control roles
  planner_model?: string;
  plan_reviewer_model?: string;
  idea_maker_model?: string;
  idea_hater_model?: string;
  orchestration_model?: string;
}

/**
 * Per-stage cmbagent iteration knobs. Maps to
 * ``planning_and_control_context_carryover`` parameters and to ``one_shot``'s
 * ``max_rounds`` / ``max_n_attempts``. Anything left unset means "use cmbagent's
 * default".
 */
export interface StageIterationLimits {
  n_plan_reviews?: number;
  max_plan_steps?: number;
  max_n_attempts?: number;
  max_rounds_planning?: number;
  max_rounds_control?: number;
  max_rounds?: number;
}

export interface StageModeConfig {
  stage_2_mode: CmbAgentMode;
  stage_3_mode: CmbAgentMode;
  stage_4_mode: CmbAgentMode;
  stage_5_mode: CmbAgentMode;

  // Stage-2-specific
  stage_2_top_companies_count: number;
  stage_2_min_sources: number;
  stage_2_enrich_with_llm: boolean;

  stage_2_models: StageModelOverrides;
  stage_3_models: StageModelOverrides;
  stage_4_models: StageModelOverrides;
  stage_5_models: StageModelOverrides;

  stage_2_limits: StageIterationLimits;
  stage_3_limits: StageIterationLimits;
  stage_4_limits: StageIterationLimits;
  stage_5_limits: StageIterationLimits;
}

export interface NewsletterCreateRequest {
  title?: string | null;
  industries: IndustrySelection[];
  date_from: string;
  date_to: string;
  source_mode: SourceMode;
  user_urls: string[];
  audience?: string | null;
  mode_config: StageModeConfig;
  work_dir?: string | null;
}

export interface StageInfo {
  stage_number: number;
  stage_name: string;
  status: StageStatus;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
  mode?: string | null;
  cost_usd?: number | null;
}

export interface CreateResponse {
  task_id: string;
  work_dir: string;
  stages: StageInfo[];
}

export interface LinkValidationResult {
  url: string;
  reachable: boolean;
  status_code?: number | null;
  final_url?: string | null;
  domain?: string | null;
  is_authentic: boolean;
  authority_tier: 'official' | 'authority' | 'unknown';
  matched_industry?: string | null;
  notes?: string | null;
}

export interface ScoreCard {
  authenticity_score: number;
  verdict: 'production-ready' | 'needs-revision' | 'reject';
  citation_score?: number | null;
  factual_fidelity_score?: number | null;
  coverage_score?: number | null;
  structural_completeness_score?: number | null;
  suggestions: string[];
  notes?: string | null;
}

export interface StageContent {
  stage_number: number;
  stage_name: string;
  status: StageStatus;
  content?: string | null;
  shared_state?: Record<string, unknown> | null;
  output_files?: string[] | null;
  link_validation?: LinkValidationResult[] | null;
  score_card?: ScoreCard | null;
}

export interface TaskState {
  task_id: string;
  title?: string | null;
  status: string;
  work_dir?: string | null;
  created_at?: string | null;
  stages: StageInfo[];
  current_stage?: number | null;
  progress_percent: number;
  setup?: NewsletterCreateRequest | null;
  total_cost_usd?: number;
}

export interface RecentTask {
  task_id: string;
  title?: string | null;
  status: string;
  created_at?: string | null;
  current_stage?: number | null;
  progress_percent: number;
}

export const STAGE_NAMES: Record<number, string> = {
  1: 'Setup',
  2: 'Source Collection',
  3: 'Curation',
  4: 'Generation',
  5: 'Review & Publish',
};

export const STAGE_DESCRIPTIONS: Record<number, string> = {
  1: 'Pick industries, sub-domains, sources, style and per-stage agent modes.',
  2: 'Discover top-N companies, extract per-company news, and run industry-wide search (≥30 sources).',
  3: 'Deduplicate by story, group by sub-domain and company, tag categories and Top: yes/no.',
  4: 'Analyst outlines themes, writer drafts the 22-section professional newsletter (≥3500 words).',
  5: 'Critic finds issues, editor finalises, programmatic checks run, score card emitted, PDF rendered.',
};

/**
 * Per-stage accent colour. Used by panels to give each phase its own visual
 * identity (header gradient, console border glow, badge tint).
 */
export const STAGE_ACCENT: Record<number, string> = {
  1: '#06b6d4', // cyan — Setup
  2: '#22c55e', // emerald — Source Collection
  3: '#f59e0b', // amber — Curation
  4: '#8b5cf6', // violet — Generation
  5: '#3b82f6', // blue — Review & Publish
};

/**
 * Static list of LLM model choices shown in the per-stage model dropdowns.
 */
export const AVAILABLE_MODELS: ModelOption[] = [
  // OpenAI
  { value: 'gpt-4.1-2025-04-14', label: 'GPT-4.1' },
  { value: 'gpt-4.1-mini', label: 'GPT-4.1 Mini' },
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'gpt-4o-mini-2024-07-18', label: 'GPT-4o Mini' },
  { value: 'gpt-4.5-preview-2025-02-27', label: 'GPT-4.5 Preview' },
  { value: 'gpt-5-2025-08-07', label: 'GPT-5' },
  { value: 'o3-mini-2025-01-31', label: 'o3-mini' },
  // Google Gemini
  { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
  { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
  // Anthropic
  { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
  { value: 'claude-3.5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
  // AWS Bedrock
  { value: 'bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0', label: 'Claude 3.5 Sonnet v2 (Bedrock)' },
  { value: 'bedrock/anthropic.claude-sonnet-4-20250514-v1:0', label: 'Claude Sonnet 4 (Bedrock)' },
  { value: 'bedrock/amazon.nova-pro-v1:0', label: 'Amazon Nova Pro (Bedrock)' },
  { value: 'bedrock/amazon.nova-lite-v1:0', label: 'Amazon Nova Lite (Bedrock)' },
];

/**
 * Default cmbagent model per role. Used for the "(default: xxx)" placeholder
 * in the dropdowns. Mirrors the cmbagent upstream defaults.
 */
export const STAGE_MODEL_DEFAULTS: Record<keyof StageModelOverrides, string> = {
  model: 'gpt-4o',
  researcher_model: 'gpt-4o',
  engineer_model: 'gpt-4o',
  web_surfer_model: 'gpt-4o',
  formatter_model: 'gpt-4o-mini',
  planner_model: 'gpt-4o',
  plan_reviewer_model: 'o3-mini',
  idea_maker_model: 'gpt-4o',
  idea_hater_model: 'gpt-4o',
  orchestration_model: 'gpt-4.1',
};

/**
 * Default cmbagent iteration knobs. Only used as the "(default)" hint in the
 * limits inputs — leave a field blank in the UI to keep cmbagent's own default.
 */
export const STAGE_LIMIT_DEFAULTS: Record<keyof StageIterationLimits, number> = {
  n_plan_reviews: 1,
  max_plan_steps: 6,
  max_n_attempts: 3,
  max_rounds_planning: 50,
  max_rounds_control: 30,
  max_rounds: 30,
};
