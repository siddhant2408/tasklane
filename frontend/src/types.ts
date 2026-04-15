export type Status = 'todo' | 'plan' | 'in_progress' | 'in_review' | 'in_testing' | 'done' | 'error'
export type Urgency = 'low' | 'normal' | 'high' | 'critical'
export type RunStatus =
  | 'running' | 'completed' | 'crashed' | 'iteration_exceeded'
  | 'killed' | 'budget_exceeded' | 'api_error' | 'superseded'

export const LANE_ORDER: Status[] = ['todo', 'plan', 'in_progress', 'in_review', 'in_testing', 'done']
export const ALL_LANES: Status[] = [...LANE_ORDER, 'error']

export const LANE_LABELS: Record<Status, string> = {
  todo:        'Todo',
  plan:        'Plan',
  in_progress: 'In Progress',
  in_review:   'In Review',
  in_testing:  'In Testing',
  done:        'Done',
  error:       'Error',
}

export interface Ticket {
  id: number
  title: string
  description: string
  persona: string
  status: Status
  urgency: Urgency
  tools_json: string[]
  agents_json: Record<string, string | null> | null
  models_json: Record<string, string>
  workspace_path: string
  max_iterations: number | null
  locked: boolean
  created_at: string
  updated_at: string
  active_run_id: number | null
}

export interface Run {
  id: number
  ticket_id: number
  lane: string
  agent_type: string
  persona: string
  model: string
  max_iterations: number
  status: RunStatus
  started_at: string
  ended_at: string | null
  final_report: string | null
  error: string | null
  iterations: number
  input_tokens: number
  output_tokens: number
}

export interface LogEntry {
  id: number
  run_id: number
  seq: number
  ts: string
  level: string
  message: string
}

export interface ToolInfo {
  name: string
  description: string
  group: string
  dangerous: boolean
}

export interface PersonaInfo {
  name: string
  label: string
  description: string
  default_tools: string[]
  active_lanes: string[]
  suggested_model: string
  description_template: string
}

export interface BoardState {
  lanes: Record<Status, Ticket[]>
}
