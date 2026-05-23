import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { api, TrendSeries } from "@/lib/api";

interface Props {
  keyword: string | null;
  onClose: () => void;
  weeks?: number;
}

export function TrendSeriesDialog({ keyword, onClose, weeks = 8 }: Props) {
  const [series, setSeries] = useState<TrendSeries | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!keyword) return;
    setSeries(null);
    setError(null);
    api
      .getTrendSeries(keyword, weeks)
      .then(setSeries)
      .catch((err: Error) => setError(err.message || "데이터를 불러오지 못했습니다."));
  }, [keyword, weeks]);

  const open = keyword !== null;

  const data =
    series?.points.map((p) => ({
      label: p.period.slice(5), // MM-DD
      ratio: p.ratio,
    })) ?? [];

  const peak = data.reduce((acc, d) => (d.ratio > acc ? d.ratio : acc), 0);
  const latest = data.length > 0 ? data[data.length - 1].ratio : 0;
  const first = data.length > 0 ? data[0].ratio : 0;
  const overallChange =
    data.length >= 2 && first > 0
      ? ((latest - first) / first) * 100
      : 0;

  return (
    <Dialog open={open} onOpenChange={(o) => (!o ? onClose() : undefined)}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{keyword ?? ""} 검색 트렌드</DialogTitle>
          <DialogDescription>
            최근 {weeks}주 검색 비중 (Naver DataLab 기준, 피크 = 100)
          </DialogDescription>
        </DialogHeader>

        {error ? (
          <div className="py-12 text-center text-sm text-[#DC2626]">{error}</div>
        ) : !series ? (
          <div className="py-12 text-center text-sm text-[#4B5563]">로딩 중…</div>
        ) : data.length === 0 ? (
          <div className="py-12 text-center text-sm text-[#4B5563]">
            해당 기간에 데이터가 없습니다.
          </div>
        ) : (
          <div>
            <div className="flex items-center gap-6 mb-3 text-sm">
              <div>
                <div className="text-[#4B5563]">최근</div>
                <div className="font-semibold text-[#111827]">{latest.toFixed(1)}</div>
              </div>
              <div>
                <div className="text-[#4B5563]">피크</div>
                <div className="font-semibold text-[#111827]">{peak.toFixed(1)}</div>
              </div>
              <div>
                <div className="text-[#4B5563]">{weeks}주 변화</div>
                <div
                  className={`font-semibold ${
                    overallChange >= 0 ? "text-[#059669]" : "text-[#DC2626]"
                  }`}
                >
                  {overallChange >= 0 ? "+" : ""}
                  {overallChange.toFixed(1)}%
                </div>
              </div>
            </div>
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                  <XAxis dataKey="label" stroke="#6B7280" fontSize={12} tickMargin={6} />
                  <YAxis
                    stroke="#6B7280"
                    fontSize={12}
                    domain={[0, 100]}
                    tickFormatter={(v) => `${v}`}
                  />
                  <Tooltip
                    formatter={(v: number) => [v.toFixed(1), "ratio"]}
                    labelFormatter={(l) => `주: ${l}`}
                  />
                  <Line
                    type="monotone"
                    dataKey="ratio"
                    stroke="#3730A3"
                    strokeWidth={2}
                    dot={{ r: 3, fill: "#3730A3" }}
                    activeDot={{ r: 5 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
