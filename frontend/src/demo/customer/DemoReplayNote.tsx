// Demo mode, status page: says that this is a replay of a real run, which one, and how much it is sped up.
// (Customer-facing code: covered by the customer-portal source scan.)
import { Alert } from '@mui/material'
import { useEffect, useState } from 'react'
import { formatDateTime } from '../../format'
import { describeReplay, type ReplayInfo } from '../client'

export function DemoReplayNote({ applicationId }: { applicationId: string }) {
  const [info, setInfo] = useState<ReplayInfo | null>(null)

  useEffect(() => {
    let current = true
    describeReplay(applicationId).then((next) => { if (current) setInfo(next) }).catch(() => undefined)
    return () => { current = false }
  }, [applicationId])

  if (!info) return null
  const pace = info.speed > 1.05 ? `${info.speed.toFixed(1)}× faster than real time` : 'in real time'
  return (
    <Alert severity="info" data-testid="demo-replay-note">
      Demo replay of a real run: application <code>{info.realApplicationId}</code> took{' '}
      {info.realSeconds.toFixed(1)} s on {formatDateTime(info.recordedAt)}. The status updates the system sent during
      that run are played back {pace}.
    </Alert>
  )
}
