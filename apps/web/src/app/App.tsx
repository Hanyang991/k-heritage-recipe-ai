import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router";
import { Toaster } from "./components/ui/sonner";
import { Sidebar } from "./components/Sidebar";
import { TrendDashboard } from "./components/TrendDashboard";
import { RecipeGenerateStep1 } from "./components/RecipeGenerateStep1";
import { RecipeGenerate } from "./components/RecipeGenerate";
import { RecipeResult } from "./components/RecipeResult";
import { RecipeDetail } from "./components/RecipeDetail";
import { LoginPage } from "./pages/Login";
import { OnboardingPage } from "./pages/OnboardingPage";
import { RecipeListPage } from "./pages/RecipeListPage";
import { DocumentSearchPage } from "./pages/DocumentSearchPage";
import { SubscriptionPage } from "./pages/SubscriptionPage";
import { AdminPage } from "./pages/AdminPage";
import { TrendsDebugPage } from "./pages/TrendsDebugPage";
import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";

function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const hideSidebar =
    location.pathname === "/login" || location.pathname === "/onboarding";
  return (
    <div className="size-full flex bg-[#F9FAFB]">
      {!hideSidebar && <Sidebar />}
      {children}
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/onboarding"
              element={
                <ProtectedRoute requireOnboarding={false}>
                  <OnboardingPage />
                </ProtectedRoute>
              }
            />
            <Route path="/dashboard" element={<TrendDashboard />} />
            <Route path="/documents" element={<DocumentSearchPage />} />
            <Route
              path="/generate"
              element={
                <ProtectedRoute>
                  <RecipeGenerateStep1 />
                </ProtectedRoute>
              }
            />
            <Route
              path="/generate/step2"
              element={
                <ProtectedRoute>
                  <RecipeGenerate />
                </ProtectedRoute>
              }
            />
            <Route
              path="/generate/result"
              element={
                <ProtectedRoute>
                  <RecipeResult />
                </ProtectedRoute>
              }
            />
            <Route
              path="/recipes"
              element={
                <ProtectedRoute>
                  <RecipeListPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/recipes/:id"
              element={
                <ProtectedRoute>
                  <RecipeDetail />
                </ProtectedRoute>
              }
            />
            <Route
              path="/subscription"
              element={
                <ProtectedRoute>
                  <SubscriptionPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin"
              element={
                <ProtectedRoute requireAdmin>
                  <AdminPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/trends/debug"
              element={
                <ProtectedRoute requireAdmin>
                  <TrendsDebugPage />
                </ProtectedRoute>
              }
            />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </Layout>
        <Toaster />
      </AuthProvider>
    </BrowserRouter>
  );
}
