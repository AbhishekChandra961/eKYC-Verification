import { Box, Card, CardContent, Typography } from '@mui/material'
import type { AuditEntry } from '../api/client'
import { formatDateTime } from '../format'
import { STATUS_LABELS, actorLabel } from './labels'

/** The append-only audit log: who moved the application to which status, when, and why. */
export function AuditTimeline({ entries }: { entries: AuditEntry[] }) {
  return (
    <Card component="section" aria-labelledby="audit-title">
      <CardContent>
        <Typography id="audit-title" variant="h3" component="h3" sx={{ mb: 2 }}>Audit trail</Typography>
        <Box component="ol" sx={{ listStyle: 'none', m: 0, p: 0 }}>
          {entries.map((entry, index) => (
            <Box component="li" key={`${entry.to_status}-${entry.at}`}
              sx={{ position: 'relative', pl: 3, pb: index === entries.length - 1 ? 0 : 2,
                borderLeft: index === entries.length - 1 ? '2px solid transparent' : 2, borderColor: 'divider', ml: 0.75 }}>
              <Box aria-hidden sx={{ position: 'absolute', left: -7, top: 2, width: 12, height: 12, borderRadius: '50%',
                bgcolor: entry.actor.startsWith('officer') ? 'secondary.main' : 'primary.main', border: '2px solid #fff' }} />
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {entry.from_status ? `${STATUS_LABELS[entry.from_status]} → ` : ''}{STATUS_LABELS[entry.to_status]}
              </Typography>
              <Typography variant="body2">{entry.reason}</Typography>
              <Typography variant="caption" color="text.secondary">
                {formatDateTime(entry.at)} · {actorLabel(entry.actor)}
              </Typography>
            </Box>
          ))}
        </Box>
      </CardContent>
    </Card>
  )
}
