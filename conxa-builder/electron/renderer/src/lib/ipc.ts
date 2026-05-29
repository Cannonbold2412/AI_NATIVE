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

declare global {
  interface Window {
    conxa: {
      cmd: <T = unknown>(type: string, payload?: unknown) => Promise<CmdResponse<T>>;
      onEvent: (handler: (event: BackendEvent) => void) => () => void;
      openExternal: (url: string) => Promise<void>;
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
