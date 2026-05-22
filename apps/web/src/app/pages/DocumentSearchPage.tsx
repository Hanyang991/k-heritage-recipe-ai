import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { api, HeritageDocument } from "@/lib/api";

const INSTITUTIONS = [
  { id: "", label: "전체 기관" },
  { id: "jangseogak", label: "장서각" },
  { id: "nfm", label: "국립민속박물관" },
  { id: "culture", label: "문화데이터광장" },
];

export function DocumentSearchPage() {
  const [q, setQ] = useState("");
  const [institution, setInstitution] = useState("");
  const [docs, setDocs] = useState<HeritageDocument[] | null>(null);
  const [loading, setLoading] = useState(false);

  const search = async () => {
    setLoading(true);
    try {
      const result = await api.searchDocuments({ q, institution });
      setDocs(result);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    search();
  }, []);

  return (
    <div className="flex-1 overflow-auto bg-[#F9FAFB]">
      <div className="max-w-6xl mx-auto p-8">
        <div className="mb-6">
          <h1 className="text-[2rem] font-bold text-[#111827]">고문헌 탐색</h1>
          <p className="text-sm text-[#4B5563] mt-1">
            장서각 · 국립민속박물관 · 문화데이터광장에 수록된 고문헌을 검색합니다 (공공누리 제1유형)
          </p>
        </div>

        <div className="bg-white rounded-xl border border-[#E5E7EB] p-6 mb-6">
          <div className="flex gap-2 mb-3">
            <Input
              placeholder="키워드 (예: 쑥, 오미자, 떡)"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search()}
              className="flex-1"
            />
            <Button
              onClick={search}
              className="bg-[#3730A3] hover:bg-[#6366F1]"
              disabled={loading}
            >
              <Search className="w-4 h-4 mr-2" />
              검색
            </Button>
          </div>
          <div className="flex gap-2 flex-wrap">
            {INSTITUTIONS.map((inst) => (
              <button
                key={inst.id}
                onClick={() => setInstitution(inst.id)}
                className={`px-3 py-1 rounded-full text-sm border ${
                  institution === inst.id
                    ? "border-[#3730A3] bg-[#EDE9FE] text-[#3730A3]"
                    : "border-[#E5E7EB] text-[#4B5563] hover:border-[#6366F1]"
                }`}
              >
                {inst.label}
              </button>
            ))}
          </div>
        </div>

        {docs === null ? (
          <div className="text-[#4B5563]">로딩 중…</div>
        ) : docs.length === 0 ? (
          <div className="bg-white rounded-xl border border-[#E5E7EB] p-12 text-center text-[#4B5563]">
            검색 결과가 없습니다.
          </div>
        ) : (
          <div className="space-y-3">
            {docs.map((doc) => (
              <div
                key={doc.id}
                className="bg-white rounded-lg border border-[#E5E7EB] p-5 hover:shadow-sm transition-shadow"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-[#FEF3C7] flex items-center justify-center">
                      <span className="text-lg">📜</span>
                    </div>
                    <div>
                      <h3 className="font-semibold text-[#111827]">
                        {doc.title}
                        {doc.year ? ` (${doc.year})` : ""}
                      </h3>
                      <p className="text-xs text-[#4B5563]">
                        {INSTITUTIONS.find((i) => i.id === doc.institution)?.label ||
                          doc.institution}
                      </p>
                    </div>
                  </div>
                  <span className="text-xs px-2 py-0.5 bg-[#F3F4F6] rounded text-[#4B5563]">
                    {doc.license}
                  </span>
                </div>
                <div className="flex gap-4 text-xs text-[#4B5563] mb-2">
                  <span>지역: {doc.region}</span>
                  <span>시대: {doc.period}</span>
                  {doc.category && <span>분류: {doc.category}</span>}
                </div>
                <p className="text-sm text-[#374151] leading-relaxed">
                  {doc.summary}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
