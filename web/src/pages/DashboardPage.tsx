import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api'
import type { QuestionOut } from '../types'

export function DashboardPage() {
  const [questions, setQuestions] = useState<QuestionOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .listQuestions()
      .then(setQuestions)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load questions'))
  }, [])

  return (
    <div className="page">
      <div className="page-header">
        <h1>
          My questions
          {questions && questions.length > 0 && (
            <span className="count-badge">{questions.length}</span>
          )}
        </h1>
        <Link to="/questions/new" className="button">
          Add question
        </Link>
      </div>

      {error && <p className="form-error">{error}</p>}
      {!error && questions === null && <p>Loading…</p>}
      {questions?.length === 0 && (
        <p className="empty-state">No questions yet. Add your first one to start inviting candidates.</p>
      )}

      {questions && questions.length > 0 && (
        <ul className="question-list">
          {questions.map((q) => (
            <li key={q.id}>
              <Link to={`/questions/${q.id}`}>
                <span className="question-row-top">
                  <strong>{q.title}</strong>
                  <span className="question-id">{q.id}</span>
                </span>
                <span className="question-meta">
                  {q.test_cases.length} test case{q.test_cases.length === 1 ? '' : 's'} · created{' '}
                  {new Date(q.created_at).toLocaleDateString()}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
