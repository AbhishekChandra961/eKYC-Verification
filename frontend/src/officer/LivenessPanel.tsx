// The officer's view of the active liveness check (Phase 13): the three camera frames side by side, with the result
// and the values the server measured (head yaw per frame, the turns from the looking-at-the-camera frame, and the
// same-person similarity). The check runs in the face-worker (src/ekyc/liveness.py), never in the browser.
import { Box, Card, CardContent, Grid, Stack, Typography } from '@mui/material'
import { useState } from 'react'
import type { CaseDetail, CheckOut } from '../api/client'
import type { Tone } from './labels'
import { num, obj, str } from './outputs'
import { ToneChip } from './ToneChip'

const FAILURES: Record<string, string> = {
  no_left_turn: 'No clear turn to the left',
  no_right_turn: 'No clear turn to the right',
  not_frontal: 'Not looking at the camera in the first frame',
  no_face_neutral: 'No face in the first frame',
  no_face_left: 'No face in the left-turn frame',
  no_face_right: 'No face in the right-turn frame',
  different_person: 'The frames do not all show the same person',
}

function verdict(status: string | null, failures: string[]): { label: string; tone: Tone } {
  if (status === 'passed') return { label: 'Passed', tone: 'good' }
  if (status === 'failed') {
    return failures.includes('different_person') ? { label: 'Different people', tone: 'critical' }
      : { label: 'Failed: retake requested', tone: 'warning' }
  }
  return { label: 'Not provided', tone: 'neutral' }
}

const deg = (value: number | null) => (value === null ? '–' : `${value > 0 ? '+' : ''}${value.toFixed(1)}°`)

function Frame({ url, title, lines }: { url: string | null | undefined; title: string; lines: string[] }) {
  const [broken, setBroken] = useState(false)
  return (
    <Box component="figure" sx={{ m: 0 }}>
      {url && !broken ? (
        <Box component="img" src={url} alt={`Camera frame: ${title.toLowerCase()}`} onError={() => setBroken(true)}
          sx={{ width: '100%', aspectRatio: '4 / 3', objectFit: 'cover', borderRadius: 1, display: 'block', bgcolor: '#000' }} />
      ) : (
        <Box sx={{ aspectRatio: '4 / 3', borderRadius: 1, bgcolor: 'background.default', display: 'grid', placeItems: 'center',
          border: 1, borderColor: 'divider' }}>
          <Typography variant="caption" color="text.secondary">{url ? 'Link expired: reload the case' : 'No frame'}</Typography>
        </Box>
      )}
      <Typography component="figcaption" variant="body2" sx={{ mt: 0.5, fontWeight: 600 }}>{title}</Typography>
      {lines.map((line) => (
        <Typography key={line} variant="caption" color="text.secondary" sx={{ display: 'block', fontVariantNumeric: 'tabular-nums' }}>
          {line}
        </Typography>
      ))}
    </Box>
  )
}

export function LivenessPanel({ check, images }: { check: CheckOut | undefined; images: CaseDetail['images'] }) {
  const live = obj(check?.outputs, 'liveness')
  const status = check?.status === 'ok' ? (str(live, 'status') ?? 'not_provided') : null
  const failures = Array.isArray(live?.failures) ? (live.failures as string[]) : []
  const yaw = obj(live, 'yaw_deg')
  const turn = obj(live, 'turn_deg')
  const same = obj(live, 'same_person_cosine')
  const thresholds = obj(live, 'thresholds')
  const result = verdict(status, failures)
  return (
    <Card component="section" aria-labelledby="liveness-title" data-testid="liveness-panel">
      <CardContent>
        <Stack direction="row" spacing={1} sx={{ justifyContent: 'space-between', alignItems: 'center', mb: 1.5, flexWrap: 'wrap' }}>
          <Typography id="liveness-title" variant="h3" component="h2">Liveness: head-turn check</Typography>
          {check?.status === 'ok' ? <ToneChip tone={result.tone} label={result.label} />
            : <ToneChip tone="neutral" label="Face check did not complete" />}
        </Stack>
        {status === 'not_provided' ? (
          <Typography variant="body2" color="text.secondary">
            No head-turn frames: the applicant uploaded a photo instead of using the camera (or the case predates the
            check). The case goes to a medium-risk review.
          </Typography>
        ) : status ? (
          <Stack spacing={1.5}>
            {failures.length > 0 && (
              <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
                {failures.map((f) => <Typography component="li" variant="body2" key={f}>{FAILURES[f] ?? f}</Typography>)}
              </Box>
            )}
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, sm: 4 }}>
                <Frame url={images.selfie_url} title="Looking at the camera (the selfie)" lines={[`Yaw ${deg(num(yaw, 'neutral'))}`]} />
              </Grid>
              <Grid size={{ xs: 12, sm: 4 }}>
                <Frame url={images.liveness_left_url} title="Turned left"
                  lines={[`Yaw ${deg(num(yaw, 'left'))}, turn ${deg(num(turn, 'left'))}`,
                    `Same person ${num(same, 'left')?.toFixed(3) ?? '–'}`]} />
              </Grid>
              <Grid size={{ xs: 12, sm: 4 }}>
                <Frame url={images.liveness_right_url} title="Turned right"
                  lines={[`Yaw ${deg(num(yaw, 'right'))}, turn ${deg(num(turn, 'right'))}`,
                    `Same person ${num(same, 'right')?.toFixed(3) ?? '–'}`]} />
              </Grid>
            </Grid>
            <Typography variant="caption" color="text.secondary">
              Needed: a turn of at least {num(thresholds, 'min_turn_deg') ?? 20}° each way from the first frame, which must
              face the camera (within {num(thresholds, 'max_neutral_yaw_deg') ?? 15}°), and a same-person similarity of at
              least {num(thresholds, 'same_person_min_cosine') ?? 0.2597} (SFace) between the frames. Yaw from the YuNet
              landmarks: + is the applicant's left. A deterrent against a held-up photo, not certified presentation-attack
              detection: a replayed video or a mask could pass.
            </Typography>
          </Stack>
        ) : (
          <Typography variant="body2" color="text.secondary">{check?.error ?? 'No face check result.'}</Typography>
        )}
      </CardContent>
    </Card>
  )
}
