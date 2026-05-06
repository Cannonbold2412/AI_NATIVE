/** Mirrors backend `app/editor/dto.py` JSON shape. */

export type StepFlags = {
  is_destructive: boolean
  is_scroll: boolean
  generic_intent: boolean
}

export type StepScreenshotDTO = {
  full_url: string | null
  element_url: string | null
  scroll_url: string | null
  bbox: Record<string, number>
  viewport: string
  scroll_position: string
}

export type StepEditorDTO = {
  id: string
  step_index: number
  human_readable_description: string
  action_type: string
  intent: string
  final_intent: string
  url: string
  target: Record<string, unknown>
  selectors: Record<string, unknown>
  anchors_signals: Record<string, unknown>[]
  anchors_recovery: Record<string, unknown>[]
  validation: {
    wait_for: Record<string, unknown>
    success_conditions: Record<string, unknown>
  }
  recovery: Record<string, unknown>
  value: unknown
  scroll_mode: string | null
  scroll_selector: string | null
  scroll_amount: number | null
  input_binding: string | null
  screenshot: StepScreenshotDTO
  editable_fields: Record<string, boolean>
  flags: StepFlags
  parameter_bindings: Record<string, unknown>[]
  check_kind?: string
  check_pattern?: string
  check_threshold?: number
  check_selector?: string
  check_text?: string
}

export type SuggestionItem = {
  step_index: number
  severity: 'info' | 'warn' | 'error'
  code: string
  message: string
}

export type WorkflowResponse = {
  skill_id: string
  package_meta: Record<string, unknown>
  inputs: Record<string, unknown>[]
  steps: StepEditorDTO[]
  suggestions: SuggestionItem[]
  asset_base_url: string
}
