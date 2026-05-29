import { useCallback, useEffect, useRef, useState } from "react";
import { cmd, CmdError, type BackendEvent } from "@/lib/ipc";

interface CmdState<T> {
  data: T | null;
  loading: boolean;
  error: CmdError | null;
}

/** Imperative command runner with loading/error state. */
export function usePythonCmd<T = unknown>() {
  const [state, setState] = useState<CmdState<T>>({ data: null, loading: false, error: null });
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  const run = useCallback(async (type: string, payload?: unknown): Promise<T> => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await cmd<T>(type, payload);
      if (mounted.current) setState({ data, loading: false, error: null });
      return data;
    } catch (err) {
      const e = err instanceof CmdError ? err : new CmdError("error", String(err));
      if (mounted.current) setState((s) => ({ ...s, loading: false, error: e }));
      throw e;
    }
  }, []);

  return { ...state, run };
}

/** Subscribe to streaming backend events, optionally filtered by request id. */
export function useBackendEvents(
  handler: (event: BackendEvent) => void,
  filterId?: string | null,
): void {
  const cb = useRef(handler);
  cb.current = handler;
  useEffect(() => {
    return window.conxa.onEvent((event) => {
      if (filterId != null && event.id !== filterId) return;
      cb.current(event);
    });
  }, [filterId]);
}
