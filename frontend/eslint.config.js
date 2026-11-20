// ESLint (flat config): TypeScript, React hooks (incl. the React Compiler rules), Vite fast refresh, and
// jsx-a11y for accessibility (labels, alt text, keyboard handlers).
import js from '@eslint/js'
import { defineConfig, globalIgnores } from 'eslint/config'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default defineConfig([
  globalIgnores(['dist', 'dist-demo', 'src/api/schema.d.ts', 'src/demo/fixtures', 'playwright-report', 'test-results']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
      jsxA11y.flatConfigs.recommended,
    ],
    languageOptions: { ecmaVersion: 2023, globals: globals.browser },
  },
  {
    files: ['e2e/**/*.ts', '*.config.ts', 'src/test/**/*.ts', '**/*.test.{ts,tsx}'],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
    rules: { 'react-refresh/only-export-components': 'off' },
  },
])
