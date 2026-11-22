import { Navigate, Route, Routes } from "react-router-dom";
import { DeskPlaceholderPage } from "../desk/DeskPlaceholderPage";
import { ModelAccessSection } from "./ModelAccessSection";

/** Coral workflow settings shell; nested routes under ``/workflows/settings``. */
export function WorkflowSettingsPage() {
  return (
    <Routes>
      <Route index element={<Navigate to="model-access" replace />} />
      <Route path="model-access" element={<ModelAccessSection />} />
      <Route
        path="*"
        element={
          <DeskPlaceholderPage title="Workflow settings" testId="workflow-settings-placeholder" />
        }
      />
    </Routes>
  );
}
