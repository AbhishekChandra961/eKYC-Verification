import { Alert, Button, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, TextField } from '@mui/material'
import { useState } from 'react'
import { messageOf, type OfficerAction } from '../api/client'

const MIN_REASON = 5

interface Props {
  action: OfficerAction
  applicationId: string
  onClose: () => void
  onConfirm: (reason: string) => Promise<void>
}

/** Confirmation with a mandatory reason (saved in the audit log). Mounted fresh for each use, so it starts empty. */
export function DecisionDialog({ action, applicationId, onClose, onConfirm }: Props) {
  const [reason, setReason] = useState('')
  const [touched, setTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const tooShort = reason.trim().length < MIN_REASON
  const approve = action === 'approve'

  async function confirm() {
    setTouched(true)
    if (tooShort) return
    setBusy(true)
    setError(null)
    try {
      await onConfirm(reason.trim())
    } catch (err) {
      setError(messageOf(err))
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={busy ? undefined : onClose} fullWidth maxWidth="sm" aria-labelledby="decision-dialog-title">
      <DialogTitle id="decision-dialog-title">{approve ? 'Approve this application?' : 'Reject this application?'}</DialogTitle>
      <DialogContent>
        <DialogContentText sx={{ mb: 2 }}>
          {approve
            ? 'The customer will see "Verified".'
            : 'The customer will see "We could not verify your identity" and be asked to contact support. They will not see your reason.'}
          {' '}Case <code>{applicationId}</code>. Your reason is stored in the audit log.
        </DialogContentText>
        {__DEMO_MODE__ && (
          <Alert severity="info" sx={{ mb: 2 }}>
            Demo mode: your decision is kept in this browser tab only and is gone when you reload. Nothing is sent anywhere.
          </Alert>
        )}
        {error && <Alert severity="error" sx={{ mb: 2 }} role="alert">{error}</Alert>}
        {/* WAI-ARIA dialog pattern: focus moves to the first field when the dialog opens */}
        {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
        <TextField label="Reason" required multiline minRows={3} fullWidth autoFocus value={reason}
          onChange={(e) => setReason(e.target.value)} onBlur={() => setTouched(true)}
          error={touched && tooShort}
          helperText={touched && tooShort ? `Please give a reason (at least ${MIN_REASON} characters).` : 'Required. Be specific: what did you check?'}
          slotProps={{ htmlInput: { maxLength: 1000 } }} />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" color={approve ? 'success' : 'error'} onClick={confirm} disabled={busy}>
          {busy ? 'Saving…' : approve ? 'Approve' : 'Reject'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
