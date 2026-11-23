// Dashboard 2, Risk & fraud: what the system flags, and whether it is right (compared with the batch's ground truth).
import {
  Box, Grid, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tooltip, Typography, alpha,
} from '@mui/material'
import { visuallyHidden } from '../format'
import { BarChart } from '@mui/x-charts/BarChart'
import { barChartHeight, chartBase, thinBands, tickLabelStyle } from './chartStyle'
import { ChartCard, KpiTile, Legend, NoData } from './DashboardParts'
import { percent } from './format'
import { AGREEMENT_COLORS, EFFECT_COLORS, MEASURE, verdictColor } from './palette'
import type { RiskFraudRow } from './snapshot'
import {
  EFFECTS, SYSTEM_OUTCOMES, TRUTH_CLASSES, caseRows, confusionMatrix, officerAgreement, reasonFrequencies, riskKpis,
  riskScoreDistribution,
} from './transforms'

const cases = (v: number | null) => (v === null ? null : `${v} case${v === 1 ? '' : 's'}`)

/** The highlight table: rows = ground truth, columns = system decision, each cell tinted and labelled by its verdict. */
function ConfusionTable({ rows }: { rows: RiskFraudRow[] }) {
  const m = confusionMatrix(rows)
  return (
    <TableContainer>
      <Table size="small" aria-label="System decision (columns) versus ground truth (rows), applications per cell"
        data-testid="confusion-table">
        <TableHead>
          <TableRow>
            <TableCell>Ground truth ↓ / System →</TableCell>
            {SYSTEM_OUTCOMES.map((o) => <TableCell key={o} align="center">{o}</TableCell>)}
            <TableCell align="right">Total</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {TRUTH_CLASSES.map((truth) => (
            <TableRow key={truth}>
              <TableCell component="th" scope="row" sx={{ fontWeight: 600 }}>{truth}</TableCell>
              {SYSTEM_OUTCOMES.map((outcome) => {
                const cell = m.cells.find((c) => c.truth === truth && c.outcome === outcome)!
                const tint = cell.applications ? verdictColor(cell.verdict) : null
                return (
                  <TableCell key={outcome} align="center" data-verdict={cell.applications ? cell.verdict : undefined}
                    sx={{ bgcolor: tint ? alpha(tint, 0.2) : undefined, borderLeft: 2, borderColor: 'background.paper',
                      fontVariantNumeric: 'tabular-nums' }}>
                    <Typography component="span" sx={{ fontSize: '1.25rem', fontWeight: 650, display: 'block' }}>
                      {cell.applications}
                    </Typography>
                    {cell.applications > 0 && cell.verdict && (
                      <Typography component="span" variant="caption" sx={{ display: 'block', lineHeight: 1.2 }}>
                        {cell.verdict.split(':')[0]}
                      </Typography>
                    )}
                  </TableCell>
                )
              })}
              <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>{m.rowTotals[truth]}</TableCell>
            </TableRow>
          ))}
          <TableRow>
            <TableCell component="th" scope="row">Total</TableCell>
            {SYSTEM_OUTCOMES.map((o) => <TableCell key={o} align="center">{m.columnTotals[o]}</TableCell>)}
            <TableCell align="right" sx={{ fontWeight: 650 }}>{m.total}</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </TableContainer>
  )
}

/** Decision reasons as a bar list: the reasons are long sentences, which a chart axis would cut short ("…"); here
 *  each label wraps freely (beside its bar, or above it on a phone). Bars are drawn from one baseline, to scale. */
function ReasonList({ reasons, effects }: { reasons: ReturnType<typeof reasonFrequencies>; effects: string[] }) {
  const max = Math.max(...reasons.map((r) => r.cases))
  return (
    <Box>
      <Legend items={effects.map((e) => ({ label: e, color: EFFECT_COLORS[e] }))} />
      <Box component="ul" aria-label="Cases per decision reason" data-testid="reason-list" sx={{ listStyle: 'none', p: 0, m: 0 }}>
        {reasons.map((r) => (
          <Tooltip key={r.reason} placement="top-start" disableInteractive
            title={`${r.reason}: ${cases(r.cases)}. Effect: ${r.effect}. Raised by: ${r.raisedBy || '–'}.`}>
            <Box component="li" sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'minmax(0, 2fr) minmax(0, 3fr)' },
              columnGap: 2, alignItems: 'center', py: 0.5, px: 0.5, borderRadius: 1, '&:hover': { bgcolor: 'action.hover' } }}>
              <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.3 }}>
                {r.reason}<Box component="span" sx={visuallyHidden}>, effect {r.effect}:</Box>
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, borderLeft: 1, borderColor: '#c3c2b7', minHeight: 20 }}>
                <Box sx={{ width: `${(r.cases / max) * 85}%`, minWidth: 3, height: 14, bgcolor: EFFECT_COLORS[r.effect] ?? '#a8a7a0',
                  borderRadius: '0 4px 4px 0' }} />
                <Typography variant="body2" sx={{ fontVariantNumeric: 'tabular-nums' }}>{r.cases}</Typography>
              </Box>
            </Box>
          </Tooltip>
        ))}
      </Box>
    </Box>
  )
}

export function RiskFraudTab({ rows, noReason }: { rows: RiskFraudRow[]; noReason: string }) {
  const kpis = riskKpis(rows)
  const reasons = reasonFrequencies(rows, noReason)
  const effects = EFFECTS.filter((e) => reasons.some((r) => r.effect === e))
  const distribution = riskScoreDistribution(rows)
  const agreement = officerAgreement(rows)
  const matrix = confusionMatrix(rows)
  const high = agreement.find((a) => a.riskLevel === 'High')!
  const medium = agreement.find((a) => a.riskLevel === 'Medium')!
  const empty = caseRows(rows).length === 0

  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 6, sm: 4, md: 2.4 }}>
        <KpiTile label="Fraud caught" value={`${kpis.fraudCaught.hits} of ${kpis.fraudCaught.total}`}
          detail={`${percent(kpis.fraudCaught.rate)} of frauds and mismatches not auto-approved`} />
      </Grid>
      <Grid size={{ xs: 6, sm: 4, md: 2.4 }}>
        <KpiTile label="Missed frauds" value={String(kpis.missedFrauds)} detail="auto-approved by the system" />
      </Grid>
      <Grid size={{ xs: 6, sm: 4, md: 2.4 }}>
        <KpiTile label="False alarms" value={String(kpis.falseAlarms.hits)}
          detail={`${percent(kpis.falseAlarms.rate)} of ${kpis.falseAlarms.total} legitimate sent to review`} />
      </Grid>
      <Grid size={{ xs: 6, sm: 6, md: 2.4 }}>
        <KpiTile label="Flag confirmed by officer" value={percent(kpis.flagConfirmed.rate)}
          detail={`${kpis.flagConfirmed.hits} of ${kpis.flagConfirmed.total} officer decisions were rejections`} />
      </Grid>
      <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
        <KpiTile label="Officer agrees with truth" value={percent(kpis.officerAgreesWithTruth.rate)}
          detail="simulated officer: decides from the ground truth" />
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <ChartCard title="System decision vs ground truth"
          subtitle="Read it per row: were legitimate customers approved, were frauds caught, were unusable images sent back?"
          table={{ columns: ['Ground truth', 'System decision', 'Applications', 'Verdict'],
            rows: matrix.cells.map((c) => [c.truth, c.outcome, c.applications, c.applications ? c.verdict ?? '' : '']) }}>
          {empty ? <NoData /> : <ConfusionTable rows={rows} />}
        </ChartCard>
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <ChartCard title="Officer agreement by risk level"
          subtitle={`High risk: the officer confirmed ${high.confirmed} of ${high.confirmed + high.overruled} flags ` +
            `(rejected) and overruled ${high.overruled}. Medium risk: ${medium.waiting} waiting, ` +
            `${medium.confirmed + medium.overruled} decided (the officer works the queue highest risk first).`}
          table={{ columns: ['Risk level', 'Confirmed (rejected)', 'Overruled (approved)', 'Still waiting'],
            rows: agreement.map((a) => [a.riskLevel, a.confirmed, a.overruled, a.waiting]) }}>
          {empty ? <NoData /> : (
            <BarChart {...chartBase} layout="horizontal" height={barChartHeight(agreement.length, 56) + 32}
              grid={{ vertical: true }} slotProps={{ legend: { position: { vertical: 'top', horizontal: 'start' } } }}
              yAxis={[{ scaleType: 'band', data: agreement.map((a) => a.riskLevel), width: 64, tickLabelStyle, ...thinBands }]}
              xAxis={[{ label: 'cases', tickMinStep: 1, tickLabelStyle }]}
              series={[
                { data: agreement.map((a) => a.confirmed), label: 'Officer confirmed the flag (rejected)', color: AGREEMENT_COLORS.confirmed, stack: 'a', valueFormatter: cases },
                { data: agreement.map((a) => a.overruled), label: 'Officer overruled it (approved)', color: AGREEMENT_COLORS.overruled, stack: 'a', valueFormatter: cases },
                { data: agreement.map((a) => a.waiting), label: 'Still waiting', color: AGREEMENT_COLORS.waiting, stack: 'a', valueFormatter: cases },
              ]} />
          )}
        </ChartCard>
      </Grid>

      <Grid size={{ xs: 12, md: 7 }}>
        <ChartCard title="Decision reasons"
          subtitle="Cases with each reason, grouped by its effect on the decision. A case can have several reasons."
          table={{ columns: ['Reason', 'Effect', 'Raised by', 'Cases'], rows: reasons.map((r) => [r.reason, r.effect, r.raisedBy, r.cases]) }}>
          {reasons.length === 0 ? <NoData>No decision reasons for these applications.</NoData> : (
            <ReasonList reasons={reasons} effects={effects} />
          )}
        </ChartCard>
      </Grid>

      <Grid size={{ xs: 12, md: 5 }}>
        <ChartCard title="Risk-score distribution"
          subtitle={`Applications per risk-score band, each case counted once. Auto-approvals score under 10, ` +
            `one high-risk reason gives 50. ${distribution.notScored} sent back for a new photo have no score.`}
          table={{ columns: ['Risk score', 'Applications'], rows: distribution.bands.map((b) => [b.label, b.applications]) }}>
          {empty ? <NoData /> : (
            <Box>
              <BarChart {...chartBase} height={300} hideLegend grid={{ horizontal: true }}
                xAxis={[{ scaleType: 'band', data: distribution.bands.map((b) => b.label), label: 'risk score',
                  valueFormatter: (label: string, context) => (context.location === 'tick' ? label.split('–')[0] : `risk score ${label}`),
                  tickLabelStyle, categoryGapRatio: 0.3 }]}
                yAxis={[{ label: 'applications', tickMinStep: 1, tickLabelStyle, width: 48 }]}
                series={[{ data: distribution.bands.map((b) => b.applications), label: 'Applications', color: MEASURE,
                  valueFormatter: (v) => (v === null ? '' : `${v} application${v === 1 ? '' : 's'}`) }]} />
            </Box>
          )}
        </ChartCard>
      </Grid>
    </Grid>
  )
}
