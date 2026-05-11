/**
 * Multi-provider LLM types — shared with the Settings dialog.
 *
 * Mirrors ``MARS-PaperPulse/frontend/types/providers.ts`` so the same
 * ProviderSettings UI compiles in both products.
 */

export type ProviderStatusType =
  | 'configured'
  | 'validated'
  | 'invalid'
  | 'not_configured'
  | 'error';

export interface CredentialField {
  name: string;
  display_name: string;
  description: string;
  required: boolean;
  field_type: 'password' | 'text' | 'textarea' | 'url' | 'select';
  placeholder: string;
  validation_pattern: string;
  options: { value: string; label: string }[];
  has_value: boolean;
  masked_value: string;
}

export interface ProviderModel {
  model_id: string;
  display_name: string;
  context_window: number;
  max_output_tokens: number;
  supports_vision: boolean;
  category: string;
}

export interface Provider {
  provider_id: string;
  display_name: string;
  status: ProviderStatusType;
  credential_fields: CredentialField[];
  models: ProviderModel[];
}

export interface ProviderTestResult {
  success: boolean;
  message: string;
  latency_ms?: number;
  error_details?: string;
  models_available?: string[];
}

export interface ProvidersListResponse {
  providers: Provider[];
  active_provider: string | null;
  total_models: number;
  timestamp: number;
}

export interface AvailableModelsResponse {
  models: { value: string; label: string; provider: string }[];
  provider_count: number;
  timestamp: number;
}
