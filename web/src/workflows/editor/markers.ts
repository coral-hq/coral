import type { ProblemSeverity, SourceRange, ValidateResponse } from "../api/workflowTypes";

// monaco.MarkerSeverity values; avoids importing monaco into pure code.
export const MARKER_SEVERITY = { warning: 4, error: 8 } as const;

export interface EditorMarker {
  startLineNumber: number;
  startColumn: number;
  endLineNumber: number;
  endColumn: number;
  message: string;
  severity: number;
}

export interface Diagnostic {
  key: string;
  severity: ProblemSeverity;
  message: string;
  rule: string | null;
  range: SourceRange | null;
}

/** Problems and load issues from one validate response, in display order. */
export function diagnosticsFromValidate(response: ValidateResponse | null): Diagnostic[] {
  if (!response) return [];
  if (response.load_error) {
    const { load_error: error } = response;
    const issues = error.issues.length
      ? error.issues
      : [{ yaml_path: error.yaml_path, range: error.range, message: error.message }];
    return issues.map((issue, index) => ({
      key: `load:${error.code}:${index}`,
      severity: "error",
      message: issue.message,
      rule: null,
      range: issue.range,
    }));
  }
  return (response.problems ?? []).map((problem, index) => ({
    key: `${problem.rule}:${index}`,
    severity: problem.severity,
    message: problem.message,
    rule: problem.rule,
    range: problem.range,
  }));
}

/** Range-less diagnostics have nowhere to draw and stay list-only. */
export function markersFromDiagnostics(diagnostics: Diagnostic[]): EditorMarker[] {
  return diagnostics.flatMap((diagnostic) =>
    diagnostic.range
      ? [
          {
            startLineNumber: diagnostic.range.start_line,
            startColumn: diagnostic.range.start_column,
            endLineNumber: diagnostic.range.end_line,
            endColumn: diagnostic.range.end_column,
            message: diagnostic.rule
              ? `${diagnostic.rule}: ${diagnostic.message}`
              : diagnostic.message,
            severity: MARKER_SEVERITY[diagnostic.severity],
          },
        ]
      : [],
  );
}
