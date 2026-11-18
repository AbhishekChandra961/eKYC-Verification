import { LinearProgress } from '@mui/material'
import { lazy, Suspense } from 'react'
import { Navigate, Outlet, Route, Routes } from 'react-router'
import { useAuth } from './auth/AuthContext'
import { RequireRole } from './auth/RequireRole'
import { homeFor } from './auth/session'
import { AppShell } from './components/AppShell'
import { LoginPage } from './pages/LoginPage'
import { NotFound } from './pages/NotFound'

// Each portal's pages are loaded on demand (code splitting): a customer's browser never downloads the officer code.
const MyApplications = lazy(() => import('./customer/MyApplications').then((m) => ({ default: m.MyApplications })))
const KycWizard = lazy(() => import('./customer/KycWizard').then((m) => ({ default: m.KycWizard })))
const StatusPage = lazy(() => import('./customer/StatusPage').then((m) => ({ default: m.StatusPage })))
const CaseQueue = lazy(() => import('./officer/CaseQueue').then((m) => ({ default: m.CaseQueue })))
const CaseDetailPage = lazy(() => import('./officer/CaseDetailPage').then((m) => ({ default: m.CaseDetailPage })))

function Portal({ allow }: { allow: 'CUSTOMER' | 'OFFICER' }) {
  return (
    <RequireRole allow={allow}>
      <Suspense fallback={<LinearProgress aria-label="Loading the page" />}><Outlet /></Suspense>
    </RequireRole>
  )
}

function Home() {
  const { session } = useAuth()
  return <Navigate to={session ? homeFor(session.role) : '/login'} replace />
}

/** Two portals in one app: /customer/* for customers and /officer/* for compliance officers. */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
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
        </Route>
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
