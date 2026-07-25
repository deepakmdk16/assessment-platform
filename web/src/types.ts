// Single source of truth for the UI-facing language list (the agent enforces what
// it actually supports). `Language` is derived so the two never drift.
export const LANGUAGES = [
  'python',
  'javascript',
  'java',
  'cpp',
  'c',
  'go',
  'ruby',
  'rust',
] as const

export type Language = (typeof LANGUAGES)[number]

export type TestCaseCategory = 'correctness' | 'performance'

/** A paginated slice of a collection. `total` is the full count (before
 *  limit/offset), so the UI can show "X–Y of Z" and a pager in one request. */
export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface TestCaseIn {
  name: string
  stdin: string
  expected: string
  category: TestCaseCategory
  weight: number
}

export interface TestCaseOut extends TestCaseIn {
  id: string
}

export interface QuestionIn {
  // Optional: the UI omits it and the server generates slug(title)+suffix (A6).
  id?: string
  title: string
  prompt: string
  constraints: string
  time_limit_s: number
  pass_threshold: number
  required_complexity: string
  example_input: string
  example_output: string
  difficulty?: string
  reference_solution?: string | null
  reference_language?: string | null
  duration_minutes?: number | null
  test_cases: TestCaseIn[]
}

export interface QuestionOut extends Omit<QuestionIn, 'test_cases'> {
  id: string
  status: string
  test_cases: TestCaseOut[]
  created_at: string
  updated_at: string
}

export interface QuestionDraftIn {
  brief: string
  language: Language
  difficulty?: string
  target_complexity?: string
}

export interface QuestionDraftOut {
  question: QuestionIn
  warnings: string[]
  reference_solution: string | null
  reference_language: string | null
  engine: string
  cost_usd: number | null
}

export interface User {
  id: string
  email: string
  name: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
}

export type InviteStatus = string

/** Per-recipient outcome of the invite email. Returned only on create. */
export interface InviteDelivery {
  recipient: string
  sent: boolean
  error: string | null
}

export interface Invite {
  token: string
  url: string
  /** Exactly one is set: a single-question invite has question_id; a T4
   *  assessment invite has assessment_id. */
  question_id: string | null
  assessment_id: string | null
  recipients: string[]
  expires_at: string | null
  status: InviteStatus
  deliveries: InviteDelivery[]
}

/** A question inside an assessment, with its order and denormalized title. */
export interface AssessmentQuestionRef {
  question_id: string
  position: number
  title: string
}

/** `GET/POST /assessments` — a named, ordered set of questions with a total timer. */
export interface AssessmentOut {
  id: string
  title: string
  duration_minutes: number | null
  status: string
  created_at: string
  updated_at: string
  questions: AssessmentQuestionRef[]
}

export interface AssessmentIn {
  // Optional: the UI omits it and the server generates slug(title)+suffix (A6).
  id?: string
  title: string
  duration_minutes?: number | null
  question_ids: string[]
}

export interface InviteQuestionPublic {
  title: string
  prompt: string
  constraints: string
  example_input: string
  example_output: string
  time_limit_s: number
}

/** A question inside the multi-question assessment flow (T4): the safe view plus
 *  the id run/submit target and whether this candidate has already submitted it. */
export interface CandidateQuestionPublic extends InviteQuestionPublic {
  id: string
  submitted: boolean
}

/** `GET /invite/{token}` — a liveness probe only. The question deliberately isn't
 *  here: it's handed out by `POST /invite/{token}/start` once the candidate has
 *  identified as an invited recipient. */
export interface InviteStatusResponse {
  status: string
}

/** `POST /invite/{token}/start` — the question, released after the email check. */
export interface InviteStartResponse {
  /** The first question — kept so the pre-T4 single-question UI keeps working. */
  question: InviteQuestionPublic
  /** The ordered question set (T4). Length 1 for a legacy invite; the
   *  multi-question flow renders when there's more than one. */
  questions?: CandidateQuestionPublic[]
  languages: Language[]
  /** Server-authoritative submit deadline (ISO). null when untimed. The countdown
   *  runs to this, and the server enforces it on submit. */
  deadline?: string | null
}

export interface SubmitResponse {
  submission_id: string
  status: string
}

/** `POST /invite/{token}/run` — the candidate's code against their own stdin. */
export interface RunResponse {
  stdout: string
  stderr: string | null
  duration_s: number
  timed_out: boolean
  compile_error: string | null
}

/**
 * One test case as the candidate may see it: pass/fail and timing only.
 * No name, input, expected or actual — that's the answer key, and it's stripped
 * server-side (the agent doesn't even send it on this path).
 */
export interface CandidateTestOutcome {
  index: number
  category: TestCaseCategory
  status: ResultCaseStatus
  duration_s: number
}

/** `POST /invite/{token}/run-tests` — the pre-submit rehearsal. */
export interface RunTestsResponse {
  total: number
  passed: number
  compile_error: string | null
  test_cases: CandidateTestOutcome[]
}

export interface SubmissionRow {
  submission_id: string
  candidate_name: string
  candidate_email: string
  language: Language
  status: string
  verdict?: string
  score_pct?: number
  created_at: string
}

/** A row in the global Submissions list (`GET /submissions`). Lean by design —
 *  the heavy `code`/`full_result` blobs are fetched per-id on the detail page. */
export interface SubmissionSummary {
  id: string
  question_id: string
  candidate: string
  candidate_email?: string | null
  language: Language
  status: string
  agent_job_id: string | null
  created_at: string
  verdict?: string
  score_pct?: number
}

/** How one test case came out. Mirrors the agent's runner outcome. */
export type ResultCaseStatus = 'PASS' | 'FAIL' | 'TLE'

export interface ResultTestCase {
  name: string
  category: TestCaseCategory
  weight: number
  status: ResultCaseStatus
  input: string
  expected: string
  actual: string
  duration_s: number
  timed_out: boolean
  error: string | null
}

export interface QualityCriterion {
  name: string
  score: number
  comment: string
}

export interface ResultQuality {
  engine: string
  time_complexity: string
  meets_time_constraints: boolean
  overall_score: number
  criteria: QualityCriterion[]
  strengths: string[]
  weaknesses: string[]
  summary: string
}

/**
 * The agent's callback payload (its `result_to_dict`), which the platform stores
 * verbatim in `full_result` — it never reshapes or recomputes it.
 *
 * Every field is optional on purpose: this is a faithful record of whatever the
 * agent sent, and a failed job calls back with an error-shaped payload instead
 * ({ job_id, status, error }). Treat anything here as possibly absent.
 */
export interface AgentFullResult {
  question_id?: string
  question_title?: string
  language?: string
  verdict?: string
  reason?: string
  score_pct?: number
  points_earned?: number
  points_total?: number
  pass_threshold_pct?: number
  compile_error?: string | null
  infra_error?: string | null
  test_cases?: ResultTestCase[]
  quality?: ResultQuality | null
  judge_cost_usd?: number | null
  adversarial?: unknown
  /** Present only on the agent's error callback. */
  error?: string
  status?: string
}

export interface SubmissionResult {
  verdict: string
  score_pct: number
  reason: string
  full_result: AgentFullResult
  received_at: string
}

export interface SubmissionDetail {
  id: string
  question_id: string
  candidate: string
  language: Language
  code: string
  status: string
  agent_job_id: string | null
  created_at: string
  result: SubmissionResult | null
}
