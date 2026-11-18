import { Stack, TextField, Typography } from '@mui/material'
import type { PersonalDetails, PersonalErrors } from './personal'

interface Props {
  value: PersonalDetails
  errors: PersonalErrors
  today: string
  onChange: (value: PersonalDetails) => void
}

export function PersonalDetailsStep({ value, errors, today, onChange }: Props) {
  return (
    <Stack spacing={3} sx={{ maxWidth: 480 }}>
      <Typography color="text.secondary">
        Enter your details exactly as they appear on your ID document. We compare them with the document.
      </Typography>
      <TextField label="Full name" required autoComplete="name" value={value.fullName}
        onChange={(e) => onChange({ ...value, fullName: e.target.value })}
        error={Boolean(errors.fullName)} helperText={errors.fullName ?? 'First and last name(s), for example: Maria Garcia Lopez'}
        slotProps={{ htmlInput: { maxLength: 120 } }} />
      <TextField label="Date of birth" type="date" required autoComplete="bday" value={value.dateOfBirth}
        onChange={(e) => onChange({ ...value, dateOfBirth: e.target.value })}
        error={Boolean(errors.dateOfBirth)} helperText={errors.dateOfBirth ?? ' '}
        slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: '1900-01-01', max: today } }} />
    </Stack>
  )
}
