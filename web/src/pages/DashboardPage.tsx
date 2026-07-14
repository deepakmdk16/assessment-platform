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
        <h1>My questions</h1>
        <Link to="/questions/new" className="button">
          Add question
        </Link>
      </div>

      {error && <p className="form-error">{error}</p>}
      {!error && questions === null && <p>Loading…</p>}
      {questions?.length === 0 && <p>No questions yet. Add your first one.</p>}

      {questions && questions.length > 0 && (
        <ul className="question-list">
          {questions.map((q) => (
            <li key={q.id}>
              <Link to={`/questions/${q.id}`}>
                <strong>{q.title}</strong>
                <span className="question-id">{q.id}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
