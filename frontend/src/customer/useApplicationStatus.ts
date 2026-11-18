import { useEffect, useState } from 'react'
import { api, isAbort, messageOf, type ApiError, type ApplicationView } from '../api/client'

// the API closes the stream at these statuses (the checks are over); only DECIDED can still change (officer)
const STREAM_ENDS = new Set(['DECIDED', 'APPROVED', 'REJECTED', 'RESUBMIT_REQUESTED'])
const FALLBACK_POLL_MS = 5_000 // stream lost (network, expired token): ask every 5 s instead
const REVIEW_POLL_MS = 15_000 // under review: an officer's decision can come any time

function waitingForOfficer(view: ApplicationView): boolean {
  return view.status === 'DECIDED' // Phase 9: DECIDED = manual review, waiting for an officer
}

function isDone(view: ApplicationView): boolean {
  return STREAM_ENDS.has(view.status) && !waitingForOfficer(view)
}

/** Follows one application: first a normal GET (shows the page at once and checks access), then live updates over
 *  Server-Sent Events until the API closes the stream. EventSource reconnects by itself after a network blip; if
 *  it gives up (e.g. the token expired), polling takes over, and a 401 there logs the user out. */
export function useApplicationStatus(applicationId: string) {
  const [view, setView] = useState<ApplicationView | null>(null)
  const [error, setError] = useState<{ status: number; message: string } | null>(null)
  const [live, setLive] = useState(false)

  useEffect(() => {
    let stopped = false
    let source: EventSource | null = null
    let timer: number | undefined
    const controller = new AbortController()

    const refresh = () => api.myApplication(applicationId, controller.signal).then((next) => {
      if (!stopped) setView(next)
      return next
    })

    const poll = (ms: number) => {
      window.clearInterval(timer)
      timer = window.setInterval(() => {
        refresh().then((next) => { if (isDone(next)) window.clearInterval(timer) }).catch(() => undefined)
      }, ms)
    }

    const afterStream = (next: ApplicationView) => {
      if (waitingForOfficer(next)) poll(REVIEW_POLL_MS)
    }

    refresh().then((first) => {
      if (stopped) return
      if (STREAM_ENDS.has(first.status)) {
        afterStream(first)
        return
      }
      source = new EventSource(api.applicationEventsUrl(applicationId))
      source.onopen = () => setLive(true)
      source.addEventListener('status', (event) => {
        const next = JSON.parse((event as MessageEvent<string>).data) as ApplicationView
        setView(next)
        if (STREAM_ENDS.has(next.status)) {
          source?.close() // otherwise EventSource would reconnect when the server ends the stream
          setLive(false)
          afterStream(next)
        }
      })
      source.onerror = () => {
        if (source?.readyState === EventSource.CLOSED) {
          setLive(false)
          poll(FALLBACK_POLL_MS)
        }
      }
    }).catch((err: unknown) => {
      if (stopped || isAbort(err)) return
      setError({ status: (err as ApiError).status ?? 0, message: messageOf(err) })
    })

    return () => {
      stopped = true
      controller.abort()
      source?.close()
      window.clearInterval(timer)
    }
  }, [applicationId])

  return { view, error, live }
}
