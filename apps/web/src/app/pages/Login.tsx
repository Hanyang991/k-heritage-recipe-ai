import { FormEvent, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { useAuth } from "../auth/AuthContext";

export function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("demo@k-heritage.app");
  const [password, setPassword] = useState("demo1234");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);

  const from = (location.state as { from?: string } | null)?.from || "/dashboard";

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (mode === "login") {
        await login(email, password);
        toast.success("환영합니다!");
        navigate(from, { replace: true });
      } else {
        await register(email, password, displayName);
        toast.success("회원가입이 완료되었습니다");
        // New accounts haven't completed onboarding yet — send them there
        // first so the dashboard can be personalized.
        navigate("/onboarding", { replace: true });
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "예상치 못한 오류가 발생했습니다";
      toast.error(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex-1 flex items-center justify-center bg-[#F9FAFB]">
      <div className="w-full max-w-md p-8 bg-white rounded-xl border border-[#E5E7EB] shadow-sm">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-bold text-[#3730A3]">K-Heritage Recipe AI</h1>
          <p className="text-sm text-[#4B5563] mt-1">
            {mode === "login" ? "로그인" : "회원가입"}
          </p>
        </div>

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <Label htmlFor="email">이메일</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="password">비밀번호</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              className="mt-1"
            />
          </div>
          {mode === "register" && (
            <div>
              <Label htmlFor="displayName">표시 이름</Label>
              <Input
                id="displayName"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="mt-1"
              />
            </div>
          )}
          <Button
            type="submit"
            disabled={busy}
            className="w-full bg-[#3730A3] hover:bg-[#6366F1]"
          >
            {busy ? "처리 중…" : mode === "login" ? "로그인" : "회원가입"}
          </Button>
        </form>

        <div className="text-center mt-4">
          <button
            type="button"
            className="text-sm text-[#3730A3] underline"
            onClick={() => setMode(mode === "login" ? "register" : "login")}
          >
            {mode === "login"
              ? "계정이 없으신가요? 회원가입"
              : "이미 계정이 있으신가요? 로그인"}
          </button>
        </div>

        <div className="mt-6 p-3 bg-[#F3F4F6] rounded text-xs text-[#4B5563]">
          <p className="font-semibold mb-1">데모 계정</p>
          <p>유저: demo@k-heritage.app / demo1234</p>
          <p>관리자: admin@k-heritage.app / admin1234</p>
        </div>
      </div>
    </div>
  );
}
