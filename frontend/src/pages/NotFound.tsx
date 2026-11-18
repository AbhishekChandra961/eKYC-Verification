import { Button, Stack, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router'

export function NotFound({ message = 'This page does not exist.' }: { message?: string }) {
  return (
    <Stack spacing={2} sx={{ alignItems: 'flex-start' }}>
      <Typography variant="h1">Not found</Typography>
      <Typography>{message}</Typography>
      <Button component={RouterLink} to="/" variant="outlined">Go to the home page</Button>
    </Stack>
  )
}
