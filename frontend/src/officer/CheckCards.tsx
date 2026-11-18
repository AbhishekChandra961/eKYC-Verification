import { Box, Card, CardContent, Stack, Typography } from '@mui/material'
import type { ReactNode } from 'react'
import type { CheckOut } from '../api/client'
import { CHECK_STATUS, FACE_BANDS, FORGERY_BANDS, docTypeLabel } from './labels'
import { fixed, num, obj, percent, list, str } from './outputs'
import { ToneChip } from './ToneChip'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <Typography component="dt" variant="body2" color="text.secondary">{label}</Typography>
      <Typography component="dd" variant="body2" sx={{ m: 0, fontVariantNumeric: 'tabular-nums' }}>{children}</Typography>
    </>
  )
}

export function CheckCard({ title, check, children }: { title: string; check: CheckOut | undefined; children: ReactNode }) {
  const status = check ? (CHECK_STATUS[check.status] ?? CHECK_STATUS.failed) : { label: 'Missing', tone: 'neutral' as const }
  return (
    <Card component="section" aria-label={`${title} check`} sx={{ height: '100%' }}>
      <CardContent>
        <Stack direction="row" spacing={1} sx={{ justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
          <Typography variant="h3" component="h3">{title}</Typography>
          {check?.status !== 'ok' && <ToneChip tone={status.tone} label={status.label} />}
        </Stack>
        {check && check.status !== 'ok' ? (
          <Typography variant="body2" color="text.secondary">{check.error ?? 'No result.'}</Typography>
        ) : check ? (
          children
        ) : (
          <Typography variant="body2" color="text.secondary">No result was stored for this check.</Typography>
        )}
        {check?.latency_ms != null && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
            Worker time {(check.latency_ms / 1000).toFixed(1)} s
          </Typography>
        )}
      </CardContent>
    </Card>
  )
}

const grid = { display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 2, rowGap: 0.75, m: 0 } as const

export function DocumentCheck({ check }: { check: CheckOut | undefined }) {
  const o = check?.outputs
  const top3 = list(o, 'top3')
  return (
    <CheckCard title="Document type" check={check}>
      {o?.blank ? (
        <ToneChip tone="warning" label="Blank or unreadable image" />
      ) : (
        <Stack spacing={1.5}>
          <Typography sx={{ fontWeight: 650 }}>{docTypeLabel(str(o, 'doc_type') ?? str(o, 'predicted_type'))}</Typography>
          <Box component="dl" sx={grid}>
            <Field label="Confidence">{percent(num(o, 'confidence'))}</Field>
            <Field label="Rejected below">{percent(num(o, 'threshold'), 0)}</Field>
          </Box>
          {top3.length > 0 && (
            <Box>
              <Typography variant="body2" color="text.secondary">Top 3</Typography>
              <Box component="ol" sx={{ m: 0, pl: 2.5 }}>
                {top3.map((t) => (
                  <Typography component="li" variant="body2" key={str(t, 'doc_type')}>
                    {docTypeLabel(str(t, 'doc_type'))}: {percent(num(t, 'probability'))}
                  </Typography>
                ))}
              </Box>
            </Box>
          )}
        </Stack>
      )}
    </CheckCard>
  )
}

export function FaceCheck({ check }: { check: CheckOut | undefined }) {
  const o = check?.outputs
  const band = FACE_BANDS[str(o, 'band') ?? ''] ?? { label: str(o, 'band') ?? 'Unknown', tone: 'neutral' as const }
  const thresholds = obj(o, 'thresholds')
  return (
    <CheckCard title="Face match" check={check}>
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center' }}>
          <Typography sx={{ fontSize: '1.5rem', fontWeight: 650, fontVariantNumeric: 'tabular-nums' }}>{fixed(num(o, 'score'))}</Typography>
          <ToneChip tone={band.tone} label={band.label} />
        </Stack>
        <Box component="dl" sx={grid}>
          <Field label="Mismatch below">{fixed(num(thresholds, 'mismatch_below'))}</Field>
          <Field label="Match from">{fixed(num(thresholds, 'match_from'), 3)}</Field>
          <Field label="Faces on ID">{num(obj(o, 'id_face'), 'faces') ?? '–'}</Field>
          <Field label="Faces on selfie">{num(obj(o, 'selfie_face'), 'faces') ?? '–'}</Field>
        </Box>
        {str(o, 'reason') && <Typography variant="body2" color="text.secondary">{str(o, 'reason')}</Typography>}
        <Typography variant="caption" color="text.secondary">
          Cosine similarity (SFace). Thresholds come from LFW; on ID portraits uncertain scores go to review.
        </Typography>
      </Stack>
    </CheckCard>
  )
}

export function ForgeryCheck({ check }: { check: CheckOut | undefined }) {
  const o = check?.outputs
  const band = FORGERY_BANDS[str(o, 'band') ?? ''] ?? { label: str(o, 'band') ?? 'Unknown', tone: 'neutral' as const }
  const thresholds = obj(o, 'thresholds')
  const tiles = obj(o, 'tiles')
  return (
    <CheckCard title="Forgery" check={check}>
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center' }}>
          <Typography sx={{ fontSize: '1.5rem', fontWeight: 650, fontVariantNumeric: 'tabular-nums' }}>{fixed(num(o, 'score'))}</Typography>
          <ToneChip tone={band.tone} label={band.label} />
        </Stack>
        <Box component="dl" sx={grid}>
          <Field label="Review from">{fixed(num(thresholds, 'needs_review'), 3)}</Field>
          <Field label="Suspected from">{fixed(num(thresholds, 'forgery_suspected'), 6)}</Field>
          <Field label="Tiles scored">{num(tiles, 'count') ?? num(o, 'tiles') ?? '–'}</Field>
        </Box>
        <Typography variant="caption" color="text.secondary">
          Page score = highest 224 px tile score. Pasted printed text (Crop and Replace) is often missed: check the fields.
        </Typography>
      </Stack>
    </CheckCard>
  )
}
