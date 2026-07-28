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

/** Clipboard text is remembered per sitting to tell an in-page copy from an
 *  outside one. Bounded so a candidate who copies constantly can't grow it
 *  without limit; the oldest entries fall off first. */
const COPY_MEMORY = 40

/** A window/viewport gap this large is taken as docked devtools. Deliberately
 *  generous: a wrong "devtools" flag on an interviewer's screen is worse than a
 *  missed one, and a normal sitting has no such gap in fullscreen. */
const DEVTOOLS_GAP_PX = 200

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
}

export interface IntegrityState {
  /** True while the candidate is out of fullscreen and must return to continue. */
  mustReturnToFullscreen: boolean
  /** How many times they've left fullscreen this sitting (shown in the prompt). */
  fullscreenExits: number
  /** Set when a paste was just rejected; cleared by `dismissPasteBlock`. */
  pasteBlocked: { size: number } | null
  dismissPasteBlock: () => void
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
}: IntegrityOptions): IntegrityState {
  const queue = useRef<IntegrityEventIn[]>([])
  // Stamped when monitoring starts, not at render — offsets are measured from
  // the moment the sitting actually began.
  const startedAt = useRef<number | null>(null)
  const copied = useRef<string[]>([])
  const awaySince = useRef<number | null>(null)
  const fullscreenLeftAt = useRef<number | null>(null)
  const devtoolsReported = useRef(false)
  // The latest question id, read by listeners that were registered once.
  const currentQuestion = useRef<string | null | undefined>(questionId)
  useEffect(() => {
    currentQuestion.current = questionId
  }, [questionId])

  const [mustReturnToFullscreen, setMustReturn] = useState(false)
  const [fullscreenExits, setFullscreenExits] = useState(0)
  const [pasteBlocked, setPasteBlocked] = useState<{ size: number } | null>(null)

  const record = useCallback(
    (kind: IntegrityEventKind, extra: Partial<IntegrityEventIn> = {}) => {
      if (!enabled) return
      if (queue.current.length >= MAX_BATCH) return // drop rather than grow unbounded
      queue.current.push({
        kind,
        offset_ms: Math.max(0, Date.now() - (startedAt.current ?? Date.now())),
        ...extra,
      })
    },
    [enabled],
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
    if (!enabled || !fullscreenSupported()) return
    try {
      await document.documentElement.requestFullscreen()
      setMustReturn(false)
    } catch {
      // Denied (permissions policy, an unsupported browser, a user refusal).
      // Record it as context and let the sitting continue unlocked — a candidate
      // whose browser won't go fullscreen must not be stuck on a modal.
      record('fullscreen_denied')
      setMustReturn(false)
    }
  }, [enabled, record])

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

  // Devtools, by the one signal that doesn't need a debugger trick: a large gap
  // between the window and the viewport, which docked devtools opens. Reported
  // at most once — it's a hint that the sitting is worth a look, not a count.
  useEffect(() => {
    if (!enabled) return
    const check = () => {
      if (devtoolsReported.current) return
      const gap = Math.max(
        window.outerWidth - window.innerWidth,
        window.outerHeight - window.innerHeight,
      )
      if (gap > DEVTOOLS_GAP_PX) {
        devtoolsReported.current = true
        record('devtools')
      }
    }
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

  return {
    mustReturnToFullscreen: enabled && mustReturnToFullscreen,
    fullscreenExits,
    pasteBlocked,
    dismissPasteBlock,
    enterFullscreen,
    flush,
  }
}
