import { Alert, Box, Button, FormControlLabel, Stack, Switch, Typography } from '@mui/material'
import { useMemo, useState } from 'react'
import type { Heatmap } from '../api/client'
import { brand } from '../theme'
import { heatCells, heatColor, heatOpacity, legendGradient } from './heatmap'

interface Props {
  imageUrl: string
  heatmap: Heatmap | null | undefined
  onImageExpired: () => void // presigned links last 5 minutes: ask the page to fetch fresh ones
}

/** The ID image with the forgery model's tile scores drawn over it (semi-transparent) and the top tile outlined. */
export function ForgeryHeatmap({ imageUrl, heatmap, onImageExpired }: Props) {
  const [show, setShow] = useState(true)
  const [failed, setFailed] = useState(false)
  const cells = useMemo(() => (heatmap?.tiles ? heatCells(heatmap.tiles) : []), [heatmap])
  const [width, height] = heatmap?.page_size_1280 ?? [0, 0]
  const top = heatmap?.top_tile?.box_1280
  const thresholds = heatmap?.thresholds ?? {}
  const marks = [
    { at: thresholds.needs_review, label: 'review' },
    { at: thresholds.forgery_suspected, label: 'suspected' },
  ].filter((m): m is { at: number; label: string } => typeof m.at === 'number')
  const visible = show && Boolean(heatmap) && width > 0

  if (failed) {
    return (
      <Alert severity="info" action={<Button onClick={() => { setFailed(false); onImageExpired() }}>Reload</Button>}>
        The image link has expired (links are valid for 5 minutes).
      </Alert>
    )
  }

  return (
    <Box component="figure" sx={{ m: 0 }}>
      <Box sx={{ position: 'relative', lineHeight: 0, bgcolor: 'background.default', borderRadius: 1, overflow: 'hidden' }}>
        <Box component="img" src={imageUrl} alt="ID document submitted by the applicant" onError={() => setFailed(true)}
          sx={{ width: '100%', display: 'block' }} />
        {visible && (
          <Box component="svg" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" data-testid="forgery-heatmap"
            role="img" aria-label={`Forgery heatmap with ${cells.length} cells; highest tile score ${heatmap?.top_tile?.score?.toFixed(3) ?? 'unknown'}`}
            sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}>
            {cells.filter((c) => heatOpacity(c.score) > 0).map((c) => (
              <rect key={`${c.x}-${c.y}`} x={c.x} y={c.y} width={c.width} height={c.height}
                fill={heatColor(c.score)} fillOpacity={heatOpacity(c.score)}>
                <title>{`Tile score ${c.score.toFixed(3)}`}</title>
              </rect>
            ))}
            {top && top.length === 4 && (
              <g data-testid="forgery-top-tile">
                <rect x={top[0]} y={top[1]} width={top[2]} height={top[3]} fill="none" stroke="#ffffff" strokeWidth={6}
                  vectorEffect="non-scaling-stroke" />
                <rect x={top[0]} y={top[1]} width={top[2]} height={top[3]} fill="none" stroke={brand.critical}
                  strokeWidth={3} vectorEffect="non-scaling-stroke">
                  <title>{`Highest-scoring tile: ${heatmap?.top_tile?.score?.toFixed(3)}`}</title>
                </rect>
              </g>
            )}
          </Box>
        )}
      </Box>
      <Box component="figcaption" sx={{ mt: 1.5 }}>
        {heatmap ? (
          <Stack spacing={1}>
            <Stack direction="row" spacing={2} sx={{ alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', rowGap: 1 }}>
              <FormControlLabel control={<Switch checked={show} onChange={(e) => setShow(e.target.checked)} />}
                label="Forgery heatmap" sx={{ mr: 0 }} />
              <Stack direction="row" spacing={1} sx={{ alignItems: 'center', opacity: show ? 1 : 0.4 }}>
                <Box sx={{ width: 18, height: 14, border: 3, borderColor: brand.critical, outline: '2px solid #fff' }} aria-hidden />
                <Typography variant="caption">Highest-scoring tile</Typography>
              </Stack>
            </Stack>
            <Box sx={{ opacity: show ? 1 : 0.4, px: 0.5 }} aria-hidden={!show}>
              <Typography variant="caption" color="text.secondary">Tile score (forgery model)</Typography>
              <Box sx={{ position: 'relative', height: 12, borderRadius: 1, border: 1, borderColor: 'divider',
                background: `${legendGradient()}, #ffffff` }}>
                {marks.map((m) => (
                  <Box key={m.label} sx={{ position: 'absolute', left: `${m.at * 100}%`, top: -3, bottom: -3, width: 2, bgcolor: 'text.primary' }} />
                ))}
              </Box>
              <Box sx={{ position: 'relative', height: 18, mt: 0.25 }}>
                <Typography variant="caption" sx={{ position: 'absolute', left: 0 }}>0</Typography>
                {marks.map((m, i) => (
                  <Typography key={m.label} variant="caption"
                    sx={{ position: 'absolute', left: `${m.at * 100}%`, transform: i === 0 ? 'translateX(-100%)' : 'none',
                      px: 0.5, whiteSpace: 'nowrap' }}>
                    {m.label} {m.at.toFixed(3)}
                  </Typography>
                ))}
              </Box>
            </Box>
          </Stack>
        ) : (
          <Typography variant="body2" color="text.secondary">No forgery tile data for this case.</Typography>
        )}
        {heatmap && !heatmap.tiles && (
          <Typography variant="body2" color="text.secondary">
            This result was stored before tile grids were kept: only the top tile is shown.
          </Typography>
        )}
      </Box>
    </Box>
  )
}
