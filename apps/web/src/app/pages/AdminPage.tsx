import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { Textarea } from "../components/ui/textarea";
import { api, RecipeListItem, RecipeStatus } from "@/lib/api";

const FILTERS: { id: RecipeStatus; label: string }[] = [
  { id: "pending_review", label: "검수 대기" },
  { id: "approved", label: "승인됨" },
  { id: "rejected", label: "반려됨" },
  { id: "flagged", label: "보류" },
];

export function AdminPage() {
  const [filter, setFilter] = useState<RecipeStatus>("pending_review");
  const [recipes, setRecipes] = useState<RecipeListItem[] | null>(null);
  const [rejectTarget, setRejectTarget] = useState<RecipeListItem | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = async (status: RecipeStatus) => {
    setRecipes(null);
    try {
      const list = await api.listPendingRecipes(status);
      setRecipes(list);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "로드 실패");
      setRecipes([]);
    }
  };

  useEffect(() => {
    load(filter);
  }, [filter]);

  const updateStatus = async (
    id: string,
    status: RecipeStatus,
    reason = ""
  ) => {
    try {
      await api.updateRecipeStatus(id, status, reason);
      toast.success("상태가 변경되었습니다");
      load(filter);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "변경 실패");
    }
  };

  const openRejectDialog = (recipe: RecipeListItem) => {
    setRejectTarget(recipe);
    setRejectReason(recipe.rejection_reason || "");
  };

  const closeRejectDialog = () => {
    if (submitting) return;
    setRejectTarget(null);
    setRejectReason("");
  };

  const confirmReject = async () => {
    if (!rejectTarget) return;
    if (!rejectReason.trim()) {
      toast.error("반려 사유를 입력해주세요");
      return;
    }
    setSubmitting(true);
    try {
      await api.updateRecipeStatus(rejectTarget.id, "rejected", rejectReason.trim());
      toast.success("반려되었습니다");
      setRejectTarget(null);
      setRejectReason("");
      load(filter);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "반려 실패");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex-1 overflow-auto bg-[#F9FAFB]">
      <div className="max-w-6xl mx-auto p-8">
        <div className="mb-6">
          <h1 className="text-[2rem] font-bold text-[#111827]">관리자 — 레시피 검수</h1>
          <p className="text-sm text-[#4B5563] mt-1">
            AI가 생성한 레시피를 사람이 검수합니다 (FR-07, 8.2.4)
          </p>
        </div>

        <div className="flex gap-2 mb-6">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={`px-4 py-2 rounded-lg border text-sm ${
                filter === f.id
                  ? "border-[#3730A3] bg-[#EDE9FE] text-[#3730A3] font-semibold"
                  : "border-[#E5E7EB] text-[#4B5563] hover:border-[#6366F1]"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {recipes === null ? (
          <div className="text-[#4B5563]">로딩 중…</div>
        ) : recipes.length === 0 ? (
          <div className="bg-white rounded-xl border border-[#E5E7EB] p-12 text-center text-[#4B5563]">
            해당 상태의 레시피가 없습니다.
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-[#E5E7EB] overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-[#F9FAFB] border-b border-[#E5E7EB]">
                <tr>
                  <th className="text-left p-3 font-semibold text-[#4B5563]">레시피</th>
                  <th className="text-left p-3 font-semibold text-[#4B5563]">지역</th>
                  <th className="text-left p-3 font-semibold text-[#4B5563]">시대</th>
                  <th className="text-left p-3 font-semibold text-[#4B5563]">키워드</th>
                  <th className="text-right p-3 font-semibold text-[#4B5563]">처리</th>
                </tr>
              </thead>
              <tbody>
                {recipes.map((r) => (
                  <tr key={r.id} className="border-b border-[#F3F4F6]">
                    <td className="p-3">
                      <div className="font-semibold text-[#111827]">{r.name}</div>
                      {r.status === "rejected" && r.rejection_reason && (
                        <div className="mt-1 text-xs text-[#B91C1C]">
                          반려 사유: {r.rejection_reason}
                        </div>
                      )}
                    </td>
                    <td className="p-3 text-[#4B5563]">{r.region}</td>
                    <td className="p-3 text-[#4B5563]">{r.era}</td>
                    <td className="p-3 text-[#4B5563]">{r.keyword}</td>
                    <td className="p-3 text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          className="bg-[#3730A3] hover:bg-[#6366F1]"
                          onClick={() => updateStatus(r.id, "approved")}
                        >
                          승인
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => updateStatus(r.id, "flagged")}
                        >
                          보류
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => openRejectDialog(r)}
                        >
                          반려
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Dialog
        open={rejectTarget !== null}
        onOpenChange={(open) => {
          if (!open) closeRejectDialog();
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>레시피 반려</DialogTitle>
            <DialogDescription>
              {rejectTarget?.name} 을(를) 반려합니다. 사유는 사용자에게 전달됩니다.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            placeholder="예: 재료가 식약처 기준을 충족하지 않아 반려됩니다."
            rows={4}
            disabled={submitting}
          />
          <DialogFooter>
            <Button
              variant="outline"
              onClick={closeRejectDialog}
              disabled={submitting}
            >
              취소
            </Button>
            <Button
              variant="destructive"
              onClick={confirmReject}
              disabled={submitting || !rejectReason.trim()}
            >
              반려 확정
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
