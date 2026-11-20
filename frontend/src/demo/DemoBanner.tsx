import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { Box, Link, Typography } from '@mui/material'
import { useEffect } from 'react'
import { useLocation } from 'react-router'
import { DEMO_BANNER, DEMO_LINKS } from './config'

/** Shown on every page of the demo site, above everything else and kept in view while scrolling (README: Live demo,
 *  honesty rules). A new page starts at the top, so the banner never covers the top bar. */
export function DemoBanner() {
  const { pathname } = useLocation()
  useEffect(() => { window.scrollTo(0, 0) }, [pathname]) // braces: an effect may return only a cleanup function
  // sticky from tablet width up; on a phone it would take too much of the screen, so there it stays at the page top
  return (
    <Box component="aside" aria-label="Demo mode" data-testid="demo-banner"
      sx={{ position: { xs: 'static', sm: 'sticky' }, top: 0, zIndex: (theme) => theme.zIndex.appBar + 1,
        bgcolor: '#fff4d6', color: 'text.primary', borderBottom: 1, borderColor: '#e6c36a', px: 2, py: 1 }}>
      <Typography variant="body2" sx={{ textAlign: 'center' }}>
        <InfoOutlinedIcon fontSize="small" aria-hidden sx={{ verticalAlign: 'text-bottom', mr: 0.75 }} />
        {DEMO_BANNER}{' '}
        <Link href={DEMO_LINKS.repo} target="_blank" rel="noopener" sx={{ fontWeight: 600 }}>GitHub</Link>
      </Typography>
    </Box>
  )
}

/** Dataset credit for the sample documents shown on the demo site (SIDTD is CC BY-SA). */
export function DemoAttribution() {
  return (
    <Typography variant="caption" component="p" color="text.secondary" sx={{ mt: 0.5 }}>
      Sample documents: web copies derived from the SIDTD dataset (Boned et al., <i>Scientific Data</i> 2024, CVC-UAB;
      built on MIDV-2020), licensed{' '}
      <Link href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noopener" color="inherit">CC BY-SA 4.0</Link>.
      Synthetic documents with generated faces: no real people.
    </Typography>
  )
}
