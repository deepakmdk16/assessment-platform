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

// --- Variant sets (per-candidate unique variants) --------------------------

export interface VariantSetDraftIn {
  brief: string
  language: Language
  count: number
  difficulty?: string
  target_complexity?: string
}

export interface VariantDraftOut {
  label: string | null
  question: QuestionIn
  reference_solution: string | null
  reference_language: string | null
  warnings: string[]
}

export interface VariantSetDraftOut {
  variants: VariantDraftOut[]
  warnings: string[]
  engine: string
  cost_usd: number | null
}

/** A reviewed variant to persist: a full question plus its label in the set. */
export interface VariantIn extends QuestionIn {
  label?: string | null
}

export interface VariantSetIn {
  id?: string
  title: string
  brief: string
  language: Language
  difficulty?: string
  target_complexity?: string
  variants: VariantIn[]
}

export interface VariantOut extends QuestionOut {
  variant_label: string | null
}

export interface VariantSetOut {
  id: string
  title: string
  brief: string
  language: string
  difficulty: string | null
  target_complexity: string | null
  status: string
  created_at: string
  updated_at: string
  variants: VariantOut[]
}

export interface VariantSetSummary {
  id: string
  title: string
  language: string
  difficulty: string | null
  variant_count: number
  status: string
  created_at: string
  updated_at: string
}

export interface User {
  id: string
  email: string
  name: string
  // Workspace default branding (A12) — prefills a new assessment's org/logo.
  default_org_name: string | null
  default_logo_url: string | null
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
  /** Set when the invite drew its question from a variant set; question_id is the
   *  assigned variant and variant_label is that variant's tag. */
  variant_set_id: string | null
  variant_label: string | null
  recipients: string[]
  expires_at: string | null
  status: InviteStatus
  deliveries: InviteDelivery[]
}

/** Invite candidates to a variant set: one invite per recipient, round-robin,
 *  with optional per-recipient overrides (email → variant question id). */
export interface VariantSetInviteIn {
  recipients: string[]
  expires_at?: string | null
  overrides?: Record<string, string>
}

/** A slot inside an assessment, with its order and denormalized title. A fixed
 *  slot carries `question_id`; a variant-set slot (VS2) carries `variant_set_id`
 *  + `variant_count` instead — each candidate is handed a different variant. */
export interface AssessmentQuestionRef {
  question_id: string | null
  variant_set_id: string | null
  variant_count: number | null
  position: number
  title: string
}

/** One slot when creating/updating an assessment: EITHER a fixed question OR a
 *  variant set (VS2), exactly one set. */
export interface AssessmentSlotIn {
  question_id?: string
  variant_set_id?: string
}

/** `GET/POST /assessments` — a named, ordered set of questions with a total timer. */
export interface AssessmentOut {
  id: string
  title: string
  duration_minutes: number | null
  // Per-assessment branding (A12): shown on the candidate IDE header.
  org_name: string | null
  logo_url: string | null
  /** Integrity monitoring (I1): fullscreen enforced + outside pastes blocked for
   *  every sitting of this assessment. Defaults on. */
  proctored: boolean
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
  // Ordered slots (VS2): each a fixed question or a variant set. The legacy flat
  // `question_ids` is still accepted server-side but the builder now sends slots.
  slots: AssessmentSlotIn[]
  org_name?: string | null
  logo_url?: string | null
  proctored?: boolean
}

/** One question's result within a candidate's sitting (A3/A11). For a variant-set
 *  slot (VS2), `question_id` is the variant this candidate was assigned and
 *  `variant_label` names it; `title` is the set title so the column stays aligned. */
export interface AssessmentAttemptQuestion {
  question_id: string | null
  variant_set_id: string | null
  variant_label: string | null
  title: string
  submitted: boolean
  // True when this candidate's submission for the slot arrived after the timed
  // window closed — recorded and graded, but flagged.
  late: boolean
  submission_id: string | null
  verdict: string | null
  score_pct: number | null
}

/** `GET /assessments/{id}/attempts` — one candidate's whole sitting: every
 *  question's result plus a composite (A11). avg_score_pct is null until at
 *  least one question is graded. */
export interface AssessmentAttempt {
  candidate_name: string
  candidate_email: string
  questions: AssessmentAttemptQuestion[]
  passed_count: number
  total_count: number
  avg_score_pct: number | null
  /** Integrity signals recorded during this candidate's sitting (I1). null = the
   *  sitting wasn't monitored, which is not the same as zero signals. */
  integrity_signals?: number | null
  /** Of those, pastes actually blocked — the severe kind. */
  integrity_blocked?: number
}

// --- Analytics (AR1) -------------------------------------------------------
// Rates are fractions in [0, 1] (null = undefined, e.g. nothing graded yet);
// scores are 0..100. Times are seconds.

export interface TrendPoint {
  date: string // YYYY-MM-DD
  submissions: number
  graded: number
  passed: number
  pass_rate: number | null
}

/** `GET /analytics/overview` — workspace rollup + daily submission trend. */
export interface OverviewAnalytics {
  questions: number
  submissions: number
  graded: number
  candidates: number
  passed: number
  pass_rate: number | null
  avg_score_pct: number | null
  trend: TrendPoint[]
  score_distribution: ScoreBucket[]
}

/** `GET /analytics/questions` — per-question stats (merged into the library
 *  table by question_id). */
export interface QuestionAnalytics {
  question_id: string
  title: string
  difficulty: string | null
  submissions: number
  graded: number
  passed: number
  pass_rate: number | null
  avg_score_pct: number | null
  median_score_pct: number | null
  late: number
  avg_time_to_solve_s: number | null
  median_time_to_solve_s: number | null
}

export interface ScoreBucket {
  low: number
  high: number
  count: number
}

export interface AssessmentCandidateAnalytics {
  candidate_name: string
  candidate_email: string
  passed_count: number
  submitted_count: number
  total_count: number
  avg_score_pct: number | null
  rank: number | null
  percentile: number | null
  time_to_solve_s: number | null
}

/** `GET /analytics/assessments/{id}` — cross-candidate rollup for one assessment. */
export interface AssessmentAnalytics {
  assessment_id: string
  title: string
  slot_count: number
  candidates_started: number
  candidates_completed: number
  avg_score_pct: number | null
  pass_rate: number | null
  score_distribution: ScoreBucket[]
  candidates: AssessmentCandidateAnalytics[]
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
  /** Whether this sitting is monitored (I1) — known before /start so the gate
   *  screen can disclose it before the candidate identifies themselves. */
  proctored?: boolean
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
  /** Per-assessment branding (A12): set only for an assessment invite whose
   *  Assessment carries them; null for a legacy single-question invite or an
   *  unbranded assessment. */
  assessment_title?: string | null
  org_name?: string | null
  logo_url?: string | null
  /** Whether this sitting is monitored (I1). The candidate UI enforces fullscreen
   *  and blocks outside pastes only when true; a legacy single-question invite is
   *  always monitored. */
  proctored?: boolean
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
  late?: boolean // arrived after the timed window closed (recorded + flagged)
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
  late?: boolean // arrived after the timed window closed (recorded + flagged)
  // Set when this submission came in through an assessment invite (A3).
  assessment_id?: string | null
  assessment_title?: string | null
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
  late: boolean // arrived after the timed window closed (recorded + flagged)
  result: SubmissionResult | null
}

// --- Integrity signals (I1 browser telemetry) ------------------------------ #

export type IntegrityEventKind =
  | 'focus_loss'
  | 'fullscreen_exit'
  | 'fullscreen_denied'
  | 'paste_external'
  | 'paste_internal'
  | 'devtools'

/** One signal as reported by the candidate's browser. */
export interface IntegrityEventIn {
  kind: IntegrityEventKind
  offset_ms: number
  duration_ms?: number | null
  size?: number | null
  blocked?: boolean
}

export interface IntegrityEvent extends IntegrityEventIn {
  question_id: string | null
  /** Which question was open when the signal fired; null for sitting-level ones. */
  question_title: string | null
  blocked: boolean
}

export interface IntegritySummary {
  total: number
  focus_losses: number
  away_ms: number
  fullscreen_exits: number
  pastes_blocked: number
  devtools_opens: number
}

/** A sitting's integrity signals, read from one of its submissions. `monitored`
 *  false means the sitting ran unmonitored — an empty timeline says nothing. */
export interface IntegrityReport {
  monitored: boolean
  summary: IntegritySummary
  events: IntegrityEvent[]
}
