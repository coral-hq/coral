import { useEffect, useRef, useState } from "react";
import { Editor, type OnMount } from "@monaco-editor/react";
import { Spinner } from "@/components/ui/spinner";
import { useResolvedThemeMode } from "@/components/theme/useResolvedThemeMode";
import {
  ensureLanguage,
  ensureMonacoReady,
  monaco,
  monacoLanguageId,
  resolvedThemeToMonaco,
} from "@/shell/monacoSetup";
import type { EditorMarker } from "./markers";

const MARKER_OWNER = "coral-validate";

export interface YamlPaneProps {
  value: string;
  onChange: (value: string) => void;
  markers: EditorMarker[];
}

/** YAML editor with server-validation markers; uses the shared Monaco seam, not the session editor. */
export function YamlPane({ value, onChange, markers }: YamlPaneProps) {
  const theme = resolvedThemeToMonaco(useResolvedThemeMode());
  const [ready, setReady] = useState(false);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void ensureMonacoReady()
      .then(() => ensureLanguage("yaml"))
      .then(() => {
        if (!cancelled) setReady(true);
      })
      // Highlighting is cosmetic; the editor still works without it.
      .catch(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const model = editorRef.current?.getModel();
    if (model) monaco.editor.setModelMarkers(model, MARKER_OWNER, markers);
  }, [markers, mounted]);

  if (!ready) {
    return (
      <div className="flex size-full items-center justify-center">
        <Spinner className="size-5 text-muted-foreground" aria-label="Loading editor" />
      </div>
    );
  }

  return (
    <div className="size-full" data-testid="yaml-pane">
      <Editor
        value={value}
        language={monacoLanguageId("yaml")}
        theme={theme}
        onChange={(next) => onChange(next ?? "")}
        onMount={(editor) => {
          editorRef.current = editor;
          setMounted(true);
        }}
        options={{ minimap: { enabled: false }, scrollBeyondLastLine: false, tabSize: 2 }}
      />
    </div>
  );
}
