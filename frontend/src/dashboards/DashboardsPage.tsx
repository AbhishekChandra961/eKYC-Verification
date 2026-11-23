// The analytics dashboards (Phase 12, replaces the Tableau workbook): three tabs over the bundled batch snapshot.
// Public on the demo site (/dashboards); in the real app, the officer portal's "Analytics" tab (/officer/analytics).
// Either way the data is the same static snapshot (snapshot.json), never live data, and it says so.
import { Box, Stack, Tab, Tabs, Typography } from '@mui/material'
import { useState } from 'react'
import { Navigate, Link as RouterLink, useParams } from 'react-router'
import { DashboardMeta, FilterBar } from './DashboardParts'
import { formatDataAsOf } from './format'
import { ModelPerformanceTab } from './ModelPerformanceTab'
import { OperationsTab } from './OperationsTab'
import { RiskFraudTab } from './RiskFraudTab'
import { snapshot } from './snapshot'
import { NO_FILTERS, applyFilters, optionsOf, type Filters } from './transforms'

const TABS = [
  { slug: '', label: 'Operations', title: 'Operations', intro: 'How much work the system does, and how fast.' },
  { slug: 'risk-fraud', label: 'Risk & fraud', title: 'Risk & fraud', intro: 'What the system flags, and whether it is right (compared with the ground truth).' },
  { slug: 'model-performance', label: 'Model performance', title: 'Model performance', intro: 'The offline evaluations of the four models.' },
] as const

// the final outcome of an application, in the order of its life cycle
const OUTCOME_ORDER = ['Auto-approved', 'Approved by officer', 'Rejected by officer', 'Awaiting officer', 'Retake requested']

export function DashboardsPage({ basePath }: { basePath: string }) {
  const { tab = '' } = useParams()
  const [filters, setFilters] = useState<Filters>(NO_FILTERS) // shared by the two batch dashboards
  const current = TABS.findIndex((t) => t.slug === tab)
  if (current < 0) return <Navigate to={basePath} replace />

  const all = snapshot.operations
  const docTypes = optionsOf(all, (r) => r.docType)
  const outcomes = optionsOf(all, (r) => r.outcome)
    .sort((a, b) => (OUTCOME_ORDER.indexOf(a) + 1 || 99) - (OUTCOME_ORDER.indexOf(b) + 1 || 99))
  const operations = applyFilters(snapshot.operations, filters)
  const riskFraud = applyFilters(snapshot.riskFraud, filters)
  const info = TABS[current]
  const panelId = 'dashboard-panel'

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h1" sx={{ mb: 0.5 }}>Analytics dashboards</Typography>
        <Typography color="text.secondary">
          A fixed snapshot of the simulated batch: {all.length} applications through the real pipeline, with ground
          truth{__DEMO_MODE__ ? '' : '. It is not live data: refresh it with scripts/export_dashboard_data.py, then scripts/export_dashboard_snapshot.py'}.
        </Typography>
      </Box>

      <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Tabs value={current} variant="scrollable" allowScrollButtonsMobile aria-label="Dashboards">
          {TABS.map((t, i) => (
            <Tab key={t.slug} value={i} label={t.label} component={RouterLink} to={t.slug ? `${basePath}/${t.slug}` : basePath}
              id={`dashboard-tab-${i}`} aria-controls={panelId} />
          ))}
        </Tabs>
      </Box>

      <Stack key={current} className="ekyc-fade-up" spacing={2} role="tabpanel" id={panelId}
        aria-labelledby={`dashboard-tab-${current}`} data-testid={`dashboard-${info.slug || 'operations'}`}>
        <Box>
          <Typography variant="h2">{info.title}</Typography>
          <Typography color="text.secondary" sx={{ mb: 1 }}>{info.intro}</Typography>
          <DashboardMeta dataAsOf={snapshot.dataAsOf} synthetic={snapshot.synthetic} />
        </Box>
        {current < 2 && (
          <FilterBar filters={filters} onChange={setFilters} docTypes={docTypes} outcomes={outcomes}
            shown={operations.length} total={all.length} />
        )}
        {current === 0 && <OperationsTab rows={operations} funnelStages={snapshot.funnelStages} dataAsOf={formatDataAsOf(snapshot.dataAsOf)} />}
        {current === 1 && <RiskFraudTab rows={riskFraud} noReason={snapshot.noReason} />}
        {current === 2 && <ModelPerformanceTab rows={snapshot.modelPerformance} />}
      </Stack>
    </Stack>
  )
}
