import CheckIcon from '@mui/icons-material/Check'
import { Grid, List, ListItem, ListItemIcon, ListItemText, Paper, Typography } from '@mui/material'
import { ImageDropzone } from '../ImageDropzone'
import type { PickedImage } from '../usePickedImage'

const TIPS = [
  'Use your passport photo page or the front of your ID card.',
  'Place it on a dark, flat surface with all four corners visible.',
  'Use good, even light: no glare or shadows over the text or photo.',
  'Keep the camera straight above the document, and make sure the text is sharp.',
  'Do not cover any part of the document with your fingers.',
]

export function TipList({ title, tips }: { title: string; tips: string[] }) {
  return (
    <Paper sx={{ p: 2, bgcolor: 'background.default' }}>
      <Typography variant="h3" component="h3" sx={{ mb: 1 }}>{title}</Typography>
      <List dense disablePadding>
        {tips.map((tip) => (
          <ListItem key={tip} disableGutters sx={{ alignItems: 'flex-start' }}>
            <ListItemIcon sx={{ minWidth: 32, mt: 0.5 }}><CheckIcon fontSize="small" color="success" /></ListItemIcon>
            <ListItemText primary={tip} />
          </ListItem>
        ))}
      </List>
    </Paper>
  )
}

interface Props {
  picked: PickedImage | null
  onFile: (file: File) => void
  onClear: () => void
}

export function DocumentStep({ picked, onFile, onClear }: Props) {
  return (
    <Grid container spacing={3}>
      <Grid size={{ xs: 12, md: 7 }}>
        <ImageDropzone label="ID document photo" previewAlt="Preview of your ID document" picked={picked}
          onFile={onFile} onClear={onClear} />
      </Grid>
      <Grid size={{ xs: 12, md: 5 }}>
        <TipList title="Tips for a good photo" tips={TIPS} />
      </Grid>
    </Grid>
  )
}
