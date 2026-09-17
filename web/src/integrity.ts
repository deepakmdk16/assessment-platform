/** Candidate-side integrity capture (I1 stage 1).
 *
 * Records what the browser can honestly observe during a sitting — focus loss,
 * fullscreen exits, pastes, devtools — and enforces the two rules the product
 * chose to enforce: the sitting runs in fullscreen, and text that did not come
 * from this page cannot be pasted into the editor.
 *
 * **This is a deterrent, not a proof.** Everything here runs in the candidate's
 * own browser, so a candidate who disables JavaScript simply produces no
 * signals: an empty timeline is not evidence of a clean sitting. In particular
 * the paste rule can only ask "was this text copied inside this page?" — the
 * clipboard carries no origin — so retyping or transcribing defeats it by
 * design. Signals are corroboration for a human reading a submission and never
 * touch the grade.
 *
 * Failures are swallowed throughout: monitoring must never be the reason a
 * candidate can't sit their assessment.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { IntegrityEventIn, IntegrityEventKind } from './types'

/** How often the queue is flushed to the server. Long enough that a normal
 *  sitting costs a handful of requests, short enough that a candidate who closes
 *  the tab mid-sitting loses at most this much (`pagehide` flushes too). */
const FLUSH_INTERVAL_MS = 10_000

/** Max events per request — matches the server's batch ceiling. */
const MAX_BATCH = 50

/** Below this, a hidden tab is a notification stealing focus or a screenshot,
 *  not a visit somewhere else. Recorded either way; only announced above it. */
const AWAY_NOTICE_MS = 1500

/** Clipboard text is remembered per sitting to tell an in-page copy from an
 *  outside one. Bounded so a candidate who copies constantly can't grow it
 *  without limit; the oldest entries fall off first. */
const COPY_MEMORY = 40

/** How much the window/viewport gap must GROW, against the narrowest it has been
 *  this sitting, to be taken as docked devtools opening. Deliberately generous:
 *  a wrong "devtools" flag on an interviewer's screen is worse than a missed one.
 *
 *  Growth rather than absolute size (R2-040): Edge's vertical tabs and Firefox's
 *  sidebar hold a gap of this order open for the whole sitting, and scoring the
 *  size flagged every candidate who uses one. What devtools actually does is
 *  make the gap grow while the sitting is running. The honest limits of that —
 *  devtools already open before the sitting began, or undocked into its own
 *  window — are why the consent screen says "when the browser makes it visible"
 *  rather than claiming every use is seen. */
const DEVTOOLS_GROWTH_PX = 200

/** The larger of the two window/viewport gaps, which is where docked devtools
 *  shows up whichever edge it is docked to. */
function currentGap(): number {
  return Math.max(
    window.outerWidth - window.innerWidth,
    window.outerHeight - window.innerHeight,
  )
}

/** Clipboard text as compared against what was copied in-page. Whitespace is
 *  normalized so re-indentation by the editor doesn't turn an in-page copy into
 *  a false "pasted from outside". */
export function normalizeClipboard(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

/** True when the browser can put us in fullscreen at all. iOS Safari cannot do
 *  this for a non-video element, so an iPhone candidate is recorded, not locked
 *  out. */
export function fullscreenSupported(): boolean {
  return typeof document !== 'undefined' && Boolean(document.documentElement.requestFullscreen)
}

export interface IntegrityOptions {
  token: string
  candidateEmail: string
  /** The question open right now; sent with each batch for the timeline. */
  questionId?: string | null
  /** False for an unmonitored sitting (assessment.proctored = false) — nothing is
   *  recorded, nothing is enforced, and the candidate sees no notice. */
  enabled: boolean
  /** When the sitting began, translated into this browser's own clock from the
   *  `started_at`/`server_now` pair /start returns (R2-036). Every offset is
   *  measured from here, so a reload three-quarters of the way through a sitting
   *  keeps placing events three-quarters of the way along the interviewer's
   *  timeline instead of restarting at zero. Null until /start has answered, and
   *  for a sitting the server reports no attempt for; the first event then falls
   *  back to this page load, which is the best the browser can say on its own. */
  startedAtMs?: number | null
}

export interface IntegrityState {
  /** True while the candidate is out of fullscreen and must return to continue. */
  mustReturnToFullscreen: boolean
  /** How many times they've left fullscreen this sitting (shown in the prompt). */
  fullscreenExits: number
  /** Set when a paste was just rejected; cleared by `dismissPasteBlock`. */
  pasteBlocked: { size: number } | null
  dismissPasteBlock: () => void
  /** Set when the candidate comes back from another tab, so the return can be
   *  acknowledged instead of only logged (U05); cleared by `dismissAwayNotice`. */
  awayNotice: { durationMs: number } | null
  dismissAwayNotice: () => void
  /** Ask the browser for fullscreen. Called from the start button and from the
   *  "return to fullscreen" prompt — both are user gestures, which is the only
   *  context where a browser will grant it. */
  enterFullscreen: () => Promise<void>
  /** Push any queued signals now (used at submit, so the last ones aren't lost). */
  flush: () => void
}

export function useIntegrity({
  token,
  candidateEmail,
  questionId,
  enabled,
  startedAtMs,
}: IntegrityOptions): IntegrityState {
  const queue = useRef<IntegrityEventIn[]>([])
  // Stamped when monitoring starts, not at render — offsets are measured from
  // the moment the sitting actually began.
  const startedAt = useRef<number | null>(null)
  const copied = useRef<string[]>([])
  const awaySince = useRef<number | null>(null)
  const fullscreenLeftAt = useRef<number | null>(null)
  const devtoolsReported = useRef(false)
  // The narrowest window/viewport gap seen this sitting, kept separately for
  // windowed and fullscreen, which is the baseline the devtools heuristic
  // measures growth against (R2-040).
  const narrowestGap = useRef<{ windowed: number | null; fullscreen: number | null }>({
    windowed: null,
    fullscreen: null,
  })
  // The latest question id, read by listeners that were registered once.
  const currentQuestion = useRef<string | null | undefined>(questionId)
  useEffect(() => {
    currentQuestion.current = questionId
  }, [questionId])

  // The server's answer wins over whatever this page load assumed: it is the
  // same value across every reload of the same sitting, which is the whole point
  // (R2-036).
  useEffect(() => {
    if (startedAtMs != null) startedAt.current = startedAtMs
  }, [startedAtMs])

  const [mustReturnToFullscreen, setMustReturn] = useState(false)
  const [fullscreenExits, setFullscreenExits] = useState(0)
  const [pasteBlocked, setPasteBlocked] = useState<{ size: number } | null>(null)
  const [awayNotice, setAwayNotice] = useState<{ durationMs: number } | null>(null)

  // Put an event on the queue. `record` wraps this with the "is monitoring on?"
  // test; `enterFullscreen` deliberately does not — see the comment there.
  const enqueue = useCallback((kind: IntegrityEventKind, extra: Partial<IntegrityEventIn> = {}) => {
    if (queue.current.length >= MAX_BATCH) return // drop rather than grow unbounded
    queue.current.push({
      kind,
      offset_ms: Math.max(0, Date.now() - (startedAt.current ?? Date.now())),
      ...extra,
    })
  }, [])

  const record = useCallback(
    (kind: IntegrityEventKind, extra: Partial<IntegrityEventIn> = {}) => {
      if (!enabled) return
      enqueue(kind, extra)
    },
    [enabled, enqueue],
  )

  const flush = useCallback(() => {
    if (!enabled || queue.current.length === 0) return
    const batch = queue.current
    queue.current = []
    // Fire-and-forget: a dropped batch costs a signal, never the sitting. The
    // events are gone either way, so there is nothing useful to retry into.
    api
      .postIntegrityEvents(token, {
        candidate_email: candidateEmail,
        question_id: currentQuestion.current ?? null,
        events: batch,
      })
      .catch(() => {})
  }, [enabled, token, candidateEmail])

  const enterFullscreen = useCallback(async () => {
    // Deliberately NOT gated on `enabled`, and neither is the denial below
    // (R2-003). The only gesture a browser grants fullscreen from is the click
    // that starts the sitting, and that handler runs BEFORE the render where
    // `enabled` flips true — so the hook object it holds is the one from the
    // render where monitoring was still off. Testing `enabled` here meant the
    // call never happened: a live proctored sitting recorded `requestFullscreen`
    // call count 0 while the interviewer's panel read "Stayed in fullscreen".
    // The caller decides whether this sitting is monitored; for an unmonitored
    // one it is simply never called, and anything queued below is never sent
    // because `flush` and its effect are still gated on `enabled`.
    if (!fullscreenSupported()) return
    startedAt.current ??= Date.now()
    try {
      await document.documentElement.requestFullscreen()
      setMustReturn(false)
    } catch {
      // Denied (permissions policy, an unsupported browser, a user refusal).
      // Record it as context and let the sitting continue unlocked — a candidate
      // whose browser won't go fullscreen must not be stuck on a modal.
      enqueue('fullscreen_denied')
      setMustReturn(false)
    }
  }, [enqueue])

  // Focus loss: the tab/window went to the background. `visibilitychange` is the
  // reliable half (a real tab switch); `blur` alone fires for things as innocent
  // as focusing the URL bar, so only the visibility signal is recorded.
  useEffect(() => {
    if (!enabled) return
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        awaySince.current = Date.now()
        return
      }
      if (awaySince.current !== null) {
        const away = Date.now() - awaySince.current
        awaySince.current = null
        record('focus_loss', { duration_ms: away })
        // A tab switch is the one thing a browser gives a page NO way to block
        // — there is no API for it, and `beforeunload` only fires on a real
        // unload. So the honest response is to say it was seen (U05): the
        // candidate agreed to exactly this on the start screen, and a signal
        // sent only to the interviewer deters nobody. Brief flickers (a
        // screenshot, a notification stealing focus) are recorded but not
        // announced — nagging about those would train them to ignore it.
        if (away >= AWAY_NOTICE_MS) setAwayNotice({ durationMs: away })
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [enabled, record])

  // Fullscreen enforcement: leaving blocks the editor until they return, and the
  // exit is recorded with how long it lasted.
  useEffect(() => {
    if (!enabled || !fullscreenSupported()) return
    const onChange = () => {
      if (document.fullscreenElement) {
        if (fullscreenLeftAt.current !== null) {
          record('fullscreen_exit', { duration_ms: Date.now() - fullscreenLeftAt.current })
          fullscreenLeftAt.current = null
        }
        setMustReturn(false)
        return
      }
      fullscreenLeftAt.current = Date.now()
      setFullscreenExits((n) => n + 1)
      setMustReturn(true)
    }
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [enabled, record])

  // Paste rule. `copy`/`cut` remember what left this page; a paste whose text
  // isn't in that memory came from somewhere else and is rejected. Capture phase
  // so the editor never sees a blocked paste.
  useEffect(() => {
    if (!enabled) return
    const remember = (e: ClipboardEvent) => {
      const text = e.clipboardData?.getData('text') ?? document.getSelection()?.toString() ?? ''
      const key = normalizeClipboard(text)
      if (!key) return
      copied.current = [...copied.current.filter((k) => k !== key), key].slice(-COPY_MEMORY)
    }
    const onPaste = (e: ClipboardEvent) => {
      const text = e.clipboardData?.getData('text') ?? ''
      const key = normalizeClipboard(text)
      if (!key) return
      if (copied.current.includes(key)) {
        record('paste_internal', { size: text.length })
        return
      }
      e.preventDefault()
      e.stopPropagation()
      record('paste_external', { size: text.length, blocked: true })
      setPasteBlocked({ size: text.length })
    }
    document.addEventListener('copy', remember, true)
    document.addEventListener('cut', remember, true)
    document.addEventListener('paste', onPaste, true)
    return () => {
      document.removeEventListener('copy', remember, true)
      document.removeEventListener('cut', remember, true)
      document.removeEventListener('paste', onPaste, true)
    }
  }, [enabled, record])

  // Devtools, by the one signal that doesn't need a debugger trick: the gap
  // between the window and the viewport, which docked devtools opens. Reported
  // at most once — it's a hint that the sitting is worth a look, not a count.
  useEffect(() => {
    if (!enabled) return
    // The narrowest gap seen so far is this browser's own chrome; anything above
    // it appeared during the sitting. Tracking the minimum rather than the first
    // sample matters because a candidate who closes a sidebar and then opens
    // devtools would otherwise net out to no change at all.
    //
    // One baseline per fullscreen state, because entering fullscreen removes the
    // browser's chrome and collapses the gap to nothing. Sharing a baseline
    // across that boundary made the fullscreen gap the sitting's minimum, so
    // every LATER exit from fullscreen — the one thing this sitting expects
    // candidates to do — scored as a 200px+ growth and was recorded as devtools.
    const check = () => {
      const state = document.fullscreenElement ? 'fullscreen' : 'windowed'
      const gap = currentGap()
      const seen = narrowestGap.current[state]
      if (seen === null || gap < seen) narrowestGap.current[state] = gap
      if (devtoolsReported.current) return
      const baseline = narrowestGap.current[state]
      if (baseline !== null && gap - baseline > DEVTOOLS_GROWTH_PX) {
        devtoolsReported.current = true
        record('devtools')
      }
    }
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [enabled, record])

  // Periodic flush, plus a last one as the page goes away.
  useEffect(() => {
    if (!enabled) return
    startedAt.current ??= Date.now()
    const timer = setInterval(flush, FLUSH_INTERVAL_MS)
    window.addEventListener('pagehide', flush)
    return () => {
      clearInterval(timer)
      window.removeEventListener('pagehide', flush)
      flush()
    }
  }, [enabled, flush])

  const dismissPasteBlock = useCallback(() => setPasteBlocked(null), [])
  const dismissAwayNotice = useCallback(() => setAwayNotice(null), [])

  return {
    mustReturnToFullscreen: enabled && mustReturnToFullscreen,
    fullscreenExits,
    pasteBlocked,
    dismissPasteBlock,
    awayNotice: enabled ? awayNotice : null,
    dismissAwayNotice,
    enterFullscreen,
    flush,
  }
}
