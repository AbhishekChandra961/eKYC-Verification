import {
  Alert, Box, Card, CardContent, Grid, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography,
} from '@mui/material'
import type { CaseDetail } from '../api/client'
import { FIELD_LABELS, RULE_FIELDS, RULE_SEVERITY, ruleLabel, type Tone } from './labels'
import { list, obj, str, type Outputs } from './outputs'
import { ToneChip } from './ToneChip'

const OTHER_FIELDS = ['document_number', 'personal_number', 'nationality', 'gender', 'birth_place', 'issue_date',
  'expiry_date', 'authority', 'mrz_line0', 'mrz_line1']

interface Comparison {
  label: string
  entered: string
  extracted: string
  result: { label: string; tone: Tone }
}

/** Applicant-entered vs extracted, judged by the DECISION ENGINE (its reasons), not re-computed here: the engine's
 *  name match ignores case, accents and word order, and tolerates small typos. */
function comparisons(detail: CaseDetail, fields: Outputs, extractionOk: boolean): Comparison[] {
  const codes = new Set((detail.decision?.reasons ?? []).map((r) => r.code))
  const notChecked = { label: 'Not checked', tone: 'neutral' as const }
  const documentName = [str(fields, 'given_names'), str(fields, 'surname')].filter(Boolean).join(' ')
  return [
    {
      label: 'Full name',
      entered: detail.application.applicant.full_name,
      extracted: documentName || '–',
      result: !extractionOk ? notChecked
        : codes.has('name_mismatch') ? { label: 'Mismatch', tone: 'warning' } : { label: 'Match', tone: 'good' },
    },
    {
      label: 'Date of birth',
      entered: detail.application.applicant.date_of_birth,
      extracted: str(fields, 'birth_date') ?? '–',
      result: !extractionOk ? notChecked
        : codes.has('dob_mismatch') ? { label: 'Mismatch', tone: 'critical' }
          : codes.has('dob_unverified') ? { label: 'Unreadable', tone: 'warning' } : { label: 'Match', tone: 'good' },
    },
  ]
}

export function ExtractionPanel({ detail }: { detail: CaseDetail }) {
  const check = detail.checks.extraction
  const outputs = check?.outputs
  const fields = obj(outputs, 'fields') ?? {}
  const flags = list(outputs, 'flags')
  const ok = check?.status === 'ok'
  const flaggedFields = new Map<string, Outputs[]>()
  for (const flag of flags) {
    for (const field of RULE_FIELDS[str(flag, 'rule') ?? ''] ?? []) {
      flaggedFields.set(field, [...(flaggedFields.get(field) ?? []), flag])
    }
  }

  return (
    <Card component="section" aria-labelledby="extraction-title">
      <CardContent>
        <Typography id="extraction-title" variant="h3" component="h3" sx={{ mb: 0.5 }}>Extracted fields</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Read from the ID image by the on-premises vision model (qwen2.5vl), then checked with consistency rules.
        </Typography>
        {!ok && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            Extraction {check ? check.status.replace('_', ' ') : 'missing'}{check?.error ? `: ${check.error}` : ''}. Check the
            fields against the image by hand.
          </Alert>
        )}
        <Grid container spacing={3}>
          <Grid size={{ xs: 12, lg: 6 }}>
            <Typography variant="subtitle2" component="h4" sx={{ mb: 1 }}>Applicant vs document</Typography>
            <TableContainer>
              <Table size="small" aria-label="Applicant-entered data compared with the document">
                <TableHead>
                  <TableRow>
                    <TableCell>Field</TableCell>
                    <TableCell>Entered by applicant</TableCell>
                    <TableCell>On the document</TableCell>
                    <TableCell>Result</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {comparisons(detail, fields, ok).map((row) => (
                    <TableRow key={row.label}
                      sx={row.result.label === 'Mismatch' ? { bgcolor: row.result.tone === 'critical' ? '#fdecea' : '#fff4e0' } : undefined}>
                      <TableCell component="th" scope="row">{row.label}</TableCell>
                      <TableCell>{row.entered}</TableCell>
                      <TableCell>{row.extracted}</TableCell>
                      <TableCell><ToneChip tone={row.result.tone} label={row.result.label} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            <Typography variant="subtitle2" component="h4" sx={{ mt: 3, mb: 1 }}>Consistency rules</Typography>
            {flags.length === 0 ? (
              <Typography variant="body2" color="text.secondary">{ok ? 'No rule flagged this document.' : 'Not run.'}</Typography>
            ) : (
              <Stack spacing={1} component="ul" sx={{ listStyle: 'none', p: 0, m: 0 }}>
                {flags.map((flag) => {
                  const severity = RULE_SEVERITY[str(flag, 'severity') ?? ''] ?? { label: str(flag, 'severity') ?? 'Flag', tone: 'neutral' as const }
                  return (
                    <Box component="li" key={str(flag, 'rule')} sx={{ display: 'flex', gap: 1, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                      <ToneChip tone={severity.tone} label={severity.label} />
                      <Box>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>{ruleLabel(str(flag, 'rule') ?? '')}</Typography>
                        {str(flag, 'detail') && (
                          <Typography variant="body2" sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>{str(flag, 'detail')}</Typography>
                        )}
                      </Box>
                    </Box>
                  )
                })}
              </Stack>
            )}
          </Grid>
          <Grid size={{ xs: 12, lg: 6 }}>
            <Typography variant="subtitle2" component="h4" sx={{ mb: 1 }}>Other fields</Typography>
            <TableContainer>
              <Table size="small" aria-label="Other extracted fields">
                <TableBody>
                  {['surname', 'given_names', ...OTHER_FIELDS].map((field) => {
                    const flagged = flaggedFields.get(field) ?? []
                    const value = str(fields, field)
                    const strong = flagged.some((f) => str(f, 'severity') === 'strong')
                    return (
                      <TableRow key={field} sx={flagged.length ? { bgcolor: strong ? '#fdecea' : '#fff4e0' } : undefined}>
                        <TableCell component="th" scope="row" sx={{ color: 'text.secondary', width: '35%' }}>
                          {FIELD_LABELS[field] ?? field}
                        </TableCell>
                        <TableCell sx={{ fontFamily: field.startsWith('mrz') ? 'monospace' : undefined, wordBreak: 'break-all' }}>
                          {value ?? <Box component="span" sx={{ color: 'text.secondary' }}>not read</Box>}
                          {flagged.length > 0 && (
                            <Typography variant="caption" sx={{ display: 'block', fontFamily: 'inherit', color: 'text.secondary' }}>
                              flagged by: {flagged.map((f) => ruleLabel(str(f, 'rule') ?? '')).join(', ')}
                            </Typography>
                          )}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          </Grid>
        </Grid>
      </CardContent>
    </Card>
  )
}
