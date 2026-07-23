import type {
  Invite,
  InviteStartResponse,
  InviteStatusResponse,
  LoginResponse,
  Page,
  QuestionDraftIn,
  QuestionDraftOut,
  QuestionIn,
  QuestionOut,
  RunResponse,
  RunTestsResponse,
  SubmissionDetail,
  SubmissionRow,
  SubmissionSummary,
  SubmitResponse,
  User,
} from './types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:9000'
const TOKEN_KEY = 'assessment_platform_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Called by AuthProvider so any 401 from an authenticated call can trigger logout + redirect. */
let unauthorizedHandler: (() => void) | null = null

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

interface RequestOptions {
  method?: string
  body?: unknown
  auth?: boolean
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = false } = options

  const headers: Record<string, string> = {}
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  if (auth) {
    const token = getToken()
    if (token) {
      headers.Authorization = `Bearer ${token}`
    }
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (res.status === 401 && auth) {
    unauthorizedHandler?.()
  }

  if (!res.ok) {
    let message = res.statusText
    try {
      const data = await res.json()
      message = data.detail ?? data.message ?? message
    } catch {
      // response had no JSON body
    }
    throw new ApiError(res.status, message)
  }

  if (res.status === 204) {
    return undefined as T
  }

  return (await res.json()) as T
}

export const api = {
  register: (data: { email: string; password: string; name: string }) =>
    request<{ id: string; email: string; name: string }>('/auth/register', {
      method: 'POST',
      body: data,
    }),

  login: (data: { email: string; password: string }) =>
    request<LoginResponse>('/auth/login', { method: 'POST', body: data }),

  me: () => request<User>('/auth/me', { auth: true }),

  listQuestions: (includeArchived = false, offset = 0, limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (includeArchived) params.set('include_archived', 'true')
    return request<Page<QuestionOut>>(`/questions?${params}`, { auth: true })
  },

  archiveQuestion: (id: string) =>
    request<QuestionOut>(`/questions/${id}/archive`, { method: 'POST', auth: true }),

  unarchiveQuestion: (id: string) =>
    request<QuestionOut>(`/questions/${id}/unarchive`, { method: 'POST', auth: true }),

  createQuestion: (data: QuestionIn) =>
    request<QuestionOut>('/questions', { method: 'POST', body: data, auth: true }),

  draftQuestion: (data: QuestionDraftIn) =>
    request<QuestionDraftOut>('/questions/draft', { method: 'POST', body: data, auth: true }),

  getQuestion: (id: string) => request<QuestionOut>(`/questions/${id}`, { auth: true }),

  updateQuestion: (id: string, data: QuestionIn) =>
    request<QuestionOut>(`/questions/${id}`, { method: 'PUT', body: data, auth: true }),

  deleteQuestion: (id: string) =>
    request<void>(`/questions/${id}`, { method: 'DELETE', auth: true }),

  createInvite: (
    questionId: string,
    data: { recipients?: string[]; expires_at?: string | null },
  ) =>
    request<Invite>(`/questions/${questionId}/invites`, {
      method: 'POST',
      body: data,
      auth: true,
    }),

  listInvites: (questionId: string) =>
    request<Invite[]>(`/questions/${questionId}/invites`, { auth: true }),

  revokeInvite: (questionId: string, token: string) =>
    request<Invite>(`/questions/${questionId}/invites/${token}/revoke`, {
      method: 'POST',
      auth: true,
    }),

  listSubmissions: (questionId: string, offset = 0, limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    return request<Page<SubmissionRow>>(`/questions/${questionId}/submissions?${params}`, {
      auth: true,
    })
  },

  listAllSubmissions: (offset = 0, limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    return request<Page<SubmissionSummary>>(`/submissions?${params}`, { auth: true })
  },

  getSubmission: (submissionId: string) =>
    request<SubmissionDetail>(`/submissions/${submissionId}`, { auth: true }),

  getInvite: (token: string) => request<InviteStatusResponse>(`/invite/${token}`),

  startInvite: (token: string, candidate_email: string) =>
    request<InviteStartResponse>(`/invite/${token}/start`, {
      method: 'POST',
      body: { candidate_email },
    }),

  runCandidate: (
    token: string,
    data: {
      candidate_email: string
      language: string
      code: string
      stdin: string
      question_id?: string
    },
  ) => request<RunResponse>(`/invite/${token}/run`, { method: 'POST', body: data }),

  runCandidateTests: (
    token: string,
    data: { candidate_email: string; language: string; code: string; question_id?: string },
  ) => request<RunTestsResponse>(`/invite/${token}/run-tests`, { method: 'POST', body: data }),

  submitCandidate: (
    token: string,
    data: {
      candidate_name: string
      candidate_email: string
      language: string
      code: string
      question_id?: string
    },
  ) => request<SubmitResponse>(`/invite/${token}/submit`, { method: 'POST', body: data }),
}

/** Fetch the owner-scoped submissions CSV (authenticated) and trigger a browser
 *  download. Kept out of `request` because it returns a file, not JSON. */
export async function exportSubmissionsCsv(): Promise<void> {
  const token = getToken()
  const res = await fetch(`${BASE_URL}/submissions/export`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (res.status === 401) unauthorizedHandler?.()
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = 'submissions.csv'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
