// Self-host Monaco (STATUS §E W02). Without this, @monaco-editor/react's loader
// fetches the editor from jsdelivr at runtime — a timed, proctored sitting went
// blank behind a corporate proxy or CSP, and the version pin lived outside the
// lockfile. Imported once from main.tsx so every <Editor> shares one instance;
// Vite splits it into its own long-cached chunk (vite.config.ts).
//
// Only the editor core plus the syntax definitions for the languages the
// platform offers are bundled (Monarch tokenizers — no language-service
// workers), which keeps the chunk a fraction of the full distribution. The
// subpath imports are declared for TypeScript in vite-env.d.ts.
import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import 'monaco-editor/esm/vs/basic-languages/python/python.contribution'
import 'monaco-editor/esm/vs/basic-languages/javascript/javascript.contribution'
import 'monaco-editor/esm/vs/basic-languages/java/java.contribution'
import 'monaco-editor/esm/vs/basic-languages/cpp/cpp.contribution'
import 'monaco-editor/esm/vs/basic-languages/go/go.contribution'
import 'monaco-editor/esm/vs/basic-languages/rust/rust.contribution'
import 'monaco-editor/esm/vs/basic-languages/ruby/ruby.contribution'

self.MonacoEnvironment = {
  getWorker: () => new EditorWorker(),
}

loader.config({ monaco })
