import { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { useAuth } from "./AuthContext";

interface Props {
  children: ReactNode;
  requireAdmin?: boolean;
  /** When false, logged-in users that haven't finished onboarding are still
   *  allowed through (used by the onboarding page itself). Defaults to true. */
  requireOnboarding?: boolean;
}

export function ProtectedRoute({
  children,
  requireAdmin = false,
  requireOnboarding = true,
}: Props) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-[#4B5563]">
        Loading…
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (requireAdmin && user.role !== "admin") {
    return <Navigate to="/dashboard" replace />;
  }
  if (requireOnboarding && !user.onboarding_completed) {
    return <Navigate to="/onboarding" replace />;
  }
  return <>{children}</>;
}
