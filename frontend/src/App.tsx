import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./layouts/AppLayout";
import { DashboardPage } from "./pages/DashboardPage";
import { NewProjectPage } from "./pages/NewProjectPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ScriptPage } from "./pages/ScriptPage";
import { TranslationPage } from "./pages/TranslationPage";
import { AudioPage } from "./pages/AudioPage";
import { TimelinePage } from "./pages/TimelinePage";
import { QAReviewPage } from "./pages/QAReviewPage";
import { AlignmentPage } from "./pages/AlignmentPage";
import { ExportsPage } from "./pages/ExportsPage";
import { SettingsPage } from "./pages/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/new" element={<NewProjectPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/script" element={<ScriptPage />} />
        <Route path="/translation" element={<TranslationPage />} />
        <Route path="/audio" element={<AudioPage />} />
        <Route path="/timeline" element={<TimelinePage />} />
        <Route path="/qa" element={<QAReviewPage />} />
        <Route path="/alignment" element={<AlignmentPage />} />
        <Route path="/exports" element={<ExportsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
