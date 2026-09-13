import { useId, useState, type FormEvent } from 'react'
import { ApiError, api } from '../api'
import { DIFFICULTY_LABELS } from '../badges'
import type { DifficultyVerdict } from '../types'

interface Props {
  token: string
  candidateEmail: string
}

const RATINGS = [1, 2, 3, 4, 5]
// The candidate's wording and the interviewer's are the same wording.
const DIFFICULTIES = Object.entries(DIFFICULTY_LABELS) as [DifficultyVerdict, string][]
const MAX_COMMENT = 2000

/** What the candidate made of the sitting (P2b) — optional, once, and only on a
 *  screen where the sitting is over.
 *
 *  Nothing is pre-selected on the rating: a default would be recorded as an
 *  opinion by anyone who sends without touching it, and a feedback scale that
 *  quietly agrees with itself is worse than no scale. Difficulty starts at the
 *  neutral middle, which claims nothing in either direction.
 *
 *  A 409 (this sitting already answered) ends in the same thank-you as a 201, so
 *  a reload or a double-click never reads as a failure. */
export function CandidateFeedbackForm({ token, candidateEmail }: Props) {
  const group = useId()
  const [rating, setRating] = useState<number | null>(null)
  const [difficulty, setDifficulty] = useState<DifficultyVerdict>('fair')
  const [comment, setComment] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [closed, setClosed] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (rating === null || sending || sent) return
    setSending(true)
    setError(null)
    try {
      await api.sendCandidateFeedback(token, {
        candidate_email: candidateEmail,
        rating,
        difficulty_fair: difficulty,
        comment: comment.trim(),
      })
      setSent(true)
    } catch (err) {
      // 409 = this sitting already answered. Same thank-you as a 201, so a reload
      // or a double-click never reads as a failure.
      if (err instanceof ApiError && err.status === 409) {
        setSent(true)
        return
      }
      // Any other 4xx is a permanent no — the link was revoked or expired while
      // they were typing, or this sitting never took feedback. Retrying cannot
      // fix it, so say so instead of inviting an endless loop. 429 is the
      // exception: too fast, not too late.
      if (err instanceof ApiError && err.status >= 400 && err.status < 500 && err.status !== 429) {
        setClosed(true)
        return
      }
      setError('That didn’t send. Check your connection and try again.')
    } finally {
      setSending(false)
    }
  }

  if (closed) {
    return (
      <div className="feedback">
        <p className="fb-thanks">
          <span className="chip chip-neutral">Closed</span>
          This assessment can’t take feedback any more — the link has expired.
        </p>
      </div>
    )
  }

  if (sent) {
    return (
      <div className="feedback">
        <p className="fb-thanks">
          <span className="chip chip-good">Sent ✓</span>
          Thanks — your feedback is with the hiring team.
        </p>
      </div>
    )
  }

  return (
    <form className="feedback" onSubmit={handleSubmit}>
      <div className="feedback-head">
        <span className="feedback-title">How did that go?</span>
        <p className="feedback-sub">
          Optional, and it doesn’t affect your result. Your interviewer sees it next to your name.
        </p>
      </div>

      <fieldset className="fb-group">
        <legend>Overall</legend>
        <div className="fb-seg">
          {RATINGS.map((n) => (
            <div key={n}>
              <input
                type="radio"
                id={`${group}-rating-${n}`}
                name={`${group}-rating`}
                value={n}
                checked={rating === n}
                onChange={() => setRating(n)}
              />
              <label htmlFor={`${group}-rating-${n}`}>{n}</label>
            </div>
          ))}
        </div>
        <div className="fb-scale">
          <span>1 — poor</span>
          <span>5 — great</span>
        </div>
      </fieldset>

      <fieldset className="fb-group">
        <legend>Difficulty</legend>
        <div className="fb-seg">
          {DIFFICULTIES.map(([value, label]) => (
            <div key={value}>
              <input
                type="radio"
                id={`${group}-difficulty-${value}`}
                name={`${group}-difficulty`}
                value={value}
                checked={difficulty === value}
                onChange={() => setDifficulty(value)}
              />
              <label htmlFor={`${group}-difficulty-${value}`}>{label}</label>
            </div>
          ))}
        </div>
      </fieldset>

      <div className="field">
        <label htmlFor={`${group}-comment`}>Anything you want the team to know?</label>
        <textarea
          id={`${group}-comment`}
          maxLength={MAX_COMMENT}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Optional. The editor, the time limit, the question itself — whatever stood out."
        />
        <span className="fb-count">
          {comment.length} / {MAX_COMMENT}
        </span>
      </div>

      {error && (
        <p role="alert" className="fb-error">
          {error}
        </p>
      )}
      <div className="fb-actions">
        <button type="submit" className="btn" disabled={rating === null || sending}>
          {sending ? 'Sending…' : 'Send feedback'}
        </button>
        <span className="cellsub">
          {rating === null ? 'Pick a rating to send.' : 'Sends once — you can’t edit it afterwards.'}
        </span>
      </div>
    </form>
  )
}
