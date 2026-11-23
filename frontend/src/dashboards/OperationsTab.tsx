// Dashboard 1, Operations: how much work the system does, and how fast (the Phase 9 batch).
import { Grid, useMediaQuery, useTheme } from '@mui/material'
import { BarChart } from '@mui/x-charts/BarChart'
import { barChartHeight, chartBase, thinBands, tickLabelStyle, withHeadroom } from './chartStyle'
import { ChartCard, KpiTile, NoData } from './DashboardParts'
import { percent, seconds } from './format'
import { LATENCY_COLORS, MEASURE, OUTCOME_COLORS, RISK_COLORS } from './palette'
import type { OperationsRow } from './snapshot'
import {
  SYSTEM_OUTCOMES, funnel, latencyByCheck, operationsKpis, outcomesByDocType, queueAge,
} from './transforms'

// funnel stage names short enough for a phone's axis
const SHORT_STAGES: Record<string, string> = {
  'Decided by the system': 'System decided', 'Sent to an officer': 'To an officer',
  'Decided by an officer': 'Officer decided', 'Rejected by an officer': 'Officer rejected',
}

const count = (v: number | null) => (v === null ? '' : `${v} application${v === 1 ? '' : 's'}`)

export function OperationsTab({ rows, funnelStages, dataAsOf }: { rows: OperationsRow[]; funnelStages: string[]; dataAsOf: string }) {
  const theme = useTheme()
  const narrow = useMediaQuery(theme.breakpoints.down('sm'))
  const kpis = operationsKpis(rows)
  const stages = funnel(rows, funnelStages)
  const byType = outcomesByDocType(rows)
  const latency = latencyByCheck(rows)
  const queue = queueAge(rows)
  const queueLevels = Object.keys(RISK_COLORS).filter((level) => queue.some((q) => q.riskLevel === level))
  const rateTile = (label: string, s: typeof kpis.autoApproval) =>
    <KpiTile label={label} value={percent(s.rate)} detail={`${s.hits} of ${s.total} applications`} />

  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 6, sm: 4, md: 2.4 }}>
        <KpiTile label="Applications" value={String(kpis.applications)} detail="in the batch" />
      </Grid>
      <Grid size={{ xs: 6, sm: 4, md: 2.4 }}>{rateTile('Auto-approval rate', kpis.autoApproval)}</Grid>
      <Grid size={{ xs: 6, sm: 4, md: 2.4 }}>{rateTile('Manual-review rate', kpis.manualReview)}</Grid>
      <Grid size={{ xs: 6, sm: 6, md: 2.4 }}>{rateTile('Resubmit rate', kpis.resubmit)}</Grid>
      <Grid size={{ xs: 12, sm: 6, md: 2.4 }}>
        <KpiTile label="Median time to decision" value={seconds(kpis.medianTimeToDecisionS)}
          detail="submission to system decision" />
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <ChartCard title="Outcome funnel" subtitle="Applications reaching each stage, from submission to an officer's rejection."
          table={{ columns: ['Stage', 'Applications'], rows: stages.map((s) => [s.stage, s.applications]) }}>
          {kpis.applications === 0 ? <NoData /> : (
            <BarChart {...chartBase} layout="horizontal" height={barChartHeight(stages.length)} hideLegend
              grid={{ vertical: true }} margin={{ right: 40 }}
              yAxis={[{ scaleType: 'band', data: stages.map((s) => s.stage), width: narrow ? 104 : 150, tickLabelStyle, ...thinBands,
                valueFormatter: (stage: string, context) => (narrow && context.location === 'tick' ? SHORT_STAGES[stage] ?? stage : stage) }]}
              xAxis={[{ tickMinStep: 1, max: withHeadroom(stages.map((s) => s.applications), narrow ? 0.3 : 0.15), tickLabelStyle }]}
              series={[{ data: stages.map((s) => s.applications), label: 'Applications', color: MEASURE,
                barLabel: 'value', barLabelPlacement: 'outside', valueFormatter: count }]} />
          )}
        </ChartCard>
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <ChartCard title="Processing time per check"
          subtitle="Seconds per worker: median and 95th percentile. The field extraction (a local vision LLM) dominates."
          table={{ columns: ['Check', 'Median (s)', '95th percentile (s)', 'Runs'],
            rows: latency.map((l) => [l.check, seconds(l.medianS), seconds(l.p95S), l.runs]) }}>
          {kpis.applications === 0 ? <NoData /> : (
            <BarChart {...chartBase} layout="horizontal" height={barChartHeight(latency.length, 48) + 32}
              grid={{ vertical: true }} margin={{ right: 48 }}
              slotProps={{ legend: { position: { vertical: 'top', horizontal: 'start' } } }}
              yAxis={[{ scaleType: 'band', data: latency.map((l) => l.check), width: narrow ? 100 : 120, tickLabelStyle, ...thinBands }]}
              xAxis={[{ label: 'seconds', max: withHeadroom(latency.map((l) => l.p95S), narrow ? 0.45 : 0.25), tickLabelStyle }]}
              series={[
                { data: latency.map((l) => l.medianS), label: 'Median', color: LATENCY_COLORS.median,
                  barLabel: (item) => seconds(item.value), barLabelPlacement: 'outside', valueFormatter: (v) => seconds(v) },
                { data: latency.map((l) => l.p95S), label: '95th percentile', color: LATENCY_COLORS.p95,
                  barLabel: (item) => seconds(item.value), barLabelPlacement: 'outside', valueFormatter: (v) => seconds(v) },
              ]} />
          )}
        </ChartCard>
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <ChartCard title="Outcomes by document type" subtitle="The system's decision per document type, the busiest first."
          table={{ columns: ['Document type', ...SYSTEM_OUTCOMES, 'Total'],
            rows: byType.map((t) => [t.docType, ...SYSTEM_OUTCOMES.map((o) => t[o]), t.total]) }}>
          {byType.length === 0 ? <NoData /> : (
            <BarChart {...chartBase} layout="horizontal" height={barChartHeight(byType.length, 28) + 32}
              grid={{ vertical: true }} slotProps={{ legend: { position: { vertical: 'top', horizontal: 'start' } } }}
              yAxis={[{ scaleType: 'band', data: byType.map((t) => t.docType), width: narrow ? 150 : 170, tickLabelStyle, ...thinBands,
                valueFormatter: (type: string, context) => (narrow && context.location === 'tick' ? type.replace(' internal ', ' int. ') : type) }]}
              xAxis={[{ tickMinStep: 1, tickLabelStyle }]}
              series={SYSTEM_OUTCOMES.map((o) => ({ data: byType.map((t) => t[o]), label: o, color: OUTCOME_COLORS[o],
                stack: 'outcome', valueFormatter: count }))} />
          )}
        </ChartCard>
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <ChartCard title="Officer queue age"
          subtitle={`Cases waiting for an officer: minutes since the system decision, as of the latest recorded event (${dataAsOf}).`}
          table={{ columns: ['Case', 'Risk level', 'Waiting (min)'], rows: queue.map((q) => [q.case, q.riskLevel, q.minutes]) }}>
          {queue.length === 0 ? <NoData>No case is waiting for an officer.</NoData> : (
            <BarChart {...chartBase} layout="horizontal" height={barChartHeight(queue.length, 22) + 32}
              grid={{ vertical: true }} margin={{ right: 16 }}
              slotProps={{ legend: { position: { vertical: 'top', horizontal: 'start' } } }}
              yAxis={[{ scaleType: 'band', data: queue.map((q) => q.case), width: 56, tickLabelStyle, categoryGapRatio: 0.3 }]}
              xAxis={[{ label: 'minutes waiting', tickLabelStyle }]}
              series={queueLevels.map((level) => ({
                data: queue.map((q) => (q.riskLevel === level ? q.minutes : null)), label: `${level} risk`,
                color: RISK_COLORS[level], stack: 'queue', valueFormatter: (v: number | null) => (v === null ? null : `${v} min`),
              }))} />
          )}
        </ChartCard>
      </Grid>
    </Grid>
  )
}
