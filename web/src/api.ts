import type {
  AssessmentAnalytics,
  AssessmentAttempt,
  AssessmentIn,
  AssessmentOut,
  CandidateDraftsResponse,
  IntegrityEventIn,
  IntegrityReport,
  Invite,
  InviteStartResponse,
  InviteStatusResponse,
  LoginResponse,
  OverviewAnalytics,
  Page,
  QuestionAnalytics,
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
  VariantSetDraftIn,
  VariantSetDraftOut,
  VariantSetIn,
  VariantSetInviteIn,
  VariantSetOut,
  VariantSetSummary,
} from './types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:9000'

// The access token lives only in memory: it is short-lived by design and never
// goes into localStorage, where any script on the page could read it. The
// long-lived credential is the httpOnly refresh cookie the browser holds for
// /auth, which script can't touch — see tryRefresh.
let accessToken: string | null = null

export function getToken(): string | null {
  return accessToken
}

export function setToken(token: string): void {
  accessToken = token
}

export function clearToken(): void {
  accessToken = null
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

let refreshing: Promise<boolean> | null = null

/** Trade the refresh cookie for a new access token. Concurrent callers share one
 *  in-flight request. Resolves false when there is no live session. */
export function tryRefresh(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch(`${BASE_URL}/auth/refresh`, { method: 'POST', credentials: 'include' })
      .then(async (res) => {
        if (!res.ok) return false
        const data = (await res.json()) as LoginResponse
        setToken(data.access_token)
        return true
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
  retried = false,
): Promise<T> {
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
    credentials: 'include',
  })

  if (res.status === 401 && auth) {
    // Access tokens expire in minutes, so a 401 usually just means that: refresh
    // and replay once. Only a failed refresh is a real sign-out.
    if (!retried && (await tryRefresh())) {
      return request<T>(path, options, true)
    }
    unauthorizedHandler?.()
  }

  if (!res.ok) {
    let message = res.statusText
    try {
      const data = await res.json()
      // A schema failure (422) carries pydantic's list of {loc, msg} objects; join
      // the messages so the page shows words, not "[object Object]".
      const detail: unknown = data.detail
      const joined = Array.isArray(detail)
        ? detail
            .map((d: { msg?: string }) => (d.msg ?? '').replace(/^Value error, /, ''))
            .filter(Boolean)
            .join(' ')
        : null
      // An empty join would blank the alert entirely, so keep the fallback.
      message = joined || (typeof detail === 'string' ? detail : null) || data.message || message
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

  updateMe: (data: { default_org_name: string | null; default_logo_url: string | null }) =>
    request<User>('/auth/me', { method: 'PATCH', body: data, auth: true }),

  logout: () => request<void>('/auth/logout', { method: 'POST' }),

  forgotPassword: (email: string) =>
    request<{ detail: string }>('/auth/forgot-password', { method: 'POST', body: { email } }),

  resetPassword: (token: string, new_password: string) =>
    request<void>('/auth/reset-password', { method: 'POST', body: { token, new_password } }),

  changePassword: (current_password: string, new_password: string) =>
    request<LoginResponse>('/auth/change-password', {
      method: 'POST',
      body: { current_password, new_password },
      auth: true,
    }),

  verifyEmail: (token: string) =>
    request<void>('/auth/verify-email', { method: 'POST', body: { token } }),

  resendVerification: () =>
    request<{ detail: string }>('/auth/resend-verification', { method: 'POST', auth: true }),

  deleteAccount: (password: string) =>
    request<void>('/auth/me', { method: 'DELETE', body: { password }, auth: true }),

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

  // --- Variant sets (per-candidate unique variants) ------------------------
  draftVariantSet: (data: VariantSetDraftIn) =>
    request<VariantSetDraftOut>('/variant-sets/draft', { method: 'POST', body: data, auth: true }),

  createVariantSet: (data: VariantSetIn) =>
    request<VariantSetOut>('/variant-sets', { method: 'POST', body: data, auth: true }),

  listVariantSets: (includeArchived = false, offset = 0, limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (includeArchived) params.set('include_archived', 'true')
    return request<Page<VariantSetSummary>>(`/variant-sets?${params}`, { auth: true })
  },

  getVariantSet: (id: string) => request<VariantSetOut>(`/variant-sets/${id}`, { auth: true }),

  createVariantSetInvites: (setId: string, data: VariantSetInviteIn) =>
    request<Invite[]>(`/variant-sets/${setId}/invites`, { method: 'POST', body: data, auth: true }),

  listVariantSetInvites: (setId: string) =>
    request<Invite[]>(`/variant-sets/${setId}/invites`, { auth: true }),

  // --- Assessments (T4) ----------------------------------------------------
  listAssessments: (includeArchived = false, offset = 0, limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (includeArchived) params.set('include_archived', 'true')
    return request<Page<AssessmentOut>>(`/assessments?${params}`, { auth: true })
  },

  createAssessment: (data: AssessmentIn) =>
    request<AssessmentOut>('/assessments', { method: 'POST', body: data, auth: true }),

  getAssessment: (id: string) => request<AssessmentOut>(`/assessments/${id}`, { auth: true }),

  updateAssessment: (id: string, data: Omit<AssessmentIn, 'id'>) =>
    request<AssessmentOut>(`/assessments/${id}`, { method: 'PUT', body: data, auth: true }),

  archiveAssessment: (id: string) =>
    request<AssessmentOut>(`/assessments/${id}/archive`, { method: 'POST', auth: true }),

  unarchiveAssessment: (id: string) =>
    request<AssessmentOut>(`/assessments/${id}/unarchive`, { method: 'POST', auth: true }),

  deleteAssessment: (id: string) =>
    request<void>(`/assessments/${id}`, { method: 'DELETE', auth: true }),

  createAssessmentInvite: (
    assessmentId: string,
    data: { recipients?: string[]; expires_at?: string | null },
  ) =>
    request<Invite>(`/assessments/${assessmentId}/invites`, {
      method: 'POST',
      body: data,
      auth: true,
    }),

  listAssessmentInvites: (assessmentId: string) =>
    request<Invite[]>(`/assessments/${assessmentId}/invites`, { auth: true }),

  listAssessmentAttempts: (assessmentId: string) =>
    request<AssessmentAttempt[]>(`/assessments/${assessmentId}/attempts`, { auth: true }),

  // --- Analytics (AR1) -----------------------------------------------------
  // `days` windows the submission-derived stats; omit for the all-time view.
  analyticsOverview: (days?: number) => {
    const q = days ? `?days=${days}` : ''
    return request<OverviewAnalytics>(`/analytics/overview${q}`, { auth: true })
  },

  analyticsQuestions: (days?: number, offset = 0, limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (days) params.set('days', String(days))
    return request<Page<QuestionAnalytics>>(`/analytics/questions?${params}`, { auth: true })
  },

  analyticsAssessment: (assessmentId: string) =>
    request<AssessmentAnalytics>(`/analytics/assessments/${assessmentId}`, { auth: true }),

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

  /** Flush a batch of integrity signals (I1). Fire-and-forget from the candidate
   *  UI's point of view — it returns 204 and the caller ignores failures. */
  postIntegrityEvents: (
    token: string,
    data: { candidate_email: string; question_id?: string | null; events: IntegrityEventIn[] },
  ) => request<void>(`/invite/${token}/events`, { method: 'POST', body: data }),

  getSubmissionIntegrity: (submissionId: string) =>
    request<IntegrityReport>(`/submissions/${submissionId}/integrity`, { auth: true }),

  /** Re-trigger the agent for a submission whose grading failed. The server
   *  409s unless status is `error`, so the caller can surface that verbatim. */
  retrySubmission: (submissionId: string) =>
    request<SubmissionDetail>(`/submissions/${submissionId}/retry`, {
      method: 'POST',
      auth: true,
    }),

  startInvite: (token: string, candidate_email: string, candidate_name?: string) =>
    request<InviteStartResponse>(`/invite/${token}/start`, {
      method: 'POST',
      body: { candidate_email, candidate_name },
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

  /** Server-side autosave (CX2). Fire-and-forget like the integrity events —
   *  localStorage stays the fast same-browser restore; this survives a cleared
   *  cache or a device switch. */
  saveCandidateDraft: (
    token: string,
    data: { candidate_email: string; question_id?: string | null; code: string; language: string },
  ) => request<void>(`/invite/${token}/draft`, { method: 'PUT', body: data }),

  getCandidateDrafts: (token: string, candidate_email: string) =>
    request<CandidateDraftsResponse>(
      `/invite/${token}/draft?${new URLSearchParams({ candidate_email })}`,
    ),
}

/** A raw authenticated GET for the file downloads below (which bypass `request`
 *  because they return a file, not JSON), with the same refresh-and-replay on an
 *  expired access token. */
async function authedFetch(path: string, retried = false): Promise<Response> {
  const token = getToken()
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    credentials: 'include',
  })
  if (res.status === 401) {
    if (!retried && (await tryRefresh())) return authedFetch(path, true)
    unauthorizedHandler?.()
  }
  return res
}

/** Fetch the owner-scoped submissions CSV (authenticated) and trigger a browser
 *  download. */
export async function exportSubmissionsCsv(): Promise<void> {
  const res = await authedFetch('/submissions/export')
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

/** Fetch a submission's PDF report (authenticated) from the agent proxy and
 *  trigger a browser download. A file, not JSON, so it bypasses `request`. */
export async function downloadSubmissionReport(submissionId: string): Promise<void> {
  const res = await authedFetch(`/submissions/${submissionId}/report`)
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = `report-${submissionId}.pdf`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
