import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import CheckIcon from '@mui/icons-material/Check'
import CloseIcon from '@mui/icons-material/Close'
import {
  Alert, Box, Button, Card, CardContent, Chip, Grid, Skeleton, Snackbar, Stack, Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { Link as RouterLink, useParams } from 'react-router'
import { api, isAbort, messageOf, type ApiError, type CaseDetail, type OfficerAction } from '../api/client'
import { formatDateTime } from '../format'
import { NotFound } from '../pages/NotFound'
import { AuditTimeline } from './AuditTimeline'
import { DocumentCheck, FaceCheck, ForgeryCheck } from './CheckCards'
import { DecisionDialog } from './DecisionDialog'
import { DecisionPanel, SummaryPanel } from './DecisionPanel'
import { ExtractionPanel } from './ExtractionPanel'
import { ForgeryHeatmap } from './ForgeryHeatmap'
import { LivenessPanel } from './LivenessPanel'
import { RISK, docTypeLabel, statusLabel } from './labels'
import { ToneChip } from './ToneChip'

export function CaseDetailPage() {
  const { applicationId = '' } = useParams()
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [error, setError] = useState<{ status: number; message: string } | null>(null)
  const [version, setVersion] = useState(0) // bump to fetch again (after a decision, or for fresh image links)
  const [dialog, setDialog] = useState<OfficerAction | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [selfieFailed, setSelfieFailed] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    api.officerCase(applicationId, controller.signal)
      .then((next) => { setDetail(next); setSelfieFailed(false) })
      .catch((err: unknown) => {
        if (!isAbort(err)) setError({ status: (err as ApiError).status ?? 0, message: messageOf(err) })
      })
    return () => controller.abort()
  }, [applicationId, version])

  if (error?.status === 404) return <NotFound message="This case does not exist." />
  if (error) return <Alert severity="error">{error.message}</Alert>
  if (!detail) {
    return (
      <Stack spacing={2} aria-busy="true" aria-label="Loading the case">
        <Skeleton variant="text" width="50%" height={48} />
        <Skeleton variant="rounded" height={360} />
        <Skeleton variant="rounded" height={200} />
      </Stack>
    )
  }

  const { application, decision, checks } = detail
  const canDecide = application.status === 'DECIDED'

  async function decide(reason: string) {
    if (!dialog) return
    const result = await api.officerDecision(applicationId, dialog, reason)
    setDialog(null)
    setNotice(`Case ${result.status === 'APPROVED' ? 'approved' : 'rejected'}. The audit log has been updated.`)
    setVersion((v) => v + 1)
  }

  return (
    <Stack spacing={3} className="ekyc-fade-up">
      <Box>
        <Button component={RouterLink} to="/officer" startIcon={<ArrowBackIcon />} sx={{ mb: 1 }}>Case queue</Button>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ justifyContent: 'space-between', alignItems: { md: 'flex-end' } }}>
          <Box>
            <Typography variant="h1" sx={{ mb: 1 }}>
              Case <Box component="span" sx={{ fontFamily: 'monospace', fontSize: '0.85em' }}>{application.application_id}</Box>
            </Typography>
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1, alignItems: 'center' }}>
              <Chip label={statusLabel(application.status, decision?.outcome)} color={application.status === 'REJECTED' ? 'error'
                : application.status === 'APPROVED' ? 'success' : application.status === 'DECIDED' ? 'warning' : 'default'} />
              {decision?.risk_level && <ToneChip size="medium" tone={RISK[decision.risk_level].tone} label={RISK[decision.risk_level].label} />}
              <Typography color="text.secondary">
                {application.applicant.full_name} · born {application.applicant.date_of_birth} · {docTypeLabel(application.doc_type)}
                {' · '}submitted {formatDateTime(application.created_at)}
              </Typography>
            </Stack>
          </Box>
          {canDecide && (
            <Stack direction="row" spacing={1.5}>
              <Button variant="contained" color="success" startIcon={<CheckIcon />} onClick={() => setDialog('approve')}>Approve</Button>
              <Button variant="contained" color="error" startIcon={<CloseIcon />} onClick={() => setDialog('reject')}>Reject</Button>
            </Stack>
          )}
        </Stack>
      </Box>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 8 }}>
          <Card component="section" aria-labelledby="id-image-title" sx={{ height: '100%' }}>
            <CardContent>
              <Typography id="id-image-title" variant="h3" component="h2" sx={{ mb: 1.5 }}>ID document</Typography>
              <ForgeryHeatmap imageUrl={detail.images.document_url} heatmap={detail.forgery_heatmap}
                onImageExpired={() => setVersion((v) => v + 1)} />
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card component="section" aria-labelledby="selfie-title" sx={{ height: '100%' }}>
            <CardContent>
              <Typography id="selfie-title" variant="h3" component="h2" sx={{ mb: 1.5 }}>Selfie</Typography>
              {selfieFailed ? (
                <Alert severity="info" action={<Button onClick={() => setVersion((v) => v + 1)}>Reload</Button>}>
                  The image link has expired.
                </Alert>
              ) : (
                <Box component="img" src={detail.images.selfie_url} alt="Selfie submitted by the applicant"
                  onError={() => setSelfieFailed(true)} sx={{ width: '100%', display: 'block', borderRadius: 1 }} />
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12 }}><LivenessPanel check={checks.face} images={detail.images} /></Grid>

        <Grid size={{ xs: 12, md: 6 }}><DecisionPanel detail={detail} /></Grid>
        <Grid size={{ xs: 12, md: 6 }}><SummaryPanel detail={detail} /></Grid>

        <Grid size={{ xs: 12 }}>
          <Typography variant="h2" sx={{ mb: 2 }}>Checks</Typography>
          <Grid container spacing={3}>
            <Grid size={{ xs: 12, md: 4 }}><DocumentCheck check={checks.doc} /></Grid>
            <Grid size={{ xs: 12, md: 4 }}><FaceCheck check={checks.face} /></Grid>
            <Grid size={{ xs: 12, md: 4 }}><ForgeryCheck check={checks.forgery} /></Grid>
            <Grid size={{ xs: 12 }}><ExtractionPanel detail={detail} /></Grid>
          </Grid>
        </Grid>

        <Grid size={{ xs: 12, md: 8, lg: 6 }}><AuditTimeline entries={detail.audit_trail} /></Grid>
      </Grid>

      {dialog && (
        <DecisionDialog key={dialog} action={dialog} applicationId={application.application_id}
          onClose={() => setDialog(null)} onConfirm={decide} />
      )}
      <Snackbar open={Boolean(notice)} autoHideDuration={6000} onClose={() => setNotice(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}>
        <Alert severity="success" variant="filled" onClose={() => setNotice(null)}>{notice}</Alert>
      </Snackbar>
    </Stack>
  )
}
