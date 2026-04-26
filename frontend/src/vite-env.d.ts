/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API origin without trailing slash; empty string uses same origin / dev proxy */
  readonly VITE_API_BASE_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
