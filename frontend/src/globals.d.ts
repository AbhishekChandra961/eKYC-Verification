// Build-time constant set in vite.config.ts (`define`): true only for the static demo build (VITE_DEMO_MODE=true).
// Code tests it directly (`if (__DEMO_MODE__)`), so a normal build removes every demo branch and module.
declare const __DEMO_MODE__: boolean
