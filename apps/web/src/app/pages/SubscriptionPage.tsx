import { useState } from "react";
import { Check } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { useAuth } from "../auth/AuthContext";
import { api, Plan } from "@/lib/api";

interface PlanCard {
  plan: Plan;
  name: string;
  priceLabel: string;
  perks: string[];
  highlight?: boolean;
}

const PLANS: PlanCard[] = [
  {
    plan: "free",
    name: "Free",
    priceLabel: "₩0 / 월",
    perks: [
      "월 3회 레시피 생성",
      "PDF 다운로드 (워터마크)",
      "트렌드 대시보드 기본",
      "고문헌 검색",
    ],
  },
  {
    plan: "pro",
    name: "Pro",
    priceLabel: "₩29,000 / 월",
    highlight: true,
    perks: [
      "무제한 레시피 생성",
      "PDF 다운로드 (워터마크 없음)",
      "유산 인증서 발급",
      "지역/계절 트렌드 필터",
      "우선 검수",
    ],
  },
  {
    plan: "b2b",
    name: "B2B",
    priceLabel: "맞춤 견적",
    perks: [
      "Pro 전체 + 다중 사용자",
      "전용 API 접근",
      "기업 인증서 / SLA",
      "맞춤 데이터 통합",
    ],
  },
];

export function SubscriptionPage() {
  const { user, refresh } = useAuth();
  const [busy, setBusy] = useState<Plan | null>(null);

  const currentPlan = user?.subscription?.plan ?? "free";

  const upgrade = async (plan: Plan) => {
    if (plan === currentPlan) return;
    setBusy(plan);
    try {
      await api.changePlan(plan);
      await refresh();
      toast.success(`${plan.toUpperCase()} 플랜으로 변경되었습니다 (mock)`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "변경 실패");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex-1 overflow-auto bg-[#F9FAFB]">
      <div className="max-w-6xl mx-auto p-8">
        <div className="mb-8">
          <h1 className="text-[2rem] font-bold text-[#111827]">구독 관리</h1>
          <p className="text-sm text-[#4B5563] mt-1">
            현재 플랜:{" "}
            <span className="font-semibold text-[#3730A3]">
              {currentPlan.toUpperCase()}
            </span>
            {currentPlan === "free" && (
              <>
                {" "}· 이번 달 사용량 {user?.subscription?.monthly_recipe_count ?? 0}/3
              </>
            )}
          </p>
          <p className="text-xs text-[#9CA3AF] mt-1">
            * 결제는 mock 모드입니다. TossPayments 키가 설정되면 실제 결제로 전환됩니다.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {PLANS.map((p) => (
            <div
              key={p.plan}
              className={`bg-white rounded-xl p-6 border-2 ${
                p.highlight
                  ? "border-[#3730A3] shadow-sm"
                  : "border-[#E5E7EB]"
              } ${currentPlan === p.plan ? "ring-2 ring-[#D97706]" : ""}`}
            >
              <div className="mb-4">
                <h3 className="text-xl font-bold text-[#111827]">{p.name}</h3>
                <p className="text-2xl font-bold text-[#3730A3] mt-2">
                  {p.priceLabel}
                </p>
              </div>
              <ul className="space-y-2 mb-6">
                {p.perks.map((perk) => (
                  <li key={perk} className="flex items-start gap-2 text-sm">
                    <Check className="w-4 h-4 text-[#3730A3] mt-0.5 shrink-0" />
                    <span className="text-[#374151]">{perk}</span>
                  </li>
                ))}
              </ul>
              <Button
                className={`w-full ${
                  p.highlight
                    ? "bg-[#3730A3] hover:bg-[#6366F1]"
                    : "bg-[#374151] hover:bg-[#111827]"
                }`}
                disabled={currentPlan === p.plan || busy !== null}
                onClick={() => upgrade(p.plan)}
              >
                {currentPlan === p.plan
                  ? "현재 플랜"
                  : busy === p.plan
                    ? "변경 중…"
                    : `${p.name}로 변경`}
              </Button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
