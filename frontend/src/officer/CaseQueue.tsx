import RefreshIcon from '@mui/icons-material/Refresh'
import {
  Alert, Box, Button, FormControl, InputLabel, Link, MenuItem, Paper, Select, Skeleton, Stack, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, TableSortLabel, Typography,
} from '@mui/material'
import { useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useNavigate } from 'react-router'
import { api, isAbort, messageOf, type ApplicationStatus, type CaseRow, type Outcome } from '../api/client'
import { formatDateTime, formatDuration, formatTime } from '../format'
import { OUTCOME_LABELS, RISK, STATUS_LABELS, docTypeLabel, statusLabel } from './labels'
import { sortRows, waitingMs, type SortKey } from './queue'
import { ToneChip } from './ToneChip'

const REFRESH_MS = 10_000
type StatusFilter = ApplicationStatus | 'ALL'
type OutcomeFilter = Outcome | 'ALL'

// the default view is the officer's work: cases awaiting a decision (DECIDED)
const STATUS_FILTERS: StatusFilter[] = ['DECIDED', 'PROCESSING', 'APPROVED', 'REJECTED', 'RESUBMIT_REQUESTED', 'ALL']
const OUTCOME_FILTERS: OutcomeFilter[] = ['ALL', 'MANUAL_REVIEW', 'AUTO_APPROVED', 'RESUBMIT_REQUIRED']

export function CaseQueue() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<StatusFilter>('DECIDED')
  const [outcome, setOutcome] = useState<OutcomeFilter>('ALL')
  const [sort, setSort] = useState<{ key: SortKey; direction: 'asc' | 'desc' }>({ key: 'risk_score', direction: 'desc' })
  const [rows, setRows] = useState<CaseRow[] | null>(null)
  const [loadedAt, setLoadedAt] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    const load = () => api.officerCases({ status: status === 'ALL' ? undefined : status, outcome: outcome === 'ALL' ? undefined : outcome },
      controller.signal)
      .then((next) => { setRows(next); setLoadedAt(Date.now()); setError(null) })
      .catch((err: unknown) => { if (!isAbort(err)) setError(messageOf(err)) })
    load()
    const timer = window.setInterval(load, REFRESH_MS)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [status, outcome, version])

  const sorted = useMemo(() => (rows && loadedAt ? sortRows(rows, sort.key, sort.direction, loadedAt) : []), [rows, sort, loadedAt])

  function sortBy(key: SortKey) {
    setSort((current) => ({ key, direction: current.key === key && current.direction === 'desc' ? 'asc' : 'desc' }))
  }

  const header = (key: SortKey, label: string) => (
    <TableSortLabel active={sort.key === key} direction={sort.key === key ? sort.direction : 'desc'} onClick={() => sortBy(key)}>
      {label}
    </TableSortLabel>
  )

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h1" sx={{ mb: 0.5 }}>Case queue</Typography>
        <Typography color="text.secondary">Highest risk first. Open a case to see the evidence and decide.</Typography>
      </Box>

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ alignItems: { sm: 'center' } }}>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel id="status-filter-label">Status</InputLabel>
          <Select labelId="status-filter-label" label="Status" value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
            {STATUS_FILTERS.map((s) => <MenuItem key={s} value={s}>{s === 'ALL' ? 'All statuses' : STATUS_LABELS[s]}</MenuItem>)}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel id="outcome-filter-label">System outcome</InputLabel>
          <Select labelId="outcome-filter-label" label="System outcome" value={outcome} onChange={(e) => setOutcome(e.target.value as OutcomeFilter)}>
            {OUTCOME_FILTERS.map((o) => <MenuItem key={o} value={o}>{o === 'ALL' ? 'All outcomes' : OUTCOME_LABELS[o]}</MenuItem>)}
          </Select>
        </FormControl>
        <Box sx={{ flexGrow: 1 }} />
        <Typography variant="body2" color="text.secondary" aria-live="polite">
          {loadedAt ? `${rows?.length ?? 0} cases · updated ${formatTime(new Date(loadedAt).toISOString())}` : ''}
        </Typography>
        <Button variant="outlined" startIcon={<RefreshIcon />} onClick={() => setVersion((v) => v + 1)}>Refresh</Button>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}
      {!rows && !error && <Skeleton variant="rounded" height={240} aria-label="Loading the case queue" />}
      {rows && rows.length === 0 && (
        <Paper sx={{ p: 4, textAlign: 'center' }}><Typography>No cases match these filters.</Typography></Paper>
      )}
      {rows && rows.length > 0 && (
        <TableContainer component={Paper}>
          <Table aria-label="Cases" sx={{ minWidth: 860 }}>
            <TableHead>
              <TableRow>
                <TableCell>Case</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>System outcome</TableCell>
                <TableCell>Risk</TableCell>
                <TableCell align="right" sortDirection={sort.key === 'risk_score' ? sort.direction : false}>{header('risk_score', 'Score')}</TableCell>
                <TableCell>Document</TableCell>
                <TableCell sortDirection={sort.key === 'created_at' ? sort.direction : false}>{header('created_at', 'Submitted')}</TableCell>
                <TableCell sortDirection={sort.key === 'waiting' ? sort.direction : false}>{header('waiting', 'Waiting')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sorted.map((row) => {
                const waiting = loadedAt ? waitingMs(row, loadedAt) : null
                return (
                  <TableRow key={row.application_id} hover sx={{ cursor: 'pointer' }} data-testid="case-row"
                    onClick={() => navigate(`/officer/cases/${row.application_id}`)}>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>
                      <Link component={RouterLink} to={`/officer/cases/${row.application_id}`} onClick={(e) => e.stopPropagation()}
                        sx={{ fontFamily: 'monospace' }}>
                        {row.application_id}
                      </Link>
                    </TableCell>
                    <TableCell>{statusLabel(row.status, row.outcome)}</TableCell>
                    <TableCell>{row.outcome ? OUTCOME_LABELS[row.outcome] : '–'}</TableCell>
                    <TableCell>
                      {row.risk_level ? <ToneChip tone={RISK[row.risk_level].tone} label={RISK[row.risk_level].label} />
                        : <ToneChip tone="neutral" label={row.outcome === 'RESUBMIT_REQUIRED' ? 'Retake' : 'Pending'} />}
                    </TableCell>
                    <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>
                      {row.risk_score != null ? row.risk_score.toFixed(1) : '–'}
                    </TableCell>
                    <TableCell>{docTypeLabel(row.doc_type)}</TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{formatDateTime(row.created_at)}</TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{waiting === null ? '–' : formatDuration(waiting)}</TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Stack>
  )
}
