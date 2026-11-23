import AddIcon from '@mui/icons-material/Add'
import {
  Alert, Box, Button, Chip, Paper, Skeleton, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router'
import { api, isAbort, messageOf } from '../api/client'
import { formatDateTime, visuallyHidden } from '../format'
import { toCustomerStatus, type CustomerOutcome, type CustomerStatus } from './customerStatus'

const CHIP_COLOR: Record<CustomerOutcome, 'default' | 'success' | 'info' | 'warning' | 'error'> = {
  pending: 'default', verified: 'success', under_review: 'info', resubmit: 'warning', not_verified: 'error',
}

export function MyApplications() {
  const [items, setItems] = useState<CustomerStatus[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    api.myApplications(controller.signal)
      .then((views) => setItems(views.map(toCustomerStatus))) // only the customer-safe view goes further
      .catch((err: unknown) => { if (!isAbort(err)) setError(messageOf(err)) })
    return () => controller.abort()
  }, [])

  return (
    <Stack spacing={3} className="ekyc-fade-up">
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ justifyContent: 'space-between', alignItems: { sm: 'center' } }}>
        <Box>
          <Typography variant="h1" sx={{ mb: 0.5 }}>My applications</Typography>
          <Typography color="text.secondary">Your identity verifications with SecureBank.</Typography>
        </Box>
        <Button component={RouterLink} to="/customer/verify" variant="contained" size="large" startIcon={<AddIcon />}>
          Verify my identity
        </Button>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}
      {!items && !error && <Skeleton variant="rounded" height={160} aria-label="Loading your applications" />}
      {items && items.length === 0 && (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="h2" sx={{ mb: 1 }}>No applications yet</Typography>
          <Typography color="text.secondary" sx={{ mb: 2 }}>
            Verifying takes about two minutes: you need your ID document and a camera (or a selfie photo).
          </Typography>
          <Button component={RouterLink} to="/customer/verify" variant="contained">Start verification</Button>
        </Paper>
      )}
      {items && items.length > 0 && (
        <TableContainer component={Paper}>
          <Table aria-label="My applications">
            <TableHead>
              <TableRow>
                <TableCell>Submitted</TableCell>
                <TableCell>Reference</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right"><Box component="span" sx={visuallyHidden}>Actions</Box></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.applicationId} hover>
                  <TableCell>{formatDateTime(item.submittedAt)}</TableCell>
                  <TableCell sx={{ fontFamily: 'monospace' }}>{item.applicationId}</TableCell>
                  <TableCell><Chip size="small" color={CHIP_COLOR[item.outcome]} label={item.title} /></TableCell>
                  <TableCell align="right">
                    <Button component={RouterLink} to={`/customer/applications/${item.applicationId}`} size="small"
                      aria-label={`View application ${item.applicationId}`}>
                      View
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Stack>
  )
}
