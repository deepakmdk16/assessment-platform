export type Language =
  | 'python'
  | 'javascript'
  | 'java'
  | 'cpp'
  | 'c'
  | 'go'
  | 'ruby'
  | 'rust'

export type TestCaseCategory = 'correctness' | 'performance'

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
  id: string
  title: string
  prompt: string
  constraints: string
  time_limit_s: number
  pass_threshold: number
  required_complexity: string
  example_input: string
  example_output: string
  test_cases: TestCaseIn[]
}

export interface QuestionOut extends Omit<QuestionIn, 'test_cases'> {
  test_cases: TestCaseOut[]
  created_at: string
  updated_at: string
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

export interface Invite {
  token: string
  url: string
  question_id: string
  recipients: string[]
  expires_at: string | null
  status: InviteStatus
}

export interface InviteQuestionPublic {
  title: string
  prompt: string
  constraints: string
  example_input: string
  example_output: string
  time_limit_s: number
}

export interface InviteGetResponse {
  question: InviteQuestionPublic
  languages: Language[]
}

export interface SubmitResponse {
  submission_id: string
  status: string
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
