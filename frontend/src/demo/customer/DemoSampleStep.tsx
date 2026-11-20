// Demo mode, wizard step 1: the visitor picks one of the bundled samples instead of typing details. The details are
// those printed on the sample document: the real run used them, so the replay matches what was submitted.
// (Customer-facing code: the customer-portal source scan covers this folder too.)
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import {
  Alert, Box, Card, CardActionArea, CardContent, CardMedia, Grid, Skeleton, Stack, Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { messageOf } from '../../api/client'
import { demoSamples, type DemoSample } from '../client'

export interface ChosenSample {
  id: string
  fullName: string
  dateOfBirth: string
  document: Blob
  selfie: Blob
}

async function imageBlob(url: string): Promise<Blob> {
  const response = await fetch(url) // a static file of this site, not an API call
  if (!response.ok) throw new Error('This sample could not be loaded. Please reload the page.')
  return response.blob()
}

interface Props {
  chosen: string | null
  error: string | null
  onChoose: (sample: ChosenSample) => void
}

export function DemoSampleStep({ chosen, error, onChoose }: Props) {
  const [samples, setSamples] = useState<DemoSample[] | null>(null)
  const [loading, setLoading] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    demoSamples().then(setSamples).catch((err: unknown) => setProblem(messageOf(err)))
  }, [])

  async function choose(sample: DemoSample) {
    setLoading(sample.id)
    setProblem(null)
    try {
      const [document, selfie] = await Promise.all([imageBlob(sample.documentUrl), imageBlob(sample.selfieUrl)])
      onChoose({ id: sample.id, fullName: sample.applicant.full_name, dateOfBirth: sample.applicant.date_of_birth,
        document, selfie })
    } catch (err) {
      setProblem(messageOf(err))
    } finally {
      setLoading(null)
    }
  }

  const picked = samples?.find((s) => s.id === chosen)
  return (
    <Stack spacing={2}>
      <Alert severity="info">
        Demo mode: choose a sample application. Each one was run through the real system; you will see a replay of
        that run. Typing your own details or uploading photos is turned off here.
      </Alert>
      {problem && <Alert severity="error" role="alert">{problem}</Alert>}
      {error && <Alert severity="error" role="alert">{error}</Alert>}
      <Grid container spacing={2} role="list" aria-label="Sample applications">
        {(samples ?? Array.from({ length: 6 }, () => null)).map((sample, index) => (
          <Grid key={sample?.id ?? index} size={{ xs: 12, sm: 6, md: 4 }} role="listitem">
            {sample ? (
              <Card variant="outlined" sx={{ height: '100%', borderWidth: 2,
                borderColor: sample.id === chosen ? 'primary.main' : 'divider' }}>
                <CardActionArea onClick={() => void choose(sample)} disabled={loading !== null}
                  aria-pressed={sample.id === chosen} sx={{ height: '100%', alignItems: 'stretch' }}>
                  <CardMedia component="img" image={sample.documentUrl} alt="" height={120}
                    sx={{ objectFit: 'cover', objectPosition: 'top', bgcolor: 'background.default' }} />
                  <CardContent>
                    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 0.5 }}>
                      {sample.id === chosen && <CheckCircleIcon color="primary" fontSize="small" aria-hidden />}
                      <Typography sx={{ fontWeight: 650 }}>{sample.title}</Typography>
                    </Stack>
                    <Typography variant="body2" color="text.secondary">
                      {loading === sample.id ? 'Loading the sample…' : sample.description}
                    </Typography>
                  </CardContent>
                </CardActionArea>
              </Card>
            ) : (
              <Skeleton variant="rounded" height={220} />
            )}
          </Grid>
        ))}
      </Grid>
      {picked && (
        <Box sx={{ p: 2, bgcolor: 'background.default', borderRadius: 1 }} data-testid="demo-details">
          <Typography variant="h3" component="h3" sx={{ mb: 1 }}>Your details (from the sample document)</Typography>
          <Typography>Full name: <b>{picked.applicant.full_name}</b></Typography>
          <Typography>Date of birth: <b>{picked.applicant.date_of_birth}</b></Typography>
        </Box>
      )}
    </Stack>
  )
}
