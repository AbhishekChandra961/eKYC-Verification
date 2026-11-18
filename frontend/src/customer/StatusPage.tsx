import { Alert, Skeleton, Stack } from '@mui/material'
import { useParams } from 'react-router'
import { NotFound } from '../pages/NotFound'
import { CustomerStatusView } from './CustomerStatusView'
import { toCustomerStatus } from './customerStatus'
import { useApplicationStatus } from './useApplicationStatus'

export function StatusPage() {
  const { applicationId = '' } = useParams()
  const { view, error, live } = useApplicationStatus(applicationId)

  if (error?.status === 404) return <NotFound message="We could not find this application." />
  if (error) return <Alert severity="error">{error.message}</Alert>
  if (!view) {
    return (
      <Stack spacing={2} aria-busy="true" aria-label="Loading your application">
        <Skeleton variant="text" width="40%" height={48} />
        <Skeleton variant="rounded" height={96} />
        <Skeleton variant="rounded" height={140} />
      </Stack>
    )
  }
  return <CustomerStatusView status={toCustomerStatus(view)} live={live} />
}
