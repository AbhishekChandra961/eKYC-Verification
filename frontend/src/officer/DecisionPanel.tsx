import { Alert, AlertTitle, Box, Card, CardContent, Stack, Typography } from '@mui/material'
import type { CaseDetail } from '../api/client'
import { formatDateTime } from '../format'
import { EFFECTS, OUTCOME_LABELS, RISK, actorLabel } from './labels'
import { evidenceText } from './outputs'
import { ToneChip } from './ToneChip'

/** The decision engine's outcome, risk and every reason with the evidence values behind it. */
export function DecisionPanel({ detail }: { detail: CaseDetail }) {
  const decision = detail.decision
  if (!decision) {
    return (
      <Card><CardContent>
        <Typography variant="h3" component="h3">Decision</Typography>
        <Typography color="text.secondary">The checks are still running.</Typography>
      </CardContent></Card>
    )
  }
  const officer = detail.application.officer_decision
  return (
    <Card component="section" aria-labelledby="decision-title">
      <CardContent>
        <Stack spacing={2}>
          <Typography id="decision-title" variant="h3" component="h3">System decision</Typography>
          <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
            <Typography sx={{ fontSize: '1.25rem', fontWeight: 650 }}>{OUTCOME_LABELS[decision.outcome]}</Typography>
            {decision.risk_level && <ToneChip size="medium" tone={RISK[decision.risk_level].tone} label={RISK[decision.risk_level].label} />}
            <Typography color="text.secondary" sx={{ fontVariantNumeric: 'tabular-nums' }}>
              Risk score <strong>{decision.risk_score.toFixed(1)}</strong> / 100
            </Typography>
          </Stack>
          {decision.early && (
            <Typography variant="body2" color="text.secondary">Decided early: the document was unusable, so the other checks were skipped.</Typography>
          )}
          {officer && (
            <Alert severity={officer.action === 'approve' ? 'success' : 'error'} variant="outlined">
              <AlertTitle>{officer.action === 'approve' ? 'Approved' : 'Rejected'} by {actorLabel(`officer:${officer.officer_id}`)}</AlertTitle>
              {officer.reason} <Typography component="span" variant="body2" color="text.secondary">({formatDateTime(officer.at)})</Typography>
            </Alert>
          )}
          <Box>
            <Typography variant="subtitle2" component="h4" sx={{ mb: 1 }}>Reasons</Typography>
            {(decision.reasons ?? []).length === 0 ? (
              <Typography variant="body2" color="text.secondary">No reasons: every check passed.</Typography>
            ) : (
              <Stack component="ul" spacing={1.5} sx={{ listStyle: 'none', p: 0, m: 0 }}>
                {(decision.reasons ?? []).map((reason) => {
                  const effect = EFFECTS[reason.effect] ?? EFFECTS.info
                  const evidence = Object.entries(reason.evidence ?? {})
                  return (
                    <Box component="li" key={reason.code} sx={{ display: 'flex', gap: 1.5, alignItems: 'flex-start' }}>
                      <Box sx={{ minWidth: 92 }}><ToneChip tone={effect.tone} label={effect.label} /></Box>
                      <Box sx={{ minWidth: 0 }}>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>{reason.message || reason.code}</Typography>
                        <Typography variant="caption" color="text.secondary" component="div">
                          {reason.code}{reason.check_type ? ` · ${reason.check_type} check` : ''}
                        </Typography>
                        {evidence.length > 0 && (
                          <Box component="dl" sx={{ m: 0, mt: 0.5, display: 'flex', flexWrap: 'wrap', columnGap: 2, rowGap: 0.25 }}>
                            {evidence.map(([key, value]) => (
                              <Box key={key} sx={{ display: 'flex', gap: 0.5 }}>
                                <Typography component="dt" variant="caption" color="text.secondary">{key}</Typography>
                                <Typography component="dd" variant="caption" sx={{ m: 0, fontFamily: 'monospace', wordBreak: 'break-all' }}>
                                  {evidenceText(value)}
                                </Typography>
                              </Box>
                            ))}
                          </Box>
                        )}
                      </Box>
                    </Box>
                  )
                })}
              </Stack>
            )}
          </Box>
        </Stack>
      </CardContent>
    </Card>
  )
}

/** The template summary is the official record; an LLM note, if any, is clearly marked as AI-assisted. */
export function SummaryPanel({ detail }: { detail: CaseDetail }) {
  return (
    <Stack spacing={2}>
      <Card component="section" aria-labelledby="summary-title">
        <CardContent>
          <Typography id="summary-title" variant="h3" component="h3" sx={{ mb: 1 }}>Official summary</Typography>
          <Typography variant="body2" sx={{ whiteSpace: 'pre-line' }}>
            {detail.summary ?? 'Written when the checks are complete.'}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
            Generated from a fixed template: the record of this decision.
          </Typography>
        </CardContent>
      </Card>
      {detail.ai_note && (
        <Alert severity="warning" variant="outlined" sx={{ bgcolor: 'background.paper' }}>
          <AlertTitle>AI-assisted note - verify before relying on it</AlertTitle>
          <Typography variant="body2" sx={{ whiteSpace: 'pre-line' }}>{detail.ai_note}</Typography>
        </Alert>
      )}
    </Stack>
  )
}
