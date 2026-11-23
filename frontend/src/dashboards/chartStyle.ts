// Shared look of every chart (MUI X Charts): recessive axes and grid in the theme's muted inks, thin bars with
// 4 px rounded ends, a 2 px gap in the surface colour between touching bars, and no animation (calmer, and the
// same picture every time, e.g. for screenshots).
import { barClasses } from '@mui/x-charts/BarChart'
import { ink } from './palette'

export const tickLabelStyle = { fontSize: 12, fill: ink.secondary }

export const chartBase = {
  skipAnimation: true,
  borderRadius: 4,
  sx: {
    [`& .${barClasses.element}`]: { stroke: '#ffffff', strokeWidth: 2 }, // the surface gap
    '& .MuiChartsAxis-line, & .MuiChartsAxis-tick': { stroke: '#c3c2b7' },
    '& .MuiChartsGrid-line': { stroke: ink.grid },
  },
} as const

/** Height of a horizontal bar chart with `rows` categories: ~20 px bars, room for the value axis. */
export function barChartHeight(rows: number, rowHeight = 32): number {
  return Math.max(rows, 1) * rowHeight + 56
}

/** The value axis' upper end, with room past the longest bar for its label (the plot area clips what overflows). */
export function withHeadroom(values: (number | null)[], room = 0.15): number {
  const max = Math.max(0, ...values.filter((v): v is number => v !== null))
  return max === 0 ? 1 : max * (1 + room)
}

/** Leaves the bands' leftover as air: bars stay thin (<= 24 px) instead of filling their row. */
export const thinBands = { categoryGapRatio: 0.35, barGapRatio: 0.1 }
