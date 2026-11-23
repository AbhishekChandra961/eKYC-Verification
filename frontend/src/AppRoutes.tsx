import { LinearProgress } from '@mui/material'
import { lazy, Suspense, type ReactNode } from 'react'
import { BrowserRouter, HashRouter, Navigate, Outlet, Route, Routes } from 'react-router'
import { useAuth } from './auth/AuthContext'
import { RequireRole } from './auth/RequireRole'
import { homeFor } from './auth/session'
import { AppShell } from './components/AppShell'
import { DemoLoginPage } from './demo/DemoLoginPage'
import { LoginPage } from './pages/LoginPage'
import { MotionLevelContext } from './motion/motionLevel'
import { NotFound } from './pages/NotFound'

// Each portal's pages are loaded on demand (code splitting): a customer's browser never downloads the officer code.
const MyApplications = lazy(() => import('./customer/MyApplications').then((m) => ({ default: m.MyApplications })))
const KycWizard = lazy(() => import('./customer/KycWizard').then((m) => ({ default: m.KycWizard })))
const StatusPage = lazy(() => import('./customer/StatusPage').then((m) => ({ default: m.StatusPage })))
const CaseQueue = lazy(() => import('./officer/CaseQueue').then((m) => ({ default: m.CaseQueue })))
const CaseDetailPage = lazy(() => import('./officer/CaseDetailPage').then((m) => ({ default: m.CaseDetailPage })))
// the analytics dashboards (Phase 12): their chart library and data load only when a dashboard is opened
const DashboardsPage = lazy(() => import('./dashboards/DashboardsPage').then((m) => ({ default: m.DashboardsPage })))
// demo site only (Phase 13): the smart selfie camera, running in the browser with nothing uploaded
const CameraCheckPage = lazy(() => import('./demo/CameraCheckPage').then((m) => ({ default: m.CameraCheckPage })))

const loading = <LinearProgress aria-label="Loading the page" />

function Portal({ allow }: { allow: 'CUSTOMER' | 'OFFICER' }) {
  return (
    <RequireRole allow={allow}>
      {/* Phase 14: the officer portal is a work tool, so its motion is restrained (hover lifts, no tilt) */}
      <MotionLevelContext.Provider value={allow === 'OFFICER' ? 'restrained' : 'full'}>
        <Suspense fallback={loading}><Outlet /></Suspense>
      </MotionLevelContext.Provider>
    </RequireRole>
  )
}

function Home() {
  const { session } = useAuth()
  return <Navigate to={session ? homeFor(session.role) : '/login'} replace />
}

/** The static demo site (GitHub Pages) can only serve files, so it uses hash URLs (.../#/officer): a reload or a shared
 *  link never asks the server for a path it does not have. The real app keeps normal URLs. */
export function AppRouter({ children }: { children: ReactNode }) {
  return __DEMO_MODE__ ? <HashRouter>{children}</HashRouter> : <BrowserRouter>{children}</BrowserRouter>
}

/** Two portals in one app: /customer/* for customers and /officer/* for compliance officers (with the analytics
 *  dashboards at /officer/analytics). The demo site also serves the dashboards publicly at /dashboards. */
export function AppRoutes() {
  return (
    <Routes>
      {/* demo mode: one-click logins and project links instead of the password form */}
      <Route path="/login" element={__DEMO_MODE__ ? <DemoLoginPage /> : <LoginPage />} />
      <Route element={<AppShell />}>
        <Route index element={<Home />} />
        <Route path="customer" element={<Portal allow="CUSTOMER" />}>
          <Route index element={<MyApplications />} />
          <Route path="verify" element={<KycWizard />} />
          <Route path="applications/:applicationId" element={<StatusPage />} />
        </Route>
        <Route path="officer" element={<Portal allow="OFFICER" />}>
          <Route index element={<CaseQueue />} />
          <Route path="cases/:applicationId" element={<CaseDetailPage />} />
          <Route path="analytics/:tab?" element={<DashboardsPage basePath="/officer/analytics" />} />
        </Route>
        {/* demo site only: the dashboards are public (no login), linked from the landing page */}
        {__DEMO_MODE__ && (
          <Route path="dashboards/:tab?"
            element={<Suspense fallback={loading}><DashboardsPage basePath="/dashboards" /></Suspense>} />
        )}
        {__DEMO_MODE__ && (
          <Route path="camera-check" element={<Suspense fallback={loading}><CameraCheckPage /></Suspense>} />
        )}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
