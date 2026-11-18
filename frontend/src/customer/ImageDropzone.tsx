import CloudUploadIcon from '@mui/icons-material/CloudUploadOutlined'
import { Alert, Box, Button, Stack, Typography } from '@mui/material'
import { useId, useState, type ChangeEvent, type DragEvent } from 'react'
import { formatBytes, visuallyHidden } from '../format'
import { ACCEPT_ATTRIBUTE } from './imageValidation'
import type { PickedImage } from './usePickedImage'

interface Props {
  label: string // e.g. "ID document photo"
  previewAlt: string
  picked: PickedImage | null
  onFile: (file: File) => void
  onClear: () => void
}

/** Drag-and-drop area plus a normal file button (keyboard and screen-reader friendly), with a preview. */
export function ImageDropzone({ label, previewAlt, picked, onFile, onClear }: Props) {
  const [dragging, setDragging] = useState(false)
  const hintId = useId()

  function handleInput(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (file) onFile(file)
    event.target.value = '' // choosing the same file again still fires a change
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files?.[0]
    if (file) onFile(file)
  }

  const chooseButton = (text: string, variant: 'contained' | 'outlined') => (
    <Button component="label" variant={variant} startIcon={<CloudUploadIcon />} aria-describedby={hintId}>
      {text}
      <Box component="input" type="file" accept={ACCEPT_ATTRIBUTE} onChange={handleInput} sx={visuallyHidden}
        aria-label={label} />
    </Button>
  )

  return (
    <Stack spacing={1.5}>
      <Box
        onDragOver={(event: DragEvent) => { event.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        sx={{
          border: 2, borderStyle: 'dashed', borderRadius: 2, p: { xs: 2, sm: 3 }, textAlign: 'center',
          borderColor: dragging ? 'primary.main' : 'divider', bgcolor: dragging ? 'action.hover' : 'background.default',
          transition: 'background-color 120ms, border-color 120ms',
        }}
      >
        {picked ? (
          <Stack spacing={2} sx={{ alignItems: 'center' }}>
            <Box component="img" src={picked.url} alt={previewAlt}
              sx={{ maxWidth: '100%', maxHeight: 320, borderRadius: 1, boxShadow: 1, bgcolor: '#fff' }} />
            <Typography variant="body2" color="text.secondary">
              {picked.name} · {formatBytes(picked.blob.size)}
            </Typography>
            <Stack direction="row" spacing={1}>
              {chooseButton('Choose another', 'outlined')}
              <Button onClick={onClear} color="inherit">Remove</Button>
            </Stack>
          </Stack>
        ) : (
          <Stack spacing={1.5} sx={{ alignItems: 'center' }}>
            <Typography sx={{ fontWeight: 600 }}>Drag and drop your photo here</Typography>
            <Typography variant="body2" color="text.secondary">or</Typography>
            {chooseButton('Choose a file', 'contained')}
          </Stack>
        )}
        <Typography id={hintId} variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
          JPEG or PNG, up to 10 MB.
        </Typography>
      </Box>
      {picked?.error && <Alert severity="error" role="alert">{picked.error}</Alert>}
      {!picked?.error && picked?.warning && <Alert severity="warning">{picked.warning}</Alert>}
    </Stack>
  )
}
