import { Box, Button, Checkbox, FormControlLabel, Grid, Paper, Stack, Typography } from '@mui/material'
import type { PersonalDetails } from './personal'

interface Props {
  details: PersonalDetails
  documentUrl: string
  selfieUrl: string
  consent: boolean
  consentError: boolean
  onConsent: (value: boolean) => void
  onEdit: (step: number) => void
}

function formatDob(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleDateString(undefined, { dateStyle: 'long' })
}

export function ReviewStep({ details, documentUrl, selfieUrl, consent, consentError, onConsent, onEdit }: Props) {
  return (
    <Stack spacing={3}>
      <Paper sx={{ p: 2 }}>
        <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <Box component="dl" sx={{ m: 0, display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 3, rowGap: 1 }}>
            <Typography component="dt" color="text.secondary">Full name</Typography>
            <Typography component="dd" sx={{ m: 0, fontWeight: 600 }}>{details.fullName.trim()}</Typography>
            <Typography component="dt" color="text.secondary">Date of birth</Typography>
            <Typography component="dd" sx={{ m: 0, fontWeight: 600 }}>{formatDob(details.dateOfBirth)}</Typography>
          </Box>
          <Button size="small" onClick={() => onEdit(0)} aria-label="Edit personal details">Edit</Button>
        </Stack>
      </Paper>
      <Grid container spacing={2}>
        {[
          { title: 'ID document', url: documentUrl, alt: 'Your ID document', step: 1 },
          { title: 'Selfie', url: selfieUrl, alt: 'Your selfie', step: 2 },
        ].map((item) => (
          <Grid key={item.title} size={{ xs: 12, sm: 6 }}>
            <Paper sx={{ p: 2, height: '100%' }}>
              <Stack direction="row" sx={{ justifyContent: 'space-between', mb: 1 }}>
                <Typography variant="h3" component="h3">{item.title}</Typography>
                <Button size="small" onClick={() => onEdit(item.step)} aria-label={`Change the ${item.title.toLowerCase()}`}>
                  Change
                </Button>
              </Stack>
              <Box component="img" src={item.url} alt={item.alt}
                sx={{ width: '100%', maxHeight: 260, objectFit: 'contain', bgcolor: 'background.default', borderRadius: 1 }} />
            </Paper>
          </Grid>
        ))}
      </Grid>
      <FormControlLabel
        control={<Checkbox checked={consent} onChange={(e) => onConsent(e.target.checked)}
          slotProps={{ input: { 'aria-invalid': consentError } }} />}
        label="I confirm that these details and photos are mine and correct, and I agree that SecureBank may use them to verify my identity."
      />
      {consentError && <Typography color="error" role="alert">Please confirm to continue.</Typography>}
    </Stack>
  )
}
