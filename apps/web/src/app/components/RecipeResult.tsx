import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router";
import { Coffee, Clock, DollarSign } from "lucide-react";
import { Button } from "./ui/button";
import { toast } from "sonner";
import { ImageWithFallback } from "./figma/ImageWithFallback";
import { GenerateResponse } from "@/lib/api";

interface NavState {
  response?: GenerateResponse;
  formData?: { keyword: string; region: string; diet: string; menuType: string };
}

export function RecipeResult() {
  const navigate = useNavigate();
  const location = useLocation();
  const state = (location.state as NavState | null) || {};

  useEffect(() => {
    // If user navigates here directly without state, send them back to step 1
    if (!state.response) {
      navigate("/generate", { replace: true });
    }
  }, [navigate, state.response]);

  if (!state.response) return null;

  const candidates = state.response.candidates;

  return (
    <div className="flex-1 overflow-auto bg-[#F9FAFB]">
      <div className="max-w-7xl mx-auto p-8">
        <div className="flex items-start justify-between mb-8">
          <div>
            <h1 className="text-[2rem] font-bold text-[#111827] mb-2">
              레시피 생성 완료! 3가지 후보를 확인하세요
            </h1>
            <p className="text-sm text-[#4B5563]">
              자세히 보거나, 다른 조건으로 다시 생성할 수 있습니다
            </p>
          </div>
          <Button
            variant="ghost"
            className="text-[#3730A3]"
            onClick={() => navigate("/generate")}
          >
            다시 생성
          </Button>
        </div>

        <div className="grid grid-cols-3 gap-6 mb-8">
          {candidates.map((recipe) => (
            <div
              key={recipe.id}
              className={`bg-white rounded-xl overflow-hidden hover:shadow-lg transition-shadow ${
                recipe.is_recommended
                  ? "border-2 border-[#3730A3]"
                  : "border border-[#E5E7EB]"
              }`}
            >
              <div className="h-48 relative overflow-hidden bg-[#F3F4F6]">
                {recipe.image_url && (
                  <ImageWithFallback
                    src={recipe.image_url}
                    alt={recipe.name}
                    className="w-full h-full object-cover"
                  />
                )}
                {recipe.is_recommended && (
                  <div className="absolute top-4 right-4">
                    <span className="px-3 py-1 bg-[#3730A3] text-white text-xs rounded-full font-semibold">
                      ★ 추천
                    </span>
                  </div>
                )}
              </div>

              <div className="p-5">
                <h3 className="font-semibold text-[#111827] mb-2">{recipe.name}</h3>
                <p className="text-sm text-[#4B5563] mb-4 line-clamp-3">
                  {recipe.description}
                </p>

                <div className="flex items-center gap-2 mb-3 flex-wrap">
                  {recipe.tags.filter(Boolean).map((tag) => (
                    <span
                      key={tag}
                      className="px-2 py-0.5 bg-[#EDE9FE] text-[#3730A3] text-xs rounded"
                    >
                      {tag}
                    </span>
                  ))}
                </div>

                <div className="flex items-center gap-4 mb-4 text-sm text-[#4B5563]">
                  <div className="flex items-center gap-1">
                    <Coffee className="w-4 h-4" />
                    <span>{recipe.difficulty}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Clock className="w-4 h-4" />
                    <span>{recipe.time_minutes}분</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <DollarSign className="w-4 h-4" />
                    <span>₩{recipe.estimated_cost_krw.toLocaleString()}</span>
                  </div>
                </div>

                <p className="text-xs text-[#4B5563] mb-4 line-clamp-1">
                  {recipe.source_attribution}
                </p>

                <Button
                  className="w-full bg-[#3730A3] hover:bg-[#6366F1] text-white"
                  size="sm"
                  onClick={() => {
                    toast.success(`"${recipe.name}" 상세 페이지로 이동`);
                    navigate(`/recipes/${recipe.id}`);
                  }}
                >
                  자세히 보기 / 저장
                </Button>
              </div>
            </div>
          ))}
        </div>

        <div className="bg-[#F3F4F6] rounded-lg p-4 text-center">
          <p className="text-sm text-[#4B5563]">
            본 레시피는 공공누리 제1유형 데이터를 활용합니다 · 출처: 장서각, 국립민속박물관, 문화데이터광장
          </p>
        </div>
      </div>
    </div>
  );
}
