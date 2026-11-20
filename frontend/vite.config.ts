import react from '@vitejs/plugin-react'
import { loadEnv, type Plugin } from 'vite'
import { defineConfig } from 'vitest/config'

/** A normal build must not even LOAD the demo data (src/demo/data.ts): its code is removed anyway (__DEMO_MODE__ is
 *  false), but Vite copies the images a loaded module imports into dist/ before unused code is dropped. Outside demo
 *  mode, that one import is replaced by an empty module. */
function withoutDemoData(): Plugin {
  const empty = '\0ekyc-demo-data-disabled'
  return {
    name: 'ekyc-without-demo-data',
    enforce: 'pre',
    resolveId: (source, importer) =>
      source === './data' && importer?.replaceAll('\\', '/').endsWith('/src/demo/client.ts') ? empty : null,
    load: (id) => (id === empty ? 'export const demoData = null' : null),
  }
}

// Dev server on 5173: the only origin the API allows (CORS). Vitest runs component tests in jsdom.
// Demo mode (Phase 11): VITE_DEMO_MODE=true (set by `--mode demo` through .env.demo, or in the environment) builds the
// static demo site for GitHub Pages into dist-demo/, served under the repository's path (/eKYC-Verification/).
export default defineConfig(({ mode, command }) => {
  const env = loadEnv(mode, import.meta.dirname, 'VITE_') // .env, .env.[mode] and VITE_* environment variables
  const demo = env.VITE_DEMO_MODE === 'true'
  return {
    plugins: [react(), ...(command === 'build' && !demo ? [withoutDemoData()] : [])],
    base: demo ? env.VITE_DEMO_BASE || '/eKYC-Verification/' : '/',
    // a literal true/false in the code, so a normal build drops every demo branch and module
    define: { __DEMO_MODE__: JSON.stringify(demo) },
    build: demo ? { outDir: 'dist-demo' } : {},
    server: { port: 5173, strictPort: true },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      css: false,
    },
  }
})
