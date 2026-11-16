import { useEffect, useState } from "react";
import { validateWorkflow } from "../api/client";
import type { CompiledGraph, ValidateResponse } from "../api/workflowTypes";

export const VALIDATE_DEBOUNCE_MS = 600;

export interface ValidateLoopState {
  response: ValidateResponse | null;
  /** Last successfully compiled graph; kept while the text is mid-edit and unparseable. */
  compiled: CompiledGraph | null;
  isValidating: boolean;
  error: Error | null;
}

/** Debounced server validation of `yaml`; a newer edit cancels the in-flight request. */
export function useValidateLoop(
  yaml: string,
  initialCompiled: CompiledGraph | null = null,
  debounceMs: number = VALIDATE_DEBOUNCE_MS,
): ValidateLoopState {
  const [state, setState] = useState<ValidateLoopState>({
    response: null,
    compiled: initialCompiled,
    isValidating: false,
    error: null,
  });

  useEffect(() => {
    const controller = new AbortController();
    setState((previous) => ({ ...previous, isValidating: true }));
    const timer = setTimeout(() => {
      validateWorkflow(yaml, controller.signal).then(
        (response) =>
          setState((previous) => ({
            response,
            compiled: response.compiled ?? previous.compiled,
            isValidating: false,
            error: null,
          })),
        (error: unknown) => {
          if (controller.signal.aborted) return;
          setState((previous) => ({
            ...previous,
            isValidating: false,
            error: error instanceof Error ? error : new Error(String(error)),
          }));
        },
      );
    }, debounceMs);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [yaml, debounceMs]);

  return state;
}
