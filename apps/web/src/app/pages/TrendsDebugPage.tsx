import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, RefreshCw, RotateCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Sparkline } from "../components/Sparkline";
import { useTrendSparklines } from "../hooks/useTrendSparklines";
import { api, TrendDebugResponse } from "@/lib/api";

const LIMIT_OPTIONS = [10, 20, 50, 100];

const SOURCE_COLORS: Record<string, { bg: string; fg: string }> = {
  static: { bg: "#E5E7EB", fg: "#374151" },
  curated_watchlist: { bg: "#E5E7EB", fg: "#374151" },
  google_trends_daily: { bg: "#DBEAFE", fg: "#1D4ED8" },
  naver_news: { bg: "#DCFCE7", fg: "#15803D" },
  llm_expansion: { bg: "#FEF3C7", fg: "#B45309" },
  naver_shopping_insight: { bg: "#FCE7F3", fg: "#BE185D" },
};

function sourceTone(name: string) {
  return SOURCE_COLORS[name] ?? { bg: "#F3F4F6", fg: "#4B5563" };
}

function isoToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

export function TrendsDebugPage() {
  const [today, setToday] = useState<string>(isoToday());
  const [limit, setLimit] = useState<number>(20);
  const [data, setData] = useState<TrendDebugResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const out = await api.getTrendsDebug({ today, limit });
      setData(out);
    } catch (e) {
      setError(e instanceof Error ? e.message : "디버그 정보를 불러오지 못했습니다");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [today, limit]);

  useEffect(() => {
    load();
  }, [load]);

  const triggerRefresh = async () => {
    setRefreshing(true);
    try {
      const out = await api.refreshTrendsSnapshot();
      toast.success(
        `트렌드 스냅샷 갱신됨 · week_of=${out.week_of ?? "-"} · inserted=${out.inserted} · updated=${out.updated}`,
      );
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "갱신 실패");
    } finally {
      setRefreshing(false);
    }
  };

  const totalProviderElapsed = useMemo(
    () => data?.providers.reduce((sum, p) => sum + p.elapsed_ms, 0) ?? 0,
    [data],
  );

  const rankedKeywords = useMemo(
    () => data?.ranked.map((r) => r.keyword) ?? [],
    [data],
  );
  const sparklines = useTrendSparklines(rankedKeywords, 4);

  return (
    <div className="flex-1 overflow-auto bg-[#F9FAFB]">
      <div className="max-w-6xl mx-auto p-8">
        <div className="mb-6">
          <h1 className="text-[2rem] font-bold text-[#111827]">트렌드 디버그</h1>
          <p className="text-sm text-[#4B5563] mt-1">
            현재 활성화된 디스커버리 파이프라인의 소스별 통계 + 병합 후 랭킹.
            <code className="ml-1 px-1.5 py-0.5 bg-[#F3F4F6] rounded text-xs text-[#3730A3]">
              GET /v1/admin/trends/debug
            </code>
          </p>
        </div>

        <div className="bg-white rounded-xl border border-[#E5E7EB] p-4 mb-6 flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs text-[#4B5563] mb-1">기준일</label>
            <Input
              type="date"
              value={today}
              onChange={(e) => setToday(e.target.value)}
              className="w-44"
            />
          </div>
          <div>
            <label className="block text-xs text-[#4B5563] mb-1">상위</label>
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="h-9 px-3 rounded-md border border-[#E5E7EB] bg-white text-sm text-[#111827]"
            >
              {LIMIT_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={load}
            disabled={loading}
            className="gap-1.5"
          >
            <RotateCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            다시 조회
          </Button>
          <Button
            type="button"
            onClick={triggerRefresh}
            disabled={refreshing}
            className="gap-1.5 bg-[#3730A3] hover:bg-[#312E81] text-white"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
            트렌드 스냅샷 즉시 갱신
          </Button>
        </div>

        {error ? (
          <div className="bg-[#FEF2F2] border border-[#FECACA] text-[#B91C1C] rounded-xl p-4 flex items-start gap-2">
            <AlertCircle className="w-5 h-5 mt-0.5 flex-shrink-0" />
            <div className="text-sm">{error}</div>
          </div>
        ) : data === null ? (
          <div className="text-[#4B5563]">로딩 중…</div>
        ) : (
          <>
            <section className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
              <Stat label="discovery_type" value={data.discovery_type} mono />
              <Stat label="ref_date" value={data.ref_date} mono />
              <Stat
                label="unique_candidates"
                value={String(data.unique_candidate_count)}
              />
              <Stat label="scored" value={String(data.scored_count)} />
            </section>

            <h2 className="text-lg font-semibold text-[#111827] mb-3">
              소스별 통계 ({data.providers.length}개 · 합 {totalProviderElapsed}ms)
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-8">
              {data.providers.map((p) => {
                const tone = sourceTone(p.name);
                return (
                  <div
                    key={p.name}
                    className="bg-white rounded-xl border border-[#E5E7EB] p-4"
                  >
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span
                        className="px-2 py-0.5 rounded text-xs font-semibold"
                        style={{ backgroundColor: tone.bg, color: tone.fg }}
                      >
                        {p.name}
                      </span>
                      <div className="text-xs text-[#4B5563]">
                        {p.candidate_count}개 · {p.elapsed_ms}ms
                      </div>
                    </div>
                    {p.error ? (
                      <div className="text-xs text-[#B91C1C] bg-[#FEF2F2] border border-[#FECACA] rounded px-2 py-1 mb-2">
                        error: {p.error}
                      </div>
                    ) : null}
                    {p.candidates_sample.length === 0 ? (
                      <div className="text-xs text-[#9CA3AF]">샘플 없음</div>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {p.candidates_sample.map((c, i) => (
                          <span
                            key={`${c}-${i}`}
                            className="text-xs px-2 py-0.5 rounded bg-[#F9FAFB] border border-[#E5E7EB] text-[#374151]"
                          >
                            {c}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <h2 className="text-lg font-semibold text-[#111827] mb-3">
              병합 랭킹 ({data.ranked.length}개)
            </h2>
            {data.ranked.length === 0 ? (
              <div className="bg-white rounded-xl border border-[#E5E7EB] p-12 text-center text-[#4B5563]">
                랭킹 결과가 없습니다.
              </div>
            ) : (
              <div className="bg-white rounded-xl border border-[#E5E7EB] overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-[#F9FAFB] border-b border-[#E5E7EB]">
                    <tr>
                      <th className="text-left p-3 font-semibold text-[#4B5563] w-12">#</th>
                      <th className="text-left p-3 font-semibold text-[#4B5563]">키워드</th>
                      <th className="text-left p-3 font-semibold text-[#4B5563]">소스</th>
                      <th className="text-right p-3 font-semibold text-[#4B5563]">score</th>
                      <th className="text-right p-3 font-semibold text-[#4B5563]">current</th>
                      <th className="text-right p-3 font-semibold text-[#4B5563]">rise %</th>
                      <th className="text-left p-3 font-semibold text-[#4B5563] w-24">4주 추이</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.ranked.map((r, idx) => {
                      const points = sparklines.get(r.keyword);
                      return (
                      <tr
                        key={`${r.keyword}-${idx}`}
                        className="border-b border-[#F3F4F6]"
                      >
                        <td className="p-3 text-[#9CA3AF]">{idx + 1}</td>
                        <td className="p-3 font-semibold text-[#111827]">{r.keyword}</td>
                        <td className="p-3">
                          <div className="flex flex-wrap gap-1">
                            {r.all_sources.map((s) => {
                              const tone = sourceTone(s);
                              const isPrimary = s === r.primary_source;
                              return (
                                <span
                                  key={s}
                                  className="px-1.5 py-0.5 rounded text-xs"
                                  style={{
                                    backgroundColor: tone.bg,
                                    color: tone.fg,
                                    fontWeight: isPrimary ? 600 : 400,
                                    outline: isPrimary
                                      ? `1px solid ${tone.fg}40`
                                      : undefined,
                                  }}
                                  title={
                                    isPrimary ? "primary source" : "co-emitter"
                                  }
                                >
                                  {s}
                                </span>
                              );
                            })}
                          </div>
                        </td>
                        <td className="p-3 text-right font-mono text-[#111827]">
                          {r.score.toFixed(3)}
                        </td>
                        <td className="p-3 text-right text-[#4B5563]">
                          {r.current_ratio === null ? "-" : r.current_ratio.toFixed(2)}
                        </td>
                        <td className="p-3 text-right text-[#4B5563]">
                          {r.rise_percent === null ? "-" : `${r.rise_percent.toFixed(1)}%`}
                        </td>
                        <td className="p-3">
                          {points === undefined ? (
                            <Sparkline points={[]} width={72} height={22} />
                          ) : points === null || points.length < 2 ? (
                            <span className="text-xs text-[#9CA3AF]">-</span>
                          ) : (
                            <Sparkline points={points} width={72} height={22} />
                          )}
                        </td>
                      </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="bg-white rounded-xl border border-[#E5E7EB] p-4">
      <div className="text-xs text-[#4B5563] mb-1">{label}</div>
      <div
        className={`text-sm font-semibold text-[#111827] ${mono ? "font-mono" : ""}`}
      >
        {value}
      </div>
    </div>
  );
}
