// Dashboard 3, Model performance: the offline evaluations (reports/phase3-5), including the forgery v1 -> v2 -> v3
// shortcut story. These are not batch numbers, so the batch filters do not apply here.
import {
  Alert, Box, Grid, List, ListItem, ListItemText, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Typography, useMediaQuery, useTheme,
} from '@mui/material'
import { BarChart } from '@mui/x-charts/BarChart'
import { ChartsReferenceLine } from '@mui/x-charts/ChartsReferenceLine'
import { barChartHeight, chartBase, thinBands, tickLabelStyle } from './chartStyle'
import { ChartCard } from './DashboardParts'
import { metricValue, percent, wrapLabel } from './format'
import { SERIES, ink } from './palette'
import type { ModelRow } from './snapshot'
import {
  FORGERY_METRICS, extractionPerField, faceComparison, faceSyntheticFalseAccepts, forgeryStory, forgeryTestPrAuc,
  type ForgeryVersion,
} from './transforms'

/** One line per forgery version: why it was rejected or accepted (the numbers come from the snapshot). */
function storyLine(v: ForgeryVersion, testPrAuc: number | null): string {
  const pr = metricValue(v.values['document PR-AUC'])
  const heat = percent(v.values['localisation (heat on the edit)'], 1)
  const control = metricValue(v.values['position-matched control AUC (~0.5 = no cue)'])
  if (v.order === 1) return `Rejected: shortcuts. The best-looking PR-AUC (${pr}), but the heat was on the edit for ${heat} of forged pages: it learned the recording style and JPEG quality, not the edits.`
  if (v.order === 2) return `Rejected: a hidden compression cue. The heat finds the edit (${heat}), but the position-matched control scores ${control} instead of ~0.5.`
  return `Accepted: every shortcut check passes (control ${control}). A slightly lower, honest PR-AUC (${pr}); ${testPrAuc === null ? '' : `${metricValue(testPrAuc)} on the one test run.`}`
}

const asValue = (v: number | null) => metricValue(v)
const shortLabel = (item: { value: number | null }) => (item.value === null ? null : String(Number(item.value.toFixed(3))))

export function ModelPerformanceTab({ rows }: { rows: ModelRow[] }) {
  const theme = useTheme()
  const narrow = useMediaQuery(theme.breakpoints.down('sm'))
  const story = forgeryStory(rows)
  const testPrAuc = forgeryTestPrAuc(rows)
  const face = faceComparison(rows)
  const syntheticFar = faceSyntheticFalseAccepts(rows)
  const fields = extractionPerField(rows)

  return (
    <Grid container spacing={2}>
      <Grid size={12}>
        <Alert severity="info" variant="outlined">
          Offline evaluations of the models (validation and test splits, LFW for faces), from <code>reports/</code>. They
          are not batch numbers, so the document-type and outcome filters do not apply here.
        </Alert>
      </Grid>

      <Grid size={{ xs: 12, md: 7 }}>
        <ChartCard title="Forgery detector: v1 → v2 → v3 (the shortcut story)"
          subtitle="Validation split. A high score is not enough: the heat must land on the edit, and the control AUC must stay near 0.5 (the line: no hidden cue)."
          table={{ columns: ['Version', ...FORGERY_METRICS.map((m) => m.label)],
            rows: story.map((v) => [v.version, ...FORGERY_METRICS.map((m) => metricValue(v.values[m.metric]))]) }}
          footer={
            <List dense disablePadding data-testid="forgery-story">
              {story.map((v) => (
                <ListItem key={v.version} disableGutters>
                  <ListItemText primary={v.version} secondary={storyLine(v, testPrAuc)}
                    slotProps={{ primary: { sx: { fontWeight: 600 } } }} />
                </ListItem>
              ))}
            </List>
          }>
          <BarChart {...chartBase} height={320} grid={{ horizontal: true }}
            slotProps={{ legend: { position: { vertical: 'top', horizontal: 'start' } } }}
            xAxis={[{ scaleType: 'band', data: story.map((v) => v.version),
              valueFormatter: (v: string) => wrapLabel(v, narrow ? 10 : 18), tickLabelStyle, ...thinBands }]}
            yAxis={[{ min: 0, max: 1.1, tickInterval: [0, 0.2, 0.4, 0.6, 0.8, 1], tickLabelStyle, width: 40 }]} // room above 1 for the labels
            series={FORGERY_METRICS.map((m, i) => ({
              data: story.map((v) => v.values[m.metric]), label: m.label, color: SERIES[i], valueFormatter: asValue,
              barLabel: shortLabel, barLabelPlacement: 'outside',
            }))}>
            <ChartsReferenceLine y={0.5} lineStyle={{ stroke: ink.secondary, strokeWidth: 1 }} />
          </BarChart>
        </ChartCard>
      </Grid>

      <Grid size={{ xs: 12, md: 5 }}>
        <ChartCard title="Face verification"
          subtitle="LFW test split: the production model (SFace) against the Siamese network trained here (a showcase). FAR = false accept rate; for the equal error rate, lower is better."
          table={{ columns: ['Metric', ...face.versions], rows: face.metrics.map((m) => [m.label, ...m.values.map(metricValue)]) }}
          footer={syntheticFar !== null && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              On synthetic ID portraits SFace accepts {percent(syntheticFar)} of different-person pairs at the LFW
              threshold, so face scores below 0.556 go to manual review.
            </Typography>
          )}>
          <BarChart {...chartBase} height={300} grid={{ horizontal: true }}
            slotProps={{ legend: { position: { vertical: 'top', horizontal: 'start' } } }}
            xAxis={[{ scaleType: 'band', data: face.metrics.map((m) => m.label),
              valueFormatter: (v: string) => wrapLabel(v, narrow ? 12 : 16), tickLabelStyle, ...thinBands }]}
            yAxis={[{ min: 0, max: 1.1, tickInterval: [0, 0.2, 0.4, 0.6, 0.8, 1], tickLabelStyle, width: 40 }]} // room above 1 for the labels
            series={face.versions.map((version, i) => ({
              data: face.metrics.map((m) => m.values[i]), label: version, color: SERIES[i], valueFormatter: asValue,
              barLabel: shortLabel, barLabelPlacement: 'outside',
            }))} />
        </ChartCard>
      </Grid>

      <Grid size={12}>
        <ChartCard title="Field extraction accuracy per field"
          subtitle="Test split, qwen2.5vl:7b (prompt v2): share of documents where the field matches the annotation, exactly or after normalization (case, spacing, date and gender formats). The MRZ lines are the weak point."
          table={{ columns: ['Field', 'Exact', 'Normalized', 'Documents'],
            rows: fields.map((f) => [f.field, percent(f.exact), percent(f.normalized), f.documents]) }}>
          <BarChart {...chartBase} layout="horizontal" height={barChartHeight(fields.length, 36) + 32}
            grid={{ vertical: true }} slotProps={{ legend: { position: { vertical: 'top', horizontal: 'start' } } }}
            yAxis={[{ scaleType: 'band', data: fields.map((f) => f.field), width: 120, tickLabelStyle, ...thinBands }]}
            xAxis={[{ min: 0, max: 1, tickInterval: [0, 0.2, 0.4, 0.6, 0.8, 1], valueFormatter: (v: number) => percent(v, 0), tickLabelStyle }]}
            series={[
              { data: fields.map((f) => f.exact), label: 'Exact match', color: SERIES[0], valueFormatter: (v) => percent(v) },
              { data: fields.map((f) => f.normalized), label: 'Normalized match', color: SERIES[2], valueFormatter: (v) => percent(v) },
            ]} />
        </ChartCard>
      </Grid>

      <Grid size={12}>
        <Paper component="section" aria-labelledby="metrics-table-title" sx={{ p: 2 }}>
          <Typography variant="h3" id="metrics-table-title">All model metrics</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 1 }}>
            The full record of the offline evaluations ({rows.length} metrics). Each test split was used once per model.
          </Typography>
          <Box>
            <TableContainer sx={{ maxHeight: 480 }}>
              <Table size="small" stickyHeader aria-label="All model metrics" data-testid="metrics-table">
                <TableHead>
                  <TableRow>
                    {['Model', 'Version', 'Split', 'Metric', 'Value', 'Source'].map((c) =>
                      <TableCell key={c} align={c === 'Value' ? 'right' : 'left'}>{c}</TableCell>)}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((r, i) => (
                    <TableRow key={i} hover>
                      <TableCell>{r.model}</TableCell>
                      <TableCell>{r.version}</TableCell>
                      <TableCell>{r.split}</TableCell>
                      <TableCell>{r.metric}{r.note && <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>{r.note}</Typography>}</TableCell>
                      <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>{metricValue(r.value)}</TableCell>
                      <TableCell sx={{ color: 'text.secondary', wordBreak: 'break-all' }}><code>{r.source}</code></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Box>
        </Paper>
      </Grid>
    </Grid>
  )
}
