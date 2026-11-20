// Demo mode, wizard steps 2 and 3: show the sample's image instead of the upload area or the camera. The camera is
// never switched on in demo mode. (Customer-facing code: covered by the customer-portal source scan.)
import { Alert, Box, Stack, Typography } from '@mui/material'
import type { PickedImage } from '../../customer/usePickedImage'

interface Props {
  kind: 'document' | 'selfie'
  picked: PickedImage | null
}

export function DemoImageStep({ kind, picked }: Props) {
  const what = kind === 'document' ? 'ID document' : 'selfie'
  return (
    <Stack spacing={2} sx={{ alignItems: 'center' }}>
      <Alert severity="info" sx={{ alignSelf: 'stretch' }}>
        Demo mode: uploads and the camera are turned off. The {what} of the sample you chose is used. On the real
        system you would {kind === 'document' ? 'upload a photo of your ID here' : 'take a selfie with your camera here'}.
      </Alert>
      {picked ? (
        <>
          <Box component="img" src={picked.url} alt={kind === 'document' ? 'Preview of your ID document' : 'Your selfie'}
            sx={{ maxWidth: '100%', maxHeight: 360, borderRadius: 1, boxShadow: 1, bgcolor: '#fff' }} />
          <Typography variant="body2" color="text.secondary">{picked.name}</Typography>
        </>
      ) : (
        <Typography>Choose a sample in step 1 first.</Typography>
      )}
    </Stack>
  )
}
