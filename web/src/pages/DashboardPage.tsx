import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import type { QuestionOut } from '../types'

export function DashboardPage() {
  const navigate = useNavigate()
  const [questions, setQuestions] = useState<QuestionOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .listQuestions()
      .then(setQuestions)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load questions'))
  }, [])

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>
            Questions
            {questions && questions.length > 0 && <span className="count">{questions.length}</span>}
          </h1>
          <div className="sub">Author problems, invite candidates, and review graded submissions.</div>
        </div>
        <Link to="/questions/new" className="btn">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New question
        </Link>
      </div>

      {error && <p className="form-error">{error}</p>}
      {!error && questions === null && <p className="page-loading">Loading…</p>}
      {questions?.length === 0 && (
        <p className="empty-state">No questions yet. Create your first one to start inviting candidates.</p>
      )}

      {questions && questions.length > 0 && (
        <div className="card tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Problem</th>
                <th>Test cases</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {questions.map((q) => (
                <tr
                  key={q.id}
                  className="clickable-row"
                  onClick={() => navigate(`/questions/${q.id}`)}
                >
                  <td>
                    <div className="t-title">{q.title}</div>
                  </td>
                  <td className="num">{q.test_cases.length}</td>
                  <td>{new Date(q.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
