import { defineConfig, configDefaults } from 'vitest/config'

// The Playwright suites are driven by their own configs, not by `vitest run`:
// tests/smoke/** by `npm run smoke` (playwright.config.ts, a running dashboard)
// and tests/browser/** by `npm run browser-verify`
// (playwright.browser.config.ts, the static front end). Playwright's test() API
// throws when collected under vitest, which fails the unit gate.
//
// patches/** holds tracked copies of foreign (non-marveen) source, e.g. a
// vendored plugin patch, see patches/telegram-plugin/README.md. Its *.test.ts
// files target that plugin's own runtime (bun:test), not vitest; collecting
// them here fails the suite before any test runs (0 tests, "Failed Suite"),
// not because the test itself is red. Exclude the whole tree: any future
// addition under patches/ is foreign by definition, not a one-off exception.
//
// Keep all vitest defaults; only carve out these directories.
export default defineConfig({
  test: {
    exclude: [...configDefaults.exclude, 'tests/smoke/**', 'tests/browser/**', 'patches/**'],
    // Hard gates, run in every worker before any test module is imported:
    //  - assert-not-live-install: refuse to run inside a live install (see that
    //    setup file's header for the 2026-07-27 incident it prevents).
    //  - assert-supported-node: refuse to run on a Node whose ABI the installed
    //    native modules were not built for, which otherwise reds out 40 files
    //    with errors that look like bugs in those files (2026-08-17).
    setupFiles: [
      './src/__tests__/setup/assert-not-live-install.ts',
      './src/__tests__/setup/assert-supported-node.ts',
    ],
  },
})
