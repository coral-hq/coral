import { describe, expect, it } from "vitest";
import type { ValidateResponse } from "../api/workflowTypes";
import { MARKER_SEVERITY, diagnosticsFromValidate, markersFromDiagnostics } from "./markers";

const range = { start_line: 3, start_column: 5, end_line: 3, end_column: 9 };

describe("validate markers", () => {
  it("turns problem ranges into editor markers with severity", () => {
    const response: ValidateResponse = {
      valid: true,
      runnable: false,
      problems: [
        {
          rule: "V2",
          severity: "error",
          message: "deadlock",
          node_ids: [],
          arrow_ids: [],
          yaml_path: "nodes[1]",
          range,
        },
        {
          rule: "W1",
          severity: "warning",
          message: "unused",
          node_ids: [],
          arrow_ids: [],
          yaml_path: null,
          range: null,
        },
      ],
    };
    const diagnostics = diagnosticsFromValidate(response);
    expect(diagnostics).toHaveLength(2);
    expect(markersFromDiagnostics(diagnostics)).toEqual([
      {
        startLineNumber: 3,
        startColumn: 5,
        endLineNumber: 3,
        endColumn: 9,
        message: "V2: deadlock",
        severity: MARKER_SEVERITY.error,
      },
    ]);
  });

  it("reports every load issue, or the load error itself when there are none", () => {
    const withIssues = diagnosticsFromValidate({
      valid: false,
      runnable: false,
      load_error: {
        code: "schema",
        yaml_path: "",
        range: null,
        message: "bad",
        issues: [
          { yaml_path: "a", range, message: "one" },
          { yaml_path: "b", range: null, message: "two" },
        ],
      },
    });
    expect(withIssues.map((item) => item.message)).toEqual(["one", "two"]);
    expect(markersFromDiagnostics(withIssues)).toHaveLength(1);

    const bare = diagnosticsFromValidate({
      valid: false,
      runnable: false,
      load_error: { code: "invalid_yaml", yaml_path: "", range, message: "boom", issues: [] },
    });
    expect(bare).toMatchObject([{ message: "boom", severity: "error" }]);
  });

  it("has no diagnostics before the first response", () => {
    expect(diagnosticsFromValidate(null)).toEqual([]);
  });
});
