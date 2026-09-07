/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
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
