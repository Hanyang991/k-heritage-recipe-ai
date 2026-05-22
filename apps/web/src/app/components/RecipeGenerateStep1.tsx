import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { Button } from "./ui/button";
import { Label } from "./ui/label";
import { Input } from "./ui/input";
import { ArrowRight } from "lucide-react";
import { api } from "@/lib/api";

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

const regions = [
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

const dietaryRestrictions = [
  "제한 없음",
  "비건",
  "채식",
  "글루텐프리",
  "유당불내증",
  "견과류 알러지",
];

const menuTypes = [
  "디저트 음료",
  "케이크/빵",
  "전통 떡",
  "아이스크림/빙수",
  "차/티",
  "스낵",
];

export function RecipeGenerateStep1() {
  const navigate = useNavigate();
  const location = useLocation();
  const preset = (location.state as { keyword?: string } | null) || {};
  const [trendKeywords, setTrendKeywords] = useState<string[]>(FALLBACK_KEYWORDS);
  const [selectedKeyword, setSelectedKeyword] = useState(preset.keyword || "");
  const [customKeyword, setCustomKeyword] = useState("");
  const [selectedRegion, setSelectedRegion] = useState("");
  const [selectedDiet, setSelectedDiet] = useState("제한 없음");
  const [selectedMenuType, setSelectedMenuType] = useState("");

  useEffect(() => {
    api
      .listTrends("전국")
      .then((trends) => {
        if (trends.length > 0) {
          setTrendKeywords(trends.slice(0, 8).map((t) => t.keyword));
        }
      })
      .catch(() => {
        /* keep fallback */
      });
  }, []);

  const effectiveKeyword = customKeyword.trim() || selectedKeyword;
  const canProceed =
    Boolean(effectiveKeyword) && selectedRegion && selectedDiet && selectedMenuType;

  const handleSubmit = () => {
    if (canProceed) {
      navigate("/generate/step2", {
        state: {
          keyword: effectiveKeyword,
          region: selectedRegion,
          diet: selectedDiet,
          menuType: selectedMenuType,
        },
      });
    }
  };

  return (
    <div className="flex-1 overflow-auto bg-[#F9FAFB]">
      <div className="max-w-5xl mx-auto p-8">
        <div className="mb-8">
          <div className="flex items-center justify-center gap-4 mb-12">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full border-2 border-[#3730A3] text-[#3730A3] flex items-center justify-center font-bold">
                1
              </div>
              <span className="text-sm font-semibold text-[#3730A3]">
                ① 옵션 선택
              </span>
            </div>
            <div className="h-px w-16 bg-[#E5E7EB]"></div>
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full border-2 border-[#E5E7EB] text-[#4B5563] flex items-center justify-center">
                2
              </div>
              <span className="text-sm text-[#4B5563]">② 고문헌 매칭</span>
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

        <div className="bg-white rounded-xl border border-[#E5E7EB] p-8 space-y-8">
          <div>
            <Label className="text-base font-semibold text-[#111827] mb-4 block">
              트렌드 키워드 선택
            </Label>
            <p className="text-sm text-[#4B5563] mb-4">
              이번 주 인기 트렌드를 선택하거나 직접 입력하세요
            </p>
            <div className="grid grid-cols-4 gap-3 mb-3">
              {trendKeywords.map((keyword) => (
                <button
                  key={keyword}
                  onClick={() => {
                    setSelectedKeyword(keyword);
                    setCustomKeyword("");
                  }}
                  className={`px-4 py-3 rounded-lg border-2 transition-all ${
                    selectedKeyword === keyword && !customKeyword
                      ? "border-[#3730A3] bg-[#EDE9FE] text-[#3730A3] font-semibold"
                      : "border-[#E5E7EB] hover:border-[#6366F1] text-[#4B5563]"
                  }`}
                >
                  #{keyword}
                </button>
              ))}
            </div>
            <Input
              placeholder="직접 입력 (예: 식혜빙수)"
              value={customKeyword}
              onChange={(e) => setCustomKeyword(e.target.value)}
              className="max-w-xs"
            />
          </div>

          <div>
            <Label className="text-base font-semibold text-[#111827] mb-4 block">
              지역 선택
            </Label>
            <p className="text-sm text-[#4B5563] mb-4">
              레시피의 지역적 특색을 선택하세요
            </p>
            <div className="grid grid-cols-4 gap-3">
              {regions.map((region) => (
                <button
                  key={region}
                  onClick={() => setSelectedRegion(region)}
                  className={`px-4 py-3 rounded-lg border-2 transition-all ${
                    selectedRegion === region
                      ? "border-[#3730A3] bg-[#EDE9FE] text-[#3730A3] font-semibold"
                      : "border-[#E5E7EB] hover:border-[#6366F1] text-[#4B5563]"
                  }`}
                >
                  {region}
                </button>
              ))}
            </div>
          </div>

          <div>
            <Label className="text-base font-semibold text-[#111827] mb-4 block">
              식이 제약
            </Label>
            <p className="text-sm text-[#4B5563] mb-4">
              특별한 식이 요구사항이 있다면 선택하세요
            </p>
            <div className="grid grid-cols-3 gap-3">
              {dietaryRestrictions.map((diet) => (
                <button
                  key={diet}
                  onClick={() => setSelectedDiet(diet)}
                  className={`px-4 py-3 rounded-lg border-2 transition-all ${
                    selectedDiet === diet
                      ? "border-[#3730A3] bg-[#EDE9FE] text-[#3730A3] font-semibold"
                      : "border-[#E5E7EB] hover:border-[#6366F1] text-[#4B5563]"
                  }`}
                >
                  {diet}
                </button>
              ))}
            </div>
          </div>

          <div>
            <Label className="text-base font-semibold text-[#111827] mb-4 block">
              목표 메뉴 타입
            </Label>
            <p className="text-sm text-[#4B5563] mb-4">
              생성하고 싶은 메뉴의 카테고리를 선택하세요
            </p>
            <div className="grid grid-cols-3 gap-3">
              {menuTypes.map((type) => (
                <button
                  key={type}
                  onClick={() => setSelectedMenuType(type)}
                  className={`px-4 py-3 rounded-lg border-2 transition-all ${
                    selectedMenuType === type
                      ? "border-[#3730A3] bg-[#EDE9FE] text-[#3730A3] font-semibold"
                      : "border-[#E5E7EB] hover:border-[#6366F1] text-[#4B5563]"
                  }`}
                >
                  {type}
                </button>
              ))}
            </div>
          </div>

          <div className="pt-6 border-t border-[#E5E7EB]">
            <Button
              className="w-full bg-[#3730A3] hover:bg-[#6366F1] text-white h-12 text-base"
              disabled={!canProceed}
              onClick={handleSubmit}
            >
              다음 단계로
              <ArrowRight className="w-5 h-5 ml-2" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
