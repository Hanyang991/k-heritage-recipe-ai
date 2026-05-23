import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { Sparkles, ArrowRight } from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { api, Trend } from "@/lib/api";
import { useAuth } from "../auth/AuthContext";

const PERSONAS = [
  "카페 사장",
  "푸드 크리에이터",
  "홈베이커",
  "F&B 기획자",
  "셰프",
  "그 외",
];

const REGIONS = [
  "전국",
  "서울",
  "경기",
  "전라북도",
  "전라남도",
  "경상북도",
  "경상남도",
  "충청북도",
  "충청남도",
  "강원",
  "제주",
];

const FALLBACK_KEYWORDS = [
  "쑥라떼",
  "오미자에이드",
  "흑임자크림",
  "매실청소다",
  "인절미케이크",
  "한방차라떼",
  "곶감스무디",
  "유자청티",
];

const MAX_REGIONS = 5;
const MAX_KEYWORDS = 8;

function toggle(list: string[], value: string, max: number): string[] {
  if (list.includes(value)) return list.filter((v) => v !== value);
  if (list.length >= max) return list;
  return [...list, value];
}

export function OnboardingPage() {
  const { user, refresh } = useAuth();
  const navigate = useNavigate();
  const [displayName, setDisplayName] = useState("");
  const [persona, setPersona] = useState("");
  const [regions, setRegions] = useState<string[]>([]);
  const [keywords, setKeywords] = useState<string[]>([]);
  const [trendKeywords, setTrendKeywords] = useState<string[]>(FALLBACK_KEYWORDS);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!user) return;
    setDisplayName(user.display_name || "");
    setPersona(user.persona || "");
    setRegions(user.preferred_regions || []);
    setKeywords(user.preferred_keywords || []);
  }, [user]);

  useEffect(() => {
    api
      .listTrends("전국")
      .then((trends: Trend[]) => {
        if (trends.length > 0) {
          setTrendKeywords(trends.slice(0, 12).map((t) => t.keyword));
        }
      })
      .catch(() => {
        /* keep fallback */
      });
  }, []);

  const canSave = persona !== "" && regions.length > 0;

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      await api.updateMe({
        display_name: displayName.trim() || undefined,
        persona,
        preferred_regions: regions,
        preferred_keywords: keywords,
        onboarding_completed: true,
      });
      await refresh();
      toast.success("환영합니다! 맞춤 트렌드를 준비했어요.");
      navigate("/dashboard", { replace: true });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "프로필 저장 중 오류가 발생했습니다";
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  const handleSkip = async () => {
    setSaving(true);
    try {
      await api.updateMe({ onboarding_completed: true });
      await refresh();
      navigate("/dashboard", { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : "오류가 발생했습니다";
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex-1 overflow-auto bg-[#F9FAFB]">
      <div className="max-w-3xl mx-auto p-8">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-[#EDE9FE] text-[#3730A3] mb-4">
            <Sparkles className="w-7 h-7" />
          </div>
          <h1 className="text-[2rem] font-bold text-[#111827] mb-2">
            환영합니다 👋
          </h1>
          <p className="text-sm text-[#4B5563]">
            몇 가지만 알려주시면 더 잘 맞는 트렌드와 레시피를 추천해드려요
          </p>
        </div>

        <div className="bg-white rounded-xl border border-[#E5E7EB] p-8 space-y-8">
          <div>
            <Label
              htmlFor="display-name"
              className="text-base font-semibold text-[#111827] mb-2 block"
            >
              표시 이름
            </Label>
            <p className="text-sm text-[#4B5563] mb-3">
              앱과 PDF에 표시될 이름이에요 (선택)
            </p>
            <Input
              id="display-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={120}
              className="max-w-xs"
              placeholder="예: 홍길동 / 한옥카페"
            />
          </div>

          <div>
            <Label className="text-base font-semibold text-[#111827] mb-2 block">
              어떤 분이세요? <span className="text-[#DC2626]">*</span>
            </Label>
            <p className="text-sm text-[#4B5563] mb-3">
              가장 가까운 역할을 하나 선택하세요
            </p>
            <div className="grid grid-cols-3 gap-3">
              {PERSONAS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPersona(p)}
                  className={`px-4 py-3 rounded-lg border-2 transition-all ${
                    persona === p
                      ? "border-[#3730A3] bg-[#EDE9FE] text-[#3730A3] font-semibold"
                      : "border-[#E5E7EB] hover:border-[#6366F1] text-[#4B5563]"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          <div>
            <Label className="text-base font-semibold text-[#111827] mb-2 block">
              관심 지역 <span className="text-[#DC2626]">*</span>
            </Label>
            <p className="text-sm text-[#4B5563] mb-3">
              최대 {MAX_REGIONS}곳까지 선택할 수 있어요 ({regions.length}/
              {MAX_REGIONS})
            </p>
            <div className="grid grid-cols-4 gap-3">
              {REGIONS.map((region) => {
                const selected = regions.includes(region);
                return (
                  <button
                    key={region}
                    type="button"
                    onClick={() =>
                      setRegions((r) => toggle(r, region, MAX_REGIONS))
                    }
                    className={`px-4 py-3 rounded-lg border-2 transition-all ${
                      selected
                        ? "border-[#3730A3] bg-[#EDE9FE] text-[#3730A3] font-semibold"
                        : "border-[#E5E7EB] hover:border-[#6366F1] text-[#4B5563]"
                    }`}
                  >
                    {region}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <Label className="text-base font-semibold text-[#111827] mb-2 block">
              관심 키워드
            </Label>
            <p className="text-sm text-[#4B5563] mb-3">
              평소 만들고 싶은 메뉴 키워드를 골라주세요 (선택, 최대{" "}
              {MAX_KEYWORDS}개, {keywords.length}/{MAX_KEYWORDS})
            </p>
            <div className="flex flex-wrap gap-2">
              {trendKeywords.map((kw) => {
                const selected = keywords.includes(kw);
                return (
                  <button
                    key={kw}
                    type="button"
                    onClick={() =>
                      setKeywords((k) => toggle(k, kw, MAX_KEYWORDS))
                    }
                    className={`px-3 py-2 rounded-full border-2 text-sm transition-all ${
                      selected
                        ? "border-[#3730A3] bg-[#EDE9FE] text-[#3730A3] font-semibold"
                        : "border-[#E5E7EB] hover:border-[#6366F1] text-[#4B5563]"
                    }`}
                  >
                    #{kw}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="pt-6 border-t border-[#E5E7EB] flex flex-col gap-3">
            <Button
              className="w-full bg-[#3730A3] hover:bg-[#6366F1] text-white h-12 text-base"
              disabled={!canSave || saving}
              onClick={handleSave}
            >
              {saving ? "저장 중…" : "시작하기"}
              {!saving && <ArrowRight className="w-5 h-5 ml-2" />}
            </Button>
            <button
              type="button"
              className="text-sm text-[#4B5563] hover:text-[#3730A3] underline disabled:opacity-50"
              disabled={saving}
              onClick={handleSkip}
            >
              나중에 설정하기
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
