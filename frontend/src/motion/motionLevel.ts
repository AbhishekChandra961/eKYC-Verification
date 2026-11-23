// Phase 14: how much motion a part of the app may use. The officer portal is "restrained" (hover lifts and smooth
// transitions only: no tilt, no moving backgrounds); the customer side, the landing page and the public dashboards
// are "full". Set once per portal in AppRoutes.tsx.
import { createContext, useContext } from 'react'

export type MotionLevel = 'full' | 'restrained'

export const MotionLevelContext = createContext<MotionLevel>('full')

export function useMotionLevel(): MotionLevel {
  return useContext(MotionLevelContext)
}
