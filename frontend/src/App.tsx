import { Navigate, Route, Routes } from "react-router-dom";
import { ToastProvider } from "./components/Toast";
import LandingPage from "./pages/LandingPage";
import ProjectsPage from "./pages/ProjectsPage";
import SystemWorkspace from "./pages/SystemWorkspace";

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/systems" element={<ProjectsPage />} />
        <Route path="/systems/:systemId/*" element={<SystemWorkspace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ToastProvider>
  );
}
