// The building blocks of the three dashboards: the "data as of" line, KPI tiles, chart cards (each with a table
// view, so no value is readable only by hovering), and the filter row.
import InsightsOutlinedIcon from '@mui/icons-material/InsightsOutlined'
import ScienceOutlinedIcon from '@mui/icons-material/ScienceOutlined'
import TableRowsOutlinedIcon from '@mui/icons-material/TableRowsOutlined'
import UpdateIcon from '@mui/icons-material/Update'
import {
  Box, Button, Chip, Collapse, FormControl, InputLabel, MenuItem, Paper, Select, Stack, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Typography,
} from '@mui/material'
import { useId, useState, type ReactNode } from 'react'
import { useTilt } from '../motion/useTilt'
import { formatDataAsOf } from './format'
import type { Filters } from './transforms'

/** Shown at the top of every dashboard: the data is synthetic, a fixed batch snapshot, and as of when. */
export function DashboardMeta({ dataAsOf, synthetic }: { dataAsOf: string; synthetic: boolean }) {
  return (
    <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }} data-testid="dashboard-meta">
      {synthetic && <Chip size="small" icon={<ScienceOutlinedIcon />} label="Synthetic data" variant="outlined" />}
      <Chip size="small" icon={<InsightsOutlinedIcon />} label="Batch snapshot" variant="outlined" />
      <Chip size="small" icon={<UpdateIcon />} label={`Data as of ${formatDataAsOf(dataAsOf)}`} variant="outlined" />
    </Stack>
  )
}

export function KpiTile({ label, value, detail }: { label: string; value: string; detail?: string }) {
  const tilt = useTilt<HTMLDivElement>()
  return (
    <Paper ref={tilt} className="ekyc-lift" sx={{ p: 2, height: '100%' }} data-testid="kpi">
      <Typography variant="body2" color="text.secondary" component="h3">{label}</Typography>
      <Typography sx={{ fontSize: '1.75rem', fontWeight: 650, color: 'primary.main', lineHeight: 1.3 }}>{value}</Typography>
      {detail && <Typography variant="caption" color="text.secondary">{detail}</Typography>}
    </Paper>
  )
}

export interface TableView {
  columns: string[]
  rows: (string | number)[][]
}

/** A chart with its title, a one-line reading guide, and a "Table" button that shows the same numbers as a table. */
export function ChartCard({ title, subtitle, table, children, footer }: {
  title: string; subtitle?: ReactNode; table: TableView; children: ReactNode; footer?: ReactNode
}) {
  const id = useId()
  const [showTable, setShowTable] = useState(false)
  return (
    <Paper component="section" aria-labelledby={`${id}-title`} sx={{ p: 2, height: '100%', minWidth: 0 }} data-testid="chart-card">
      <Stack direction="row" spacing={1} sx={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="h3" id={`${id}-title`}>{title}</Typography>
          {subtitle && <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{subtitle}</Typography>}
        </Box>
        <Button size="small" startIcon={<TableRowsOutlinedIcon />} aria-expanded={showTable} aria-controls={`${id}-table`}
          onClick={() => setShowTable((shown) => !shown)} sx={{ flexShrink: 0 }}>
          {showTable ? 'Hide table' : 'Table'}
        </Button>
      </Stack>
      <Box sx={{ mt: 1 }}>{children}</Box>
      {footer}
      <Collapse in={showTable} id={`${id}-table`}>
        <TableContainer sx={{ mt: 1, maxHeight: 360 }}>
          <Table size="small" stickyHeader aria-label={`${title}: data`}>
            <TableHead>
              <TableRow>{table.columns.map((c) => <TableCell key={c}>{c}</TableCell>)}</TableRow>
            </TableHead>
            <TableBody>
              {table.rows.map((row, i) => (
                <TableRow key={i}>
                  {row.map((value, j) => (
                    <TableCell key={j} align={typeof value === 'number' ? 'right' : 'left'}
                      sx={{ fontVariantNumeric: 'tabular-nums' }}>{value}</TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Collapse>
    </Paper>
  )
}

/** The filters of a batch dashboard, in one row above its charts; they apply to every chart of the dashboard. */
export function FilterBar({ filters, onChange, docTypes, outcomes, shown, total }: {
  filters: Filters; onChange: (next: Filters) => void; docTypes: string[]; outcomes: string[]; shown: number; total: number
}) {
  const filtered = filters.docType !== null || filters.outcome !== null
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ alignItems: { sm: 'center' } }} data-testid="filter-bar">
      <FormControl size="small" sx={{ minWidth: 220 }}>
        <InputLabel id="dash-doc-type-label" shrink>Document type</InputLabel>
        <Select labelId="dash-doc-type-label" label="Document type" value={filters.docType ?? ''} displayEmpty notched
          onChange={(e) => onChange({ ...filters, docType: e.target.value || null })}
          renderValue={(v) => v || 'All document types'}>
          <MenuItem value="">All document types</MenuItem>
          {docTypes.map((d) => <MenuItem key={d} value={d}>{d}</MenuItem>)}
        </Select>
      </FormControl>
      <FormControl size="small" sx={{ minWidth: 220 }}>
        <InputLabel id="dash-outcome-label" shrink>Outcome</InputLabel>
        <Select labelId="dash-outcome-label" label="Outcome" value={filters.outcome ?? ''} displayEmpty notched
          onChange={(e) => onChange({ ...filters, outcome: e.target.value || null })}
          renderValue={(v) => v || 'All outcomes'}>
          <MenuItem value="">All outcomes</MenuItem>
          {outcomes.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
        </Select>
      </FormControl>
      <Typography variant="body2" color="text.secondary" role="status" aria-live="polite" data-testid="filter-count">
        {shown === total ? `All ${total} applications` : `${shown} of ${total} applications`}
      </Typography>
      {filtered && <Button size="small" onClick={() => onChange({ docType: null, outcome: null })}>Clear filters</Button>}
    </Stack>
  )
}

/** Colour key for charts drawn without the chart library (a swatch beside ink-coloured text). */
export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap', mb: 1 }} aria-hidden>
      {items.map((item) => (
        <Stack key={item.label} direction="row" spacing={0.75} sx={{ alignItems: 'center' }}>
          <Box sx={{ width: 12, height: 12, borderRadius: 0.5, bgcolor: item.color }} />
          <Typography variant="body2">{item.label}</Typography>
        </Stack>
      ))}
    </Stack>
  )
}

/** A chart's place when the filters leave nothing to draw. */
export function NoData({ children = 'No applications match the filters.' }: { children?: ReactNode }) {
  return <Typography color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>{children}</Typography>
}
