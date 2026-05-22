import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import {
  Coffee,
  Clock,
  Users,
  FileText,
  Share2,
  Copy,
  Download,
  Star,
} from "lucide-react";
import { Button } from "./ui/button";
import { Switch } from "./ui/switch";
import { toast } from "sonner";
import { ImageWithFallback } from "./figma/ImageWithFallback";
import { api, getToken, RecipeDetail as RecipeDetailType } from "@/lib/api";
import { useAuth } from "../auth/AuthContext";

export function RecipeDetail() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const [recipe, setRecipe] = useState<RecipeDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    api
      .getRecipe(id)
      .then(setRecipe)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  const handleCopy = () => {
    if (!recipe) return;
    navigator.clipboard.writeText(recipe.sns_caption);
    toast.success("SNS 문구가 복사되었습니다");
  };

  const handlePdfDownload = () => {
    if (!recipe) return;
    fetch(api.recipePdfUrl(recipe.id), {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${recipe.name}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
        toast.success("PDF가 다운로드됩니다");
      })
      .catch(() => toast.error("PDF 다운로드 실패"));
  };

  const handleCertificate = () => {
    if (!recipe) return;
    if ((user?.subscription?.plan ?? "free") === "free") {
      toast.info("Pro 플랜으로 업그레이드하면 고증 인증서를 발급받을 수 있습니다");
      return;
    }
    fetch(api.certificateUrl(recipe.id), {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
      .then((res) => {
        if (res.status === 402) {
          toast.info("Pro 플랜 필요");
          return null;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${recipe.name}_certificate.pdf`;
        a.click();
        URL.revokeObjectURL(url);
        toast.success("인증서가 발급되었습니다");
      })
      .catch(() => toast.error("인증서 발급 실패"));
  };

  const handleShare = () => {
    navigator.clipboard.writeText(window.location.href);
    toast.success("레시피 링크가 복사되었습니다");
  };

  const handleRating = async (rating: number) => {
    if (!recipe) return;
    const previous = recipe.rating;
    setRecipe({ ...recipe, rating });
    try {
      const updated = await api.updateRecipe(recipe.id, { rating });
      setRecipe(updated);
      toast.success(`별점 ${rating}점이 저장되었습니다`);
    } catch (e) {
      setRecipe({ ...recipe, rating: previous });
      toast.error(e instanceof Error ? e.message : "별점 저장 실패");
    }
  };

  const handleSellingToggle = async (next: boolean) => {
    if (!recipe) return;
    const previous = recipe.is_selling;
    setRecipe({ ...recipe, is_selling: next });
    try {
      const updated = await api.updateRecipe(recipe.id, { is_selling: next });
      setRecipe(updated);
      toast.success(next ? "판매 시작으로 표시되었습니다" : "판매 중지로 변경되었습니다");
    } catch (e) {
      setRecipe({ ...recipe, is_selling: previous });
      toast.error(e instanceof Error ? e.message : "판매 상태 변경 실패");
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-[#4B5563]">
        로딩 중…
      </div>
    );
  }
  if (error || !recipe) {
    return (
      <div className="flex-1 flex items-center justify-center text-[#4B5563]">
        레시피를 찾을 수 없습니다.
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto bg-[#F9FAFB]">
      <div className="max-w-7xl mx-auto p-8">
        <div className="grid grid-cols-3 gap-8">
          <div className="col-span-2 space-y-6">
            <div>
              <nav className="text-sm text-[#4B5563] mb-4">
                <Link to="/recipes" className="hover:text-[#3730A3]">
                  내 레시피
                </Link>
                <span className="mx-2">›</span>
                <span className="text-[#111827]">{recipe.name}</span>
              </nav>
              <h1 className="text-[2rem] font-bold text-[#111827] mb-4">
                {recipe.name}
              </h1>
              <div className="flex items-center gap-2 mb-4 flex-wrap">
                <span className="px-3 py-1 bg-[#EDE9FE] text-[#3730A3] text-sm rounded">
                  {recipe.region}
                </span>
                <span className="px-3 py-1 bg-[#EDE9FE] text-[#3730A3] text-sm rounded">
                  {recipe.era}
                </span>
                <span className="px-3 py-1 bg-[#EDE9FE] text-[#3730A3] text-sm rounded">
                  {recipe.diet}
                </span>
                {recipe.status === "approved" && (
                  <span className="px-3 py-1 bg-[#D1FAE5] text-[#059669] text-sm rounded flex items-center gap-1">
                    ✓ 승인완료
                  </span>
                )}
                {recipe.status === "pending_review" && (
                  <span className="px-3 py-1 bg-[#FEF3C7] text-[#D97706] text-sm rounded">
                    검수 대기
                  </span>
                )}
              </div>
              <div className="flex items-center gap-6 text-sm text-[#4B5563]">
                <div className="flex items-center gap-2">
                  <Coffee className="w-4 h-4" />
                  <span>{recipe.difficulty}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4" />
                  <span>{recipe.time_minutes}분</span>
                </div>
                <div className="flex items-center gap-2">
                  <Users className="w-4 h-4" />
                  <span>{recipe.servings}인분</span>
                </div>
              </div>
            </div>

            <div className="bg-[#FEF3C7] border-l-4 border-[#D97706] rounded-lg p-6">
              <h3 className="font-semibold text-[#111827] mb-3 flex items-center gap-2">
                📜 고문헌 출처
              </h3>
              <p className="text-sm text-[#4B5563] whitespace-pre-line">
                {recipe.source_attribution || "출처 정보가 없습니다."}
              </p>
            </div>

            {recipe.status === "rejected" && recipe.rejection_reason && (
              <div className="bg-[#FEE2E2] border-l-4 border-[#DC2626] rounded-lg p-6">
                <h3 className="font-semibold text-[#991B1B] mb-2 flex items-center gap-2">
                  ⚠ 검수 반려 사유
                </h3>
                <p className="text-sm text-[#7F1D1D] whitespace-pre-line">
                  {recipe.rejection_reason}
                </p>
              </div>
            )}

            <div className="bg-white rounded-xl border border-[#E5E7EB] p-6">
              <h2 className="text-lg font-semibold text-[#111827] mb-4">레시피 설명</h2>
              <p className="text-sm text-[#374151] leading-relaxed whitespace-pre-line">
                {recipe.description}
              </p>
            </div>

            <div className="bg-white rounded-xl border border-[#E5E7EB] p-6">
              <h2 className="text-lg font-semibold text-[#111827] mb-4">재료</h2>
              <div className="border border-[#E5E7EB] rounded-lg overflow-hidden">
                <table className="w-full">
                  <thead>
                    <tr className="bg-[#EDE9FE]">
                      <th className="text-left px-4 py-3 text-sm font-semibold text-[#3730A3]">
                        재료명
                      </th>
                      <th className="text-right px-4 py-3 text-sm font-semibold text-[#3730A3]">
                        분량
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {recipe.ingredients.map((item, index) => (
                      <tr
                        key={`${item.name}-${index}`}
                        className={index % 2 === 0 ? "bg-white" : "bg-[#F9FAFB]"}
                      >
                        <td className="px-4 py-3 text-sm text-[#111827]">
                          {item.name}
                          {item.note && (
                            <span className="ml-2 text-xs text-[#6B7280]">
                              {item.note}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-sm text-[#4B5563] text-right">
                          {item.amount}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-[#E5E7EB] p-6">
              <h2 className="text-lg font-semibold text-[#111827] mb-4">조리 방법</h2>
              <div className="space-y-4">
                {recipe.steps.map((step, index) => (
                  <div key={index} className="flex gap-4">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-[#3730A3] text-white flex items-center justify-center font-semibold">
                      {index + 1}
                    </div>
                    <div className="flex-1">
                      <h3 className="font-semibold text-[#111827] mb-1">
                        {step.title}
                        {step.waiting && (
                          <span className="ml-2 px-2 py-0.5 bg-[#FEF3C7] text-[#D97706] text-xs rounded">
                            ⏱ 대기 시간
                          </span>
                        )}
                      </h3>
                      <p className="text-sm text-[#4B5563]">{step.description}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-white rounded-xl border border-[#E5E7EB] p-6">
              <h2 className="text-lg font-semibold text-[#111827] mb-4">원가 분석</h2>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-[#4B5563] mb-1">원가</p>
                  <p className="text-xl font-bold text-[#111827]">
                    ₩{recipe.estimated_cost_krw.toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-[#4B5563] mb-1">예상 판매가</p>
                  <p className="text-xl font-bold text-[#3730A3]">
                    ₩{recipe.estimated_price_krw.toLocaleString()}
                  </p>
                </div>
              </div>
            </div>

            {recipe.sns_caption && (
              <div className="bg-white rounded-xl border border-[#E5E7EB] p-6">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-lg font-semibold text-[#111827]">
                    SNS 마케팅 문구
                  </h2>
                  <Button
                    size="sm"
                    variant="outline"
                    className="border-[#3730A3] text-[#3730A3]"
                    onClick={handleCopy}
                  >
                    <Copy className="w-4 h-4 mr-1" />
                    복사
                  </Button>
                </div>
                <div className="bg-[#F9FAFB] rounded-lg p-4 text-sm text-[#4B5563] font-mono whitespace-pre-line">
                  {recipe.sns_caption}
                </div>
              </div>
            )}
          </div>

          <div className="col-span-1">
            <div className="bg-white rounded-xl border border-[#E5E7EB] p-6 sticky top-8 space-y-4">
              <div className="mb-4 rounded-lg overflow-hidden bg-[#F3F4F6]">
                {recipe.image_url && (
                  <ImageWithFallback
                    src={recipe.image_url}
                    alt={recipe.name}
                    className="w-full h-48 object-cover"
                  />
                )}
              </div>
              <Button
                className="w-full bg-[#3730A3] hover:bg-[#6366F1] text-white h-12"
                onClick={handlePdfDownload}
              >
                <Download className="w-4 h-4 mr-2" />
                PDF 저장
              </Button>
              <Button
                variant="outline"
                className="w-full border-[#3730A3] text-[#3730A3] h-12 relative"
                onClick={handleCertificate}
              >
                <FileText className="w-4 h-4 mr-2" />
                고증 인증서 발급
                {(user?.subscription?.plan ?? "free") === "free" && (
                  <span className="absolute -top-1 -right-1 px-2 py-0.5 bg-[#3730A3] text-white text-xs rounded">
                    Pro
                  </span>
                )}
              </Button>
              <Button
                variant="ghost"
                className="w-full text-[#4B5563] h-12"
                onClick={handleShare}
              >
                <Share2 className="w-4 h-4 mr-2" />
                공유하기
              </Button>

              <div className="pt-4 mt-2 border-t border-[#E5E7EB] space-y-4">
                <div>
                  <p className="text-sm font-semibold text-[#111827] mb-2">
                    이 레시피가 도움이 됐나요?
                  </p>
                  <div
                    className="flex items-center gap-1"
                    role="radiogroup"
                    aria-label="별점"
                  >
                    {[1, 2, 3, 4, 5].map((star) => {
                      const active = star <= recipe.rating;
                      return (
                        <button
                          key={star}
                          type="button"
                          role="radio"
                          aria-checked={active}
                          aria-label={`별점 ${star}점`}
                          onClick={() => handleRating(star)}
                          className="p-1 rounded hover:bg-[#FEF3C7] transition-colors"
                        >
                          <Star
                            className={`w-6 h-6 ${
                              active
                                ? "fill-[#F59E0B] text-[#F59E0B]"
                                : "text-[#D1D5DB]"
                            }`}
                          />
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold text-[#111827]">
                      판매 시작했어요
                    </p>
                    <p className="text-xs text-[#6B7280] mt-0.5">
                      판매 중인 메뉴로 표시합니다
                    </p>
                  </div>
                  <Switch
                    checked={recipe.is_selling}
                    onCheckedChange={handleSellingToggle}
                    aria-label="판매 중"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
