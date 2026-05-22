import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { TrendingUp, ArrowUpRight, ArrowDownRight } from "lucide-react";
import { Button } from "./ui/button";
import { ImageWithFallback } from "./figma/ImageWithFallback";
import { api, RecipeListItem, Trend } from "@/lib/api";
import { useAuth } from "../auth/AuthContext";

const REGIONS = ["전국", "서울", "경기", "전라북도", "경상남도", "충청남도", "강원", "제주"];

export function TrendDashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [region, setRegion] = useState("전국");
  const [trends, setTrends] = useState<Trend[] | null>(null);
  const [recentRecipes, setRecentRecipes] = useState<RecipeListItem[]>([]);

  useEffect(() => {
    api.listTrends(region).then(setTrends).catch(() => setTrends([]));
  }, [region]);

  useEffect(() => {
    if (!user) return;
    api
      .listMyRecipes()
      .then((list) => setRecentRecipes(list.slice(0, 3)))
      .catch(() => setRecentRecipes([]));
  }, [user]);

  return (
    <div className="flex-1 overflow-auto bg-[#F9FAFB]">
      <div className="max-w-7xl mx-auto p-8">
        <div className="flex items-start justify-between mb-8">
          <div>
            <h1 className="text-[2rem] font-bold text-[#111827] mb-2">
              트렌드 대시보드
            </h1>
            <p className="text-sm text-[#4B5563]">
              이번 주 급상승 키워드를 확인하고 레시피를 생성하세요
            </p>
          </div>
          <div className="flex items-center gap-3">
            <select
              className="px-4 py-2 border border-[#E5E7EB] rounded-lg text-sm bg-white"
              value={region}
              onChange={(e) => setRegion(e.target.value)}
            >
              {REGIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <Button
              className="bg-[#3730A3] hover:bg-[#6366F1] text-white px-6"
              onClick={() => navigate("/generate")}
            >
              레시피 생성하기
            </Button>
          </div>
        </div>

        <div className="mb-10">
          <div className="flex items-center gap-2 mb-6">
            <TrendingUp className="w-5 h-5 text-[#3730A3]" />
            <h2 className="text-[1.125rem] font-semibold text-[#111827]">
              이번 주 TOP 20 트렌드
            </h2>
          </div>
          {trends === null ? (
            <div className="text-[#4B5563]">로딩 중…</div>
          ) : trends.length === 0 ? (
            <div className="bg-white border border-dashed border-[#E5E7EB] rounded-lg p-8 text-center text-[#4B5563]">
              아직 트렌드 데이터가 없습니다. 시드 데이터를 로드하세요:
              <code className="ml-2 px-2 py-0.5 bg-[#F3F4F6] rounded text-xs">
                python -m app.db.seed
              </code>
            </div>
          ) : (
            <div className="grid grid-cols-5 gap-3">
              {trends.map((trend) => {
                const bgColor =
                  trend.rank <= 3
                    ? "bg-[#FEF3C7] border-[#D97706]"
                    : trend.rank <= 10
                      ? "bg-[#EDE9FE] border-[#6366F1]"
                      : "bg-white border-[#E5E7EB]";

                const textColor =
                  trend.rank <= 3
                    ? "text-[#D97706]"
                    : trend.rank <= 10
                      ? "text-[#3730A3]"
                      : "text-[#4B5563]";

                return (
                  <div
                    key={trend.rank}
                    className={`${bgColor} border-2 rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer`}
                    onClick={() =>
                      navigate("/generate", { state: { keyword: trend.keyword } })
                    }
                  >
                    <div className="flex items-start justify-between mb-2">
                      <span className={`text-lg font-bold ${textColor}`}>
                        #{trend.rank}
                      </span>
                      <div
                        className={`flex items-center gap-1 text-xs ${
                          trend.is_up ? "text-[#059669]" : "text-[#DC2626]"
                        }`}
                      >
                        {trend.is_up ? (
                          <ArrowUpRight className="w-3 h-3" />
                        ) : (
                          <ArrowDownRight className="w-3 h-3" />
                        )}
                        <span>{Math.round(trend.change_percent)}%</span>
                      </div>
                    </div>
                    <p className={`font-semibold ${textColor}`}>{trend.keyword}</p>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {user && recentRecipes.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-[1.125rem] font-semibold text-[#111827]">
                📋 최근 생성한 레시피
              </h2>
              <a href="/recipes" className="text-sm text-[#3730A3] hover:underline">
                전체보기 →
              </a>
            </div>
            <div className="grid grid-cols-3 gap-6">
              {recentRecipes.map((recipe) => (
                <div
                  key={recipe.id}
                  className="bg-white rounded-xl border border-[#E5E7EB] overflow-hidden hover:shadow-lg transition-shadow"
                >
                  <div className="h-40 relative overflow-hidden bg-[#F3F4F6]">
                    {recipe.image_url && (
                      <ImageWithFallback
                        src={recipe.image_url}
                        alt={recipe.name}
                        className="w-full h-full object-cover"
                      />
                    )}
                  </div>
                  <div className="p-5">
                    <div className="flex items-center gap-2 mb-3">
                      <span className="px-2 py-1 bg-[#EDE9FE] text-[#3730A3] text-xs rounded">
                        {recipe.region}
                      </span>
                      <span className="px-2 py-1 bg-[#EDE9FE] text-[#3730A3] text-xs rounded">
                        {recipe.era}
                      </span>
                      {recipe.status === "approved" && (
                        <span className="px-2 py-1 bg-[#D1FAE5] text-[#059669] text-xs rounded">
                          ✓ 승인
                        </span>
                      )}
                      {recipe.status === "pending_review" && (
                        <span className="px-2 py-1 bg-[#FEF3C7] text-[#D97706] text-xs rounded">
                          검수중
                        </span>
                      )}
                    </div>
                    <h3 className="font-semibold text-[#111827] mb-2">
                      {recipe.name}
                    </h3>
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full border-[#3730A3] text-[#3730A3] hover:bg-[#EDE9FE]"
                      onClick={() => navigate(`/recipes/${recipe.id}`)}
                    >
                      자세히 보기
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
