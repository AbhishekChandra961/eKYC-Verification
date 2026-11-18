// Forgery heatmap geometry. The forgery model scores overlapping 224 px tiles (stride 112) on the page resized to
// 1280 px. To draw them without stacking transparent squares, the page is cut along every tile edge into small
// cells, and each cell gets the HIGHEST score of the tiles covering it (the page score is also the highest tile).

export interface TileGridInput {
  size: number
  xy: number[][]
  scores: number[]
}

export interface HeatCell {
  x: number
  y: number
  width: number
  height: number
  score: number
}

export function heatCells(grid: TileGridInput): HeatCell[] {
  const xs = new Set<number>()
  const ys = new Set<number>()
  for (const [x, y] of grid.xy) {
    xs.add(x)
    xs.add(x + grid.size)
    ys.add(y)
    ys.add(y + grid.size)
  }
  const xEdges = [...xs].sort((a, b) => a - b)
  const yEdges = [...ys].sort((a, b) => a - b)
  const cells: HeatCell[] = []
  for (let j = 0; j < yEdges.length - 1; j++) {
    for (let i = 0; i < xEdges.length - 1; i++) {
      const cx = (xEdges[i] + xEdges[i + 1]) / 2
      const cy = (yEdges[j] + yEdges[j + 1]) / 2
      let best = -1
      grid.xy.forEach(([x, y], k) => {
        if (cx >= x && cx < x + grid.size && cy >= y && cy < y + grid.size) best = Math.max(best, grid.scores[k] ?? 0)
      })
      if (best >= 0) {
        cells.push({ x: xEdges[i], y: yEdges[j], width: xEdges[i + 1] - xEdges[i], height: yEdges[j + 1] - yEdges[j], score: best })
      }
    }
  }
  return cells
}

/** Sequential single-hue ramp (light -> dark blue), from the project's data-viz palette. */
export const HEAT_RAMP = [
  '#cde2fb', '#b7d3f6', '#9ec5f4', '#86b6ef', '#6da7ec', '#5598e7', '#3987e5',
  '#2a78d6', '#256abf', '#1c5cab', '#184f95', '#104281', '#0d366b',
] as const

export function heatColor(score: number): string {
  const index = Math.min(HEAT_RAMP.length - 1, Math.max(0, Math.floor(score * HEAT_RAMP.length)))
  return HEAT_RAMP[index]
}

/** Near-zero scores stay invisible so the document remains readable; higher scores cover more. */
export function heatOpacity(score: number): number {
  return score < 0.15 ? 0 : Math.min(0.75, 0.2 + 0.55 * score)
}

/** CSS gradient for the legend: the same colours and opacities as the overlay, from score 0 to 1. */
export function legendGradient(): string {
  const stops = Array.from({ length: 21 }, (_, i) => {
    const score = i / 20
    const hex = heatColor(score)
    const [r, g, b] = [1, 3, 5].map((p) => parseInt(hex.slice(p, p + 2), 16))
    return `rgba(${r}, ${g}, ${b}, ${heatOpacity(score)}) ${score * 100}%`
  })
  return `linear-gradient(to right, ${stops.join(', ')})`
}
