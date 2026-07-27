import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import {
  bucketClass,
  formatDuration,
  pct,
  percentileLabel,
  score,
} from '../analytics/format'
import type {
  AssessmentAnalytics,
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

/** Workspace analytics folded onto the dashboard (AR1): the time-range control,
 *  KPI tiles, submission trend, score distribution, and the cross-candidate
 *  view for a chosen assessment. `days` is lifted to the parent so the same
 *  window also drives the per-question columns in the question table. */
export function AnalyticsPanel({
  days,
  onDaysChange,
}: {
  days: number | undefined
  onDaysChange: (d: number | undefined) => void
}) {
  const [overview, setOverview] = useState<OverviewAnalytics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [assessments, setAssessments] = useState<AssessmentOut[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [xc, setXc] = useState<AssessmentAnalytics | null>(null)

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
  if (!overview) return null // the question list below still renders while this loads

  return (
    <section className="analytics">
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

      <div className="stat-grid">
        <Tile label="Questions" value={String(overview.questions)} sub="active in library" />
        <Tile
          label="Submissions"
          value={String(overview.submissions)}
          sub={`${overview.graded} graded`}
        />
        <Tile label="Candidates" value={String(overview.candidates)} sub="distinct emails" />
        <Tile
          label="Pass rate"
          value={pct(overview.pass_rate)}
          sub={`${overview.passed} of ${overview.graded} graded`}
          accent
        />
        <Tile label="Avg score" value={score(overview.avg_score_pct)} sub="across graded" />
      </div>

      <div className="analytics-row">
        <div className="card">
          <div className="card-head">
            <span className="card-title">Submissions over time</span>
            <span className="hint">passed vs total</span>
          </div>
          <div className="chart">
            <TrendChart trend={overview.trend} />
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <span className="card-title">Score distribution</span>
            <span className="hint">graded submissions</span>
          </div>
          <div className="chart">
            <Histogram buckets={overview.score_distribution} />
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <span className="card-title">Cross-candidate — by assessment</span>
          {assessments.length > 0 && (
            <label className="picker-label">
              Assessment{' '}
              <select
                className="field"
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value)}
              >
                {assessments.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.title}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        {assessments.length === 0 ? (
          <p className="empty-state">
            Create an assessment and invite candidates to compare them here.
          </p>
        ) : xc && xc.candidates.length > 0 ? (
          <CrossCandidate data={xc} />
        ) : (
          <p className="empty-state">No candidates have started this assessment yet.</p>
        )}
      </div>
    </section>
  )
}

function Tile({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string
  sub: string
  accent?: boolean
}) {
  return (
    <div className={accent ? 'stat stat-accent' : 'stat'}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-sub">{sub}</div>
    </div>
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
                  <td className="t-title">{c.candidate_name}</td>
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
