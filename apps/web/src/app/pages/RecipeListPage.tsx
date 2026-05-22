import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";
import { Clock, DollarSign, Trash2 } from "lucide-react";
import { Button } from "../components/ui/button";
import { api, RecipeListItem } from "@/lib/api";

const STATUS_LABEL: Record<string, string> = {
  pending_review: "검수 대기",
  approved: "승인",
  rejected: "반려",
  flagged: "보류",
  draft: "초안",
};

export function RecipeListPage() {
  const [recipes, setRecipes] = useState<RecipeListItem[] | null>(null);
  const navigate = useNavigate();

  const reload = async () => {
    try {
      const r = await api.listMyRecipes();
      setRecipes(r);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "레시피를 불러오지 못했습니다";
      toast.error(msg);
      setRecipes([]);
    }
  };

  useEffect(() => {
    reload();
  }, []);

  const handleDelete = async (id: string, name: string) => {
    if (!window.confirm(`"${name}" 레시피를 삭제하시겠습니까?`)) return;
    try {
      await api.deleteRecipe(id);
      toast.success("삭제되었습니다");
      reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "삭제 실패");
    }
  };

  return (
    <div className="flex-1 overflow-auto bg-[#F9FAFB]">
      <div className="max-w-6xl mx-auto p-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-[2rem] font-bold text-[#111827]">내 레시피</h1>
            <p className="text-sm text-[#4B5563] mt-1">
              생성한 레시피를 한곳에서 관리하세요
            </p>
          </div>
          <Button
            className="bg-[#3730A3] hover:bg-[#6366F1]"
            onClick={() => navigate("/generate")}
          >
            새 레시피 생성
          </Button>
        </div>

        {recipes === null ? (
          <div className="text-[#4B5563]">로딩 중…</div>
        ) : recipes.length === 0 ? (
          <div className="bg-white rounded-xl border border-[#E5E7EB] p-12 text-center">
            <p className="text-[#4B5563] mb-4">아직 저장된 레시피가 없습니다</p>
            <Button
              className="bg-[#3730A3] hover:bg-[#6366F1]"
              onClick={() => navigate("/generate")}
            >
              첫 레시피 생성하기
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {recipes.map((r) => (
              <div
                key={r.id}
                className={`bg-white rounded-xl overflow-hidden border ${
                  r.is_recommended ? "border-[#3730A3]" : "border-[#E5E7EB]"
                } hover:shadow-md transition-shadow`}
              >
                <Link to={`/recipes/${r.id}`}>
                  <div className="h-40 bg-[#F3F4F6] overflow-hidden">
                    {r.image_url && (
                      <img
                        src={r.image_url}
                        alt={r.name}
                        className="w-full h-full object-cover"
                      />
                    )}
                  </div>
                </Link>
                <div className="p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="px-2 py-0.5 bg-[#EDE9FE] text-[#3730A3] text-xs rounded">
                      {STATUS_LABEL[r.status] || r.status}
                    </span>
                    {r.is_recommended && (
                      <span className="text-xs text-[#D97706] font-semibold">
                        ★ 추천
                      </span>
                    )}
                  </div>
                  <Link to={`/recipes/${r.id}`}>
                    <h3 className="font-semibold text-[#111827] mb-2 hover:text-[#3730A3]">
                      {r.name}
                    </h3>
                  </Link>
                  <div className="flex items-center gap-3 text-xs text-[#4B5563] mb-3">
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {r.time_minutes}분
                    </span>
                    <span className="flex items-center gap-1">
                      <DollarSign className="w-3 h-3" />₩
                      {r.estimated_cost_krw.toLocaleString()}
                    </span>
                    <span>{r.region}</span>
                  </div>
                  <div className="flex gap-2">
                    <Link to={`/recipes/${r.id}`} className="flex-1">
                      <Button
                        size="sm"
                        variant="outline"
                        className="w-full border-[#3730A3] text-[#3730A3]"
                      >
                        자세히
                      </Button>
                    </Link>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleDelete(r.id, r.name)}
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
