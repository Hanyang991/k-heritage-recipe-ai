import {
  Home,
  PlusCircle,
  FolderOpen,
  BookOpen,
  CreditCard,
  ShieldCheck,
  LineChart,
  User,
  LogIn,
  LogOut,
} from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router";
import { useAuth } from "../auth/AuthContext";
import { NotificationBell } from "./NotificationBell";

export function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const baseItems = [
    { icon: Home, label: "대시보드", path: "/dashboard" },
    { icon: BookOpen, label: "고문헌 탐색", path: "/documents" },
  ];

  const userItems = user
    ? [
        { icon: PlusCircle, label: "레시피 생성", path: "/generate" },
        { icon: FolderOpen, label: "내 레시피", path: "/recipes" },
        { icon: CreditCard, label: "구독 관리", path: "/subscription" },
      ]
    : [];

  const adminItems = user?.role === "admin"
    ? [
        { icon: ShieldCheck, label: "관리자", path: "/admin" },
        { icon: LineChart, label: "트렌드 디버그", path: "/admin/trends/debug" },
      ]
    : [];

  const navItems = [...baseItems, ...userItems, ...adminItems];

  const plan = user?.subscription?.plan ?? "free";
  const planLabel = plan === "free" ? "Free" : plan === "pro" ? "Pro" : "B2B";

  return (
    <aside className="w-60 h-screen bg-white border-r border-[#E5E7EB] flex flex-col">
      <div className="p-6 border-b border-[#E5E7EB]">
        <h1 className="text-xl font-bold text-[#3730A3]">K-Heritage</h1>
        <p className="text-xs text-[#4B5563] mt-1">Recipe AI</p>
      </div>

      <nav className="flex-1 p-4">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = location.pathname === item.path;
          return (
            <Link
              key={item.path}
              to={item.path}
              className={`
                flex items-center gap-3 px-4 py-3 rounded-lg mb-2 transition-colors
                ${
                  isActive
                    ? "bg-[#EDE9FE] text-[#3730A3] font-semibold"
                    : "text-[#4B5563] hover:bg-[#F9FAFB]"
                }
              `}
            >
              <Icon className="w-5 h-5" />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="p-4 border-t border-[#E5E7EB]">
        {user ? (
          <div className="flex items-center gap-3 px-2 py-2">
            <div className="w-8 h-8 rounded-full bg-[#3730A3] flex items-center justify-center">
              <User className="w-4 h-4 text-white" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-[#111827] truncate">
                {user.display_name || user.email}
              </p>
              <span className="inline-block px-2 py-0.5 bg-[#E5E7EB] text-xs rounded text-[#4B5563]">
                {planLabel}
              </span>
            </div>
            <NotificationBell />
            <button
              type="button"
              onClick={logout}
              title="로그아웃"
              className="text-[#4B5563] hover:text-[#3730A3]"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="w-full flex items-center gap-3 px-4 py-3 rounded-lg text-[#3730A3] hover:bg-[#EDE9FE]"
            onClick={() => navigate("/login")}
          >
            <LogIn className="w-5 h-5" />
            <span className="font-semibold">로그인</span>
          </button>
        )}
      </div>
    </aside>
  );
}
