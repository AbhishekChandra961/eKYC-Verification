// The ONLY bridge from API data to the customer's screens. It copies a fixed whitelist of fields into a new object,
// so nothing else the API might ever add can reach a customer component. Customers see the outcome in plain words
// and, for a resubmission, what to do next; never anything about how the checks scored the application.
import type { ApplicationView } from '../api/client'

export type CustomerStage = 'submitted' | 'verifying' | 'result'
export type CustomerOutcome = 'pending' | 'verified' | 'under_review' | 'resubmit' | 'not_verified'

export interface CustomerStatus {
  applicationId: string
  stage: CustomerStage
  outcome: CustomerOutcome
  title: string
  detail: string
  nextSteps: string[] // only for a resubmission: what to photograph again
  progress: { completed: number; total: number } // how many checks have finished, never what they found
  submittedAt: string
  updatedAt: string
  final: boolean // nothing will change any more
}

/** Every key a customer component can receive (the whitelist test checks this list). */
export const CUSTOMER_STATUS_KEYS: readonly (keyof CustomerStatus)[] = [
  'applicationId', 'stage', 'outcome', 'title', 'detail', 'nextSteps', 'progress', 'submittedAt', 'updatedAt', 'final',
]

const TEXT: Record<'submitted' | 'verifying' | Exclude<CustomerOutcome, 'pending'>, { title: string; detail: string }> = {
  submitted: {
    title: 'Application received',
    detail: 'We have your photos and are starting the checks.',
  },
  verifying: {
    title: 'Verifying your identity',
    detail: 'This usually takes about a minute. You can leave this page: your result will be saved under My applications.',
  },
  verified: {
    title: 'Verified',
    detail: 'Your identity has been verified. You can now continue opening your SecureBank account.',
  },
  under_review: {
    title: 'Under review by our team',
    detail: 'A member of our team will look at your application, usually within one business day. ' +
      'You do not need to do anything now.',
  },
  resubmit: {
    title: 'Please resubmit',
    detail: 'We could not complete the verification with these photos.',
  },
  not_verified: {
    title: 'We could not verify your identity',
    detail: 'Please contact SecureBank customer support, who can help you with the next steps.',
  },
}

const DEFAULT_NEXT_STEP = 'Please take new photos of your ID document and of yourself, and submit them again.'

function outcomeOf(view: ApplicationView): CustomerOutcome {
  switch (view.status) {
    case 'SUBMITTED':
    case 'PROCESSING':
      return 'pending'
    case 'APPROVED':
      return 'verified'
    case 'REJECTED':
      return 'not_verified'
    case 'RESUBMIT_REQUESTED':
      return 'resubmit'
    case 'DECIDED': // waiting for an officer
      return 'under_review'
  }
}

export function toCustomerStatus(view: ApplicationView): CustomerStatus {
  const outcome = outcomeOf(view)
  const stage: CustomerStage = view.status === 'SUBMITTED' ? 'submitted' : view.status === 'PROCESSING' ? 'verifying' : 'result'
  const text = TEXT[outcome === 'pending' ? (stage === 'submitted' ? 'submitted' : 'verifying') : outcome]
  const retake = (view.retake ?? []).filter((line): line is string => typeof line === 'string' && line.length > 0)
  const total = Math.max(1, Math.trunc(view.progress?.total ?? 1))
  return {
    applicationId: view.application_id,
    stage,
    outcome,
    title: text.title,
    detail: text.detail,
    nextSteps: outcome === 'resubmit' ? (retake.length ? retake : [DEFAULT_NEXT_STEP]) : [],
    progress: { completed: Math.min(total, Math.max(0, Math.trunc(view.progress?.completed ?? 0))), total },
    submittedAt: view.created_at,
    updatedAt: view.updated_at,
    final: outcome === 'verified' || outcome === 'not_verified' || outcome === 'resubmit',
  }
}
