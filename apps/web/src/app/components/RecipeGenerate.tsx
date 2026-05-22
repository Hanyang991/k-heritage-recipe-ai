import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router";
import { Check, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "./ui/button";
import { Progress } from "./ui/progress";
import { api, DocumentMatch } from "@/lib/api";

interface NavState {
  keyword: string;
  region: string;
  diet: string;
  menuType: string;
}

export function RecipeGenerate() {
  const navigate = useNavigate();
  const location = useLocation();
  const [isLoading, setIsLoading] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null);
  const [matches, setMatches] = useState<DocumentMatch[] | null>(null);
  const [searching, setSearching] = useState(true);

  const formData: NavState = (location.state as NavState) || {
    keyword: "쑥라떼",
    region: "전라북도",
    diet: "비건",
    menuType: "디저트 음료",
  };

  useEffect(() => {
    let cancelled = false;
    setSearching(true);
    api
      .searchDocuments({ q: formData.keyword, region: formData.region })
      .then((docs) => {
        if (cancelled) return;
        const mapped: DocumentMatch[] = docs.slice(0, 3).map((d, i) => ({
          document: d,
          match_score: 0.94 - i * 0.1,
        }));
        setMatches(mapped);
        if (mapped[0]) setSelectedDoc(mapped[0].document.id);
      })
      .finally(() => !cancelled && setSearching(false));
    return () => {
      cancelled = true;
    };
  }, [formData.keyword, formData.region]);

  const handleGenerate = async () => {
    setIsLoading(true);
    try {
      const response = await api.generateRecipes({
        keyword: formData.keyword,
        region: formData.region,
        diet: formData.diet,
        menu_type: formData.menuType,
        document_id: selectedDoc ?? undefined,
      });
      navigate("/generate/result", { state: { response, formData } });
    } catch (e) {
      const err = e as { code?: string; message?: string };
      if (err.code === "RECIPE_QUOTA_EXCEEDED") {
        toast.error("월 사용량을 초과했습니다. Pro 플랜으로 업그레이드하세요.");
        navigate("/subscription");
      } else {
        toast.error(err.message || "레시피 생성에 실패했습니다");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleBack = () => {
    navigate("/generate");
  };

  return (
    <div className="flex-1 overflow-auto bg-[#F9FAFB]">
      <div className="max-w-5xl mx-auto p-8">
        <div className="mb-8">
          <div className="flex items-center justify-center gap-4 mb-12">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-[#3730A3] text-white flex items-center justify-center">
                <Check className="w-4 h-4" />
              </div>
              <span className="text-sm text-[#4B5563]">① 옵션 선택</span>
            </div>
            <div className="h-px w-16 bg-[#E5E7EB]"></div>
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full border-2 border-[#3730A3] text-[#3730A3] flex items-center justify-center font-bold">
                2
              </div>
              <span className="text-sm font-semibold text-[#3730A3]">
                ② 고문헌 매칭
              </span>
            </div>
            <div className="h-px w-16 bg-[#E5E7EB]"></div>
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full border-2 border-[#E5E7EB] text-[#4B5563] flex items-center justify-center">
                3
              </div>
              <span className="text-sm text-[#4B5563]">③ 결과 확인</span>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-6">
          <div className="col-span-2">
            <div className="bg-white rounded-xl border border-[#E5E7EB] p-8">
              <h2 className="text-xl font-semibold text-[#111827] mb-6">
                입력하신 조건에 맞는 고문헌을 찾고 있습니다
              </h2>

              {searching ? (
                <div className="space-y-3 mb-8">
                  {[1, 2, 3].map((i) => (
                    <div
                      key={i}
                      className="h-32 rounded-lg bg-[#F3F4F6] animate-pulse"
                    />
                  ))}
                </div>
              ) : matches && matches.length > 0 ? (
                <div className="space-y-4 mb-8">
                  {matches.map((m) => {
                    const doc = m.document;
                    const score = Math.round(m.match_score * 100);
                    return (
                      <div
                        key={doc.id}
                        className={`border-2 rounded-lg p-5 cursor-pointer transition-all ${
                          selectedDoc === doc.id
                            ? "border-[#3730A3] bg-[#EDE9FE]"
                            : "border-[#E5E7EB] hover:border-[#6366F1]"
                        }`}
                        onClick={() => setSelectedDoc(doc.id)}
                      >
                        <div className="flex items-start justify-between mb-3">
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-lg bg-[#FEF3C7] flex items-center justify-center">
                              <span className="text-lg">📜</span>
                            </div>
                            <div>
                              <h3 className="font-semibold text-[#111827]">
                                {doc.title}
                                {doc.year ? ` (${doc.year})` : ""}
                              </h3>
                              <p className="text-sm text-[#4B5563]">
                                {doc.institution}
                              </p>
                            </div>
                          </div>
                          {selectedDoc === doc.id && (
                            <Check className="w-5 h-5 text-[#3730A3]" />
                          )}
                        </div>
                        <div className="flex items-center gap-4 mb-3">
                          <span className="text-sm text-[#4B5563]">
                            지역: {doc.region}
                          </span>
                          <span className="text-sm text-[#4B5563]">
                            시대: {doc.period}
                          </span>
                        </div>
                        <div className="space-y-2">
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-[#4B5563]">매칭도</span>
                            <span className="font-semibold text-[#3730A3]">
                              {score}%
                            </span>
                          </div>
                          <Progress value={score} className="h-2" />
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="text-[#4B5563] py-8 text-center mb-8">
                  매칭되는 고문헌을 찾지 못했습니다. 다른 키워드로 시도해 보세요.
                </div>
              )}

              <div className="space-y-3">
                <Button
                  className="w-full bg-[#3730A3] hover:bg-[#6366F1] text-white h-12"
                  disabled={isLoading || searching}
                  onClick={handleGenerate}
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      레시피 생성 중...
                    </>
                  ) : (
                    "선택한 문헌으로 레시피 생성하기"
                  )}
                </Button>
                <Button
                  variant="ghost"
                  className="w-full text-[#3730A3]"
                  disabled={isLoading}
                  onClick={handleBack}
                >
                  다시 검색
                </Button>
              </div>
            </div>
          </div>

          <div className="col-span-1">
            <div className="bg-white rounded-xl border border-[#E5E7EB] p-6 sticky top-8">
              <h3 className="font-semibold text-[#111827] mb-4">입력 요약</h3>
              <div className="space-y-4">
                <div>
                  <p className="text-sm text-[#4B5563] mb-1">트렌드 키워드</p>
                  <p className="font-semibold text-[#111827]">#{formData.keyword}</p>
                </div>
                <div>
                  <p className="text-sm text-[#4B5563] mb-1">지역</p>
                  <p className="font-semibold text-[#111827]">{formData.region}</p>
                </div>
                <div>
                  <p className="text-sm text-[#4B5563] mb-1">식이 제약</p>
                  <p className="font-semibold text-[#111827]">{formData.diet}</p>
                </div>
                <div>
                  <p className="text-sm text-[#4B5563] mb-1">목표 메뉴</p>
                  <p className="font-semibold text-[#111827]">{formData.menuType}</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {isLoading && (
          <div className="fixed inset-0 bg-black/20 backdrop-blur-sm flex items-center justify-center z-50">
            <div className="bg-white rounded-xl p-8 max-w-md text-center">
              <Loader2 className="w-16 h-16 mx-auto mb-4 text-[#3730A3] animate-spin" />
              <h3 className="text-xl font-semibold text-[#111827] mb-2">
                고문헌 데이터를 분석하고 있습니다...
              </h3>
              <p className="text-sm text-[#4B5563] mb-4">
                Mock LLM에서는 즉시 결과가 나옵니다. 실제 모드에서는 최대 30초.
              </p>
              <div className="flex items-center justify-center gap-1">
                <div className="w-2 h-2 bg-[#3730A3] rounded-full animate-bounce"></div>
                <div className="w-2 h-2 bg-[#3730A3] rounded-full animate-bounce [animation-delay:0.2s]"></div>
                <div className="w-2 h-2 bg-[#3730A3] rounded-full animate-bounce [animation-delay:0.4s]"></div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
