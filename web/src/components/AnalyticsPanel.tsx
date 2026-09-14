import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import { Drawer } from './Drawer'
import { DIFFICULTY_LABELS, difficultyVerdictLabel, ratingClass } from '../badges'
import {
  bucketClass,
  formatDuration,
  pct,
  percentileLabel,
  score,
} from '../analytics/format'
import type {
  AssessmentAnalytics,
  AssessmentFeedback,
  AssessmentOut,
  OverviewAnalytics,
  ScoreBucket,
  TrendPoint,
} from '../types'

const RANGES: { label: string; days: number | undefined }[] = [
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: 'All', days: undefined },
]

/** The time range for everything on the dashboard. It lives in the list toolbar
 *  rather than above the numbers (U06), because it filters the question table
 *  as much as it filters these figures. */
export function RangeSeg({
  days,
  onDaysChange,
}: {
  days: number | undefined
  onDaysChange: (d: number | undefined) => void
}) {
  return (
    <div className="range-seg" role="group" aria-label="Time range">
      {RANGES.map((r) => (
        <button
          key={r.label}
          type="button"
          className={r.days === days ? 'on' : undefined}
          onClick={() => onDaysChange(r.days)}
        >
          {r.label}
        </button>
      ))}
    </div>
  )
}

/** Workspace analytics on the dashboard (AR1), as five numbers and nothing else.
 *
 *  Until U06 this panel also rendered the trend, the score distribution, the
 *  cross-candidate table and the feedback rollup inline — four charts stacked
 *  above the list the page is named for, which pushed the question library
 *  roughly 900px down. The numbers stay; each one now opens the chart that
 *  explains it in a drawer, so the page answers one question at a time and the
 *  library is the body of the page again.
 *
 *  `days` is owned by the parent so the same window drives the per-question
 *  columns in the question table; the control itself is `RangeSeg` above. */
export function AnalyticsPanel({ days }: { days: number | undefined }) {
  const [overview, setOverview] = useState<OverviewAnalytics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [assessments, setAssessments] = useState<AssessmentOut[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [xc, setXc] = useState<AssessmentAnalytics | null>(null)
  // Which number the reader opened. One at a time, by construction.
  const [openDetail, setOpenDetail] = useState<DetailKey | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .analyticsOverview(days)
      .then((o) => !cancelled && setOverview(o))
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load analytics')
      })
    return () => {
      cancelled = true
    }
  }, [days])

  useEffect(() => {
    let cancelled = false
    api
      .listAssessments()
      .then((page) => {
        if (cancelled) return
        setAssessments(page.items)
        if (page.items.length > 0) setSelectedId((prev) => prev || page.items[0].id)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!selectedId) return
    let cancelled = false
    api
      .analyticsAssessment(selectedId)
      .then((a) => !cancelled && setXc(a))
      .catch(() => !cancelled && setXc(null))
    return () => {
      cancelled = true
    }
  }, [selectedId])

  if (error) return <p className="form-error">{error}</p>
  // Reserve the space rather than returning null: the dashboard used to render
  // without this panel and then shove the whole question list down when the
  // numbers arrived. The skeleton reuses the real containers, so the height it
  // holds is the height the loaded panel takes.
  if (!overview) {
    return (
      <section className="analytics" aria-busy="true">
        <div className="stat-grid">
          {/* Five, matching the five <Tile>s below — a skeleton that reserves the
              wrong shape defeats the point. */}
          {[0, 1, 2, 3, 4].map((i) => (
            <div className="stat" key={i}>
              <div className="stat-label skeleton-line" aria-hidden="true" />
              <div className="stat-value skeleton-line" aria-hidden="true" />
            </div>
          ))}
        </div>
      </section>
    )
  }

  const assessmentPicker =
    assessments.length > 0 ? (
      <label className="picker-label">
        Assessment{' '}
        <select className="field" value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
          {assessments.map((a) => (
            <option key={a.id} value={a.id}>
              {a.title}
            </option>
          ))}
        </select>
      </label>
    ) : null

  return (
    <section className="analytics">
      <div className="stat-grid">
        {/* "Questions" opens nothing: the library it counts is the next thing on
            the page, so a drawer over it would be a door to the room you are in. */}
        <Tile label="Questions" value={String(overview.questions)} sub="active in library" />
        <Tile
          label="Submissions"
          value={String(overview.submissions)}
          sub={`${overview.graded} graded`}
          opens="over time"
          onOpen={() => setOpenDetail('trend')}
        />
        <Tile
          label="Candidates"
          value={String(overview.candidates)}
          sub="distinct emails"
          opens="compare"
          onOpen={() => setOpenDetail('candidates')}
        />
        {/* Pass rate and average score are two summaries of one distribution, so
            they open the same drawer rather than pretending to be two subjects. */}
        <Tile
          label="Pass rate"
          value={pct(overview.pass_rate)}
          sub={`${overview.passed} of ${overview.graded} graded`}
          accent
          opens="distribution"
          onOpen={() => setOpenDetail('scores')}
        />
        <Tile
          label="Avg score"
          value={score(overview.avg_score_pct)}
          sub="across graded"
          opens="distribution"
          onOpen={() => setOpenDetail('scores')}
        />
      </div>

      <Drawer
        open={openDetail === 'trend'}
        title="Submissions over time"
        hint="passed vs total"
        onClose={() => setOpenDetail(null)}
      >
        <div className="chart">
          <TrendChart trend={overview.trend} />
        </div>
      </Drawer>

      <Drawer
        open={openDetail === 'scores'}
        title="Score distribution"
        hint="graded submissions"
        onClose={() => setOpenDetail(null)}
      >
        <div className="chart">
          <Histogram buckets={overview.score_distribution} />
        </div>
      </Drawer>

      <Drawer
        open={openDetail === 'candidates'}
        title="Cross-candidate"
        hint="by assessment"
        onClose={() => setOpenDetail(null)}
      >
        {assessments.length === 0 ? (
          <p className="empty-state">
            Create an assessment and invite candidates to compare them here.
          </p>
        ) : (
          <>
            <div className="card-head">{assessmentPicker}</div>
            {xc && xc.candidates.length > 0 ? (
              <CrossCandidate data={xc} />
            ) : (
              <p className="empty-state">No candidates have started this assessment yet.</p>
            )}
            {xc && (
              <>
                <div className="card-head">
                  <span className="card-title">Candidate feedback</span>
                  <span className="hint">
                    {xc.feedback && xc.feedback.responses > 0
                      ? `${xc.feedback.responses} of ${xc.feedback.finished} sittings answered`
                      : 'optional, asked once a sitting is over'}
                  </span>
                </div>
                <FeedbackRollup feedback={xc.feedback} />
              </>
            )}
          </>
        )}
      </Drawer>
    </section>
  )
}

/** The numbers that open something, and what they open. */
type DetailKey = 'trend' | 'scores' | 'candidates'

/** What candidates made of one assessment (P2b). An erasure deletes the feedback
 *  with the rest of the sitting, so an erased candidate leaves no row here and
 *  the aggregates move with them. */
function FeedbackRollup({ feedback }: { feedback?: AssessmentFeedback }) {
  const fb = feedback
  if (!fb || fb.responses === 0) {
    return (
      <p className="empty-state">
        No feedback yet — candidates are asked once they finish, and answering is optional.
      </p>
    )
  }
  const rated = fb.too_easy + fb.fair + fb.too_hard
  // Percent of the 100-unit viewBox above.
  const share = (n: number) => (rated ? (n / rated) * 100 : 0)
  return (
    <>
      <div className="stat-grid stat-grid-3">
        <Tile
          label="Avg rating"
          value={fb.avg_rating == null ? '—' : `${fb.avg_rating.toFixed(1)}/5`}
          sub={`${fb.responses} response${fb.responses === 1 ? '' : 's'}`}
          accent
        />
        <Tile
          label="Response rate"
          value={pct(fb.finished ? fb.responses / fb.finished : null)}
          sub="of candidates who finished"
        />
        <Tile
          label="Called it too hard"
          value={pct(rated ? fb.too_hard / rated : null)}
          sub={`${fb.too_hard} of ${rated}`}
        />
      </div>

      {/* SVG rather than three sized <span>s: widths are data, and a width is a
          style — the same reason the charts above are drawn, not laid out. */}
      <svg
        className="fb-split"
        viewBox="0 0 100 6"
        preserveAspectRatio="none"
        role="img"
        aria-label={`Difficulty: ${fb.too_easy} too easy, ${fb.fair} about right, ${fb.too_hard} too hard`}
      >
        <rect className="too-easy" x={0} y={0} width={share(fb.too_easy)} height={6} />
        <rect className="fair" x={share(fb.too_easy)} y={0} width={share(fb.fair)} height={6} />
        <rect
          className="too-hard"
          x={share(fb.too_easy) + share(fb.fair)}
          y={0}
          width={share(fb.too_hard)}
          height={6}
        />
      </svg>
      {/* The chart legend this panel already uses, with three more dot colours. */}
      <div className="legend">
        <span>
          <i className="dot dot-too-easy" />
          {DIFFICULTY_LABELS.too_easy} · {fb.too_easy}
        </span>
        <span>
          <i className="dot dot-fair" />
          {DIFFICULTY_LABELS.fair} · {fb.fair}
        </span>
        <span>
          <i className="dot dot-too-hard" />
          {DIFFICULTY_LABELS.too_hard} · {fb.too_hard}
        </span>
      </div>

      {fb.comments.length > 0 && (
        <div className="fb-list">
          {fb.comments.map((c, i) => (
            <div className="fb-item" key={`${c.candidate_name}-${i}`}>
              <div className="fb-item-head">
                <span className="fb-item-who">{c.candidate_name}</span>
                <span className={ratingClass(c.rating)}>{c.rating}/5</span>
                <span className="chip chip-neutral">{difficultyVerdictLabel(c.difficulty_fair)}</span>
                {c.created_at && (
                  <span className="fb-item-when">{new Date(c.created_at).toLocaleDateString()}</span>
                )}
              </div>
              <p>{c.comment}</p>
            </div>
          ))}
        </div>
      )}
    </>
  )
}

function Tile({
  label,
  value,
  sub,
  accent,
  opens,
  onOpen,
}: {
  label: string
  value: string
  sub: string
  accent?: boolean
  /** What the drawer behind this number holds, e.g. "distribution". Shown in
   *  place of `sub` so the tile says it is a door without a second line. */
  opens?: string
  onOpen?: () => void
}) {
  const inner = (
    <>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-sub">{opens ?? sub}</div>
    </>
  )
  if (!onOpen) return <div className={accent ? 'stat stat-accent' : 'stat'}>{inner}</div>
  return (
    <button
      type="button"
      className={`stat stat-open${accent ? ' stat-accent' : ''}`}
      onClick={onOpen}
      // The number and its qualifier are both in the tile, but the button's own
      // name has to say what pressing it does.
      aria-label={`${label}: ${value}, ${sub}. Show ${opens}.`}
    >
      {inner}
    </button>
  )
}

function TrendChart({ trend }: { trend: TrendPoint[] }) {
  const points = trend.slice(-30) // keep the strip readable on wide ranges
  if (points.length === 0) return <p className="empty-state">No submissions in this range.</p>

  const W = 720
  const H = 160
  const top = 6
  const bottom = 24
  const chartH = H - top - bottom
  const max = Math.max(1, ...points.map((p) => p.submissions))
  const step = W / points.length
  const barW = Math.min(step * 0.55, 22)
  const labelEvery = Math.ceil(points.length / 10)

  return (
    <>
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Submissions over time">
        {points.map((p, i) => {
          const cx = i * step + step / 2
          const totalH = (p.submissions / max) * chartH
          const passH = p.submissions ? (p.passed / p.submissions) * totalH : 0
          return (
            <g key={p.date}>
              <rect className="bar-total" x={cx - barW / 2} y={top + chartH - totalH} width={barW} height={totalH} rx={3} />
              <rect className="bar-pass" x={cx - barW / 2} y={top + chartH - passH} width={barW} height={passH} rx={3} />
              {i % labelEvery === 0 && (
                <text className="bar-x" x={cx} y={H - 8} textAnchor="middle">
                  {p.date.slice(8, 10)}
                </text>
              )}
            </g>
          )
        })}
      </svg>
      <div className="legend">
        <span>
          <i className="dot dot-sub" />
          Submitted
        </span>
        <span>
          <i className="dot dot-pass" />
          Passed
        </span>
      </div>
    </>
  )
}

function Histogram({ buckets }: { buckets: ScoreBucket[] }) {
  const W = 300
  const H = 160
  const top = 18
  const bottom = 26
  const chartH = H - top - bottom
  const max = Math.max(1, ...buckets.map((b) => b.count))
  const step = W / buckets.length
  const barW = Math.min(step * 0.62, 46)

  return (
    <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Score distribution">
      {buckets.map((b, i) => {
        const cx = i * step + step / 2
        const h = (b.count / max) * chartH
        return (
          <g key={b.low}>
            <rect
              className={`hist-bar ${bucketClass(b.low)}`}
              x={cx - barW / 2}
              y={top + chartH - h}
              width={barW}
              height={h}
              rx={3}
            />
            <text className="hist-count" x={cx} y={top + chartH - h - 4}>
              {b.count}
            </text>
            <text className="hist-x" x={cx} y={H - 8}>
              {b.low}–{b.high}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function statusChip(c: AssessmentAnalytics['candidates'][number]): { cls: string; text: string } {
  if (c.submitted_count >= c.total_count) return { cls: 'chip chip-good', text: 'Complete' }
  if (c.submitted_count === 0) return { cls: 'chip chip-neutral', text: 'Not started' }
  return { cls: 'chip chip-warn', text: `${c.submitted_count} / ${c.total_count} submitted` }
}

function CrossCandidate({ data }: { data: AssessmentAnalytics }) {
  return (
    <div className="xc-split">
      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Rank</th>
              <th>Candidate</th>
              <th className="th-num">Score</th>
              <th className="th-num">Percentile</th>
              <th className="th-num">Passed</th>
              <th className="th-num">Time</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.candidates.map((c) => {
              const chip = statusChip(c)
              return (
                <tr key={c.candidate_email}>
                  <td className={c.rank === 1 ? 'rank rank-1' : 'rank'}>{c.rank ?? '—'}</td>
                  <td className="t-title">
                    {c.erased ? 'Erased candidate' : c.candidate_name}
                  </td>
                  <td className="num">{score(c.avg_score_pct, 0)}</td>
                  <td className="num">{percentileLabel(c.percentile)}</td>
                  <td className="num">
                    {c.passed_count} / {c.total_count}
                  </td>
                  <td className="num mono">{formatDuration(c.time_to_solve_s)}</td>
                  <td>
                    <span className={chip.cls}>{chip.text}</span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="xc-aside">
        <div>
          <div className="card-title">Score spread</div>
          <Histogram buckets={data.score_distribution} />
        </div>
        <div className="xc-stats">
          <div>
            <span className="muted">Avg score</span>
            <b>{score(data.avg_score_pct)}</b>
          </div>
          <div>
            <span className="muted">Completion</span>
            <b>
              {data.candidates_completed} of {data.candidates_started}
            </b>
          </div>
          <div>
            <span className="muted">Pass rate</span>
            <b>{pct(data.pass_rate)}</b>
          </div>
        </div>
      </div>
    </div>
  )
}
