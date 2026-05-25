"""Heritage corpus → vector index backfill job.

Walks the configured seed queries through the keyword heritage adapter,
deduplicates the collected docs by ``(institution, external_id)``, and
upserts them via :class:`HeritageIndexer`. Required first-time step
after a deployment switches to ``HERITAGE_RETRIEVAL_MODE=hybrid`` —
otherwise the semantic side of hybrid retrieval has nothing to return
and behaviour silently collapses to keyword-only.

Usage
-----
::

    # ad-hoc run with whatever heritage / embedding / vector-store
    # providers are configured in the current environment
    python -m app.jobs.backfill_heritage_index

    # admin-triggered (see POST /v1/admin/heritage/index/backfill)

The job is idempotent — re-running with the same seed pool refreshes
the vector store in place (upserts are keyed by datapoint_id). Use
``HERITAGE_BACKFILL_QUERIES`` to scope a re-run to a smaller subset of
queries when only one source is being re-indexed.
"""

from __future__ import annotations

import json
import logging
import sys

from app.services.vector_search.backfill import run_heritage_backfill

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    report = run_heritage_backfill()
    # ensure_ascii=False so Korean source names + query strings stay
    # readable in operator terminals; indent=2 because the report is
    # small (per-source + per-namespace counts only) and operators
    # eyeball it directly.
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI entry
    sys.exit(main())
