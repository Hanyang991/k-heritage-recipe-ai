import { useEffect, useState } from "react";
import { api } from "@/lib/api";

/**
 * Batched fan-out fetch of ``/v1/trends/series`` for a list of keywords,
 * returning a stable in-state ``Map<keyword, number[] | null>``.
 *
 * - Re-runs whenever the joined keyword list changes (so reordering the
 *   table doesn't refetch, but adding/removing keywords does).
 * - Caps the fan-out at ``maxKeywords`` to protect the (mock or live)
 *   backend from a 100-deep parallel burst. Keywords beyond the cap stay
 *   absent from the map and the consumer should render a placeholder.
 * - Returns ``null`` for keywords that failed to fetch so the UI can
 *   distinguish "still loading" (key not in map) from "no data" (null).
 */
export function useTrendSparklines(
  keywords: string[],
  weeks = 4,
  maxKeywords = 30,
): Map<string, number[] | null> {
  const [series, setSeries] = useState<Map<string, number[] | null>>(new Map());
  const cacheKey = keywords.slice(0, maxKeywords).join("|") + `::${weeks}`;

  useEffect(() => {
    let cancelled = false;
    const targets = keywords.slice(0, maxKeywords);
    if (targets.length === 0) {
      setSeries(new Map());
      return;
    }
    setSeries(new Map());

    Promise.all(
      targets.map((k) =>
        api
          .getTrendSeries(k, weeks)
          .then((s) => [k, s.points.map((p) => p.ratio)] as const)
          .catch(() => [k, null] as const),
      ),
    ).then((rows) => {
      if (cancelled) return;
      const next = new Map<string, number[] | null>();
      for (const [k, v] of rows) next.set(k, v);
      setSeries(next);
    });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cacheKey]);

  return series;
}
