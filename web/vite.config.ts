/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The policy pages import `docs/*.md?raw` (X04), which sits above this
    // package. Vite's dev server refuses to read outside its root unless told
    // otherwise — without this the documents build fine but 403 under `npm run
    // dev` and fail to resolve under vitest, so the failure only appears where
    // it is least expected. Scoped to the repository, which the dev server is
    // already serving from.
    fs: { allow: ['..'] },
    // Bind IPv4 loopback explicitly. Vite's default host is "localhost", which
    // Node 17+ resolves with verbatim DNS ordering — on macOS that puts ::1
    // first, so the dev server listens on [::1]:5173 ONLY. Every link the API
    // mints (FRONTEND_BASE_URL defaults to http://127.0.0.1:5173) then points at
    // a port with nothing on it: that is why invite links arrived dead.
    //
    // Reaching for the other spelling — browsing localhost:5173 — is worse than
    // the dead link rather than a fix, because "localhost" and "127.0.0.1" are
    // different SITES to a browser. The SameSite=lax refresh cookie is then
    // neither stored nor sent, so the session quietly stops surviving a reload
    // while everything still looks signed in. 127.0.0.1 is the one spelling the
    // whole system already agrees on: the agent's SSRF guard rejects a
    // callback_url host of exactly "localhost", so the platform cannot move.
    host: '127.0.0.1',
    port: 5173,
    // Fail loudly on a busy port instead of drifting to 5174 and serving an app
    // that every minted link still points away from.
    strictPort: true,
  },
  build: {
    rollupOptions: {
      output: {
        // Monaco is self-hosted (src/monaco-setup.ts) and is by far the largest
        // dependency; keep it in its own long-cached chunk so an app change
        // doesn't invalidate it, and so the main chunk stays small.
        manualChunks: (id) => (id.includes('node_modules/monaco-editor') ? 'monaco' : undefined),
      },
    },
    // The monaco chunk alone is ~3.7 MB minified / ~0.9 MB gzipped by design
    // (see above); the default 500 kB warning would fire on every build and
    // teach people to ignore it. Anything else growing past this still warns.
    chunkSizeWarningLimit: 4000,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Playwright specs live under e2e/ and must not be run by vitest.
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
