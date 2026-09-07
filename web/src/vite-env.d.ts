/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

// monaco-editor's export map only exposes its main entry to TypeScript, but the
// ESM subpaths exist on disk and Vite resolves them fine. Declaring them here
// lets src/monaco-setup.ts bundle just the editor core + the syntax definitions
// the platform offers, instead of the full distribution with every language
// service worker (which was ~10 MB of assets).
declare module 'monaco-editor/esm/vs/editor/editor.api' {
  export * from 'monaco-editor'
}
declare module 'monaco-editor/esm/vs/basic-languages/*'
