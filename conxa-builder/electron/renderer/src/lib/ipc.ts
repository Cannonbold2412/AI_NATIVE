/** Typed wrapper over the preload `window.conxa` bridge. */

export interface CmdSuccess<T> {
  ok: true;
  result: T;
}
export interface CmdFailure {
  ok: false;
  code: string;
  message: string;
  trace?: string;
}
export type CmdResponse<T> = CmdSuccess<T> | CmdFailure;

export interface BackendEvent {
  type: "event";
  id: string | null;
  phase?: string;
  [k: string]: unknown;
}

export type UpdateStatusEvent =
  | { phase: 'download-progress'; percent: number; bytesPerSecond: number; transferred: number; total: number }
  | { phase: 'downloaded' }
  | { phase: 'error'; message: string }

export interface UpdateCheckResult {
  available: boolean;
  currentVersion: string;
  latestVersion?: string;
  error?: string;
}

declare global {
  interface Window {
    conxa: {
      isPackaged: boolean;
      cmd: <T = unknown>(type: string, payload?: unknown) => Promise<CmdResponse<T>>;
      onEvent: (handler: (event: BackendEvent) => void) => () => void;
      openExternal: (url: string) => Promise<void>;
      pickFile: (filters?: { name: string; extensions: string[] }[]) => Promise<string | null>;
      windowControls: {
        minimize: () => Promise<void>;
        toggleMaximize: () => Promise<boolean>;
        close: () => Promise<void>;
        isMaximized: () => Promise<boolean>;
        onMaximizeChange: (handler: (isMaximized: boolean) => void) => () => void;
      };
      onDeepLink: (handler: (url: string) => void) => () => void;
      update: {
        check: () => Promise<UpdateCheckResult>;
        start: () => Promise<void>;
        install: () => Promise<void>;
        getVersion: () => Promise<string>;
        onStatus: (handler: (event: UpdateStatusEvent) => void) => () => void;
      };
    };
  }
}

export class CmdError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

/** Invoke a backend command, throwing CmdError on failure. */
export async function cmd<T = unknown>(type: string, payload?: unknown): Promise<T> {
  const res = await window.conxa.cmd<T>(type, payload);
  if (!res.ok) throw new CmdError(res.code, res.message);
  return res.result;
}
