"""Admin review queue endpoints (spec section 8.2)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_admin
from app.db.session import get_db
from app.jobs.refresh_trends import refresh_trends
from app.models.recipe import Recipe, RecipeStatus
from app.models.user import User
from app.schemas.recipe import RecipeListItem, RecipeStatusUpdate
from app.schemas.trend import TrendDebugResponse, TrendRefreshResponse
from app.services.trends import TrendsAdapterError, get_trend_discovery
from app.services.trends.debug import build_debug_response

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/recipes", response_model=list[RecipeListItem])
def list_pending_recipes(
    status_filter: RecipeStatus = RecipeStatus.PENDING_REVIEW,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[RecipeListItem]:
    _ = admin
    rows = (
        db.query(Recipe)
        .filter(Recipe.status == status_filter)
        .order_by(Recipe.created_at.desc())
        .all()
    )
    return [RecipeListItem.model_validate(r) for r in rows]


@router.post("/recipes/{recipe_id}/status", response_model=RecipeListItem)
def update_recipe_status(
    recipe_id: str,
    payload: RecipeStatusUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> RecipeListItem:
    _ = admin
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "RECIPE_NOT_FOUND",
                "message": "Recipe does not exist.",
                "status": 404,
            },
        )
    if payload.status == RecipeStatus.REJECTED and not payload.rejection_reason.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "REJECTION_REASON_REQUIRED",
                "message": "Rejection requires a non-empty reason for user feedback.",
                "status": 400,
            },
        )
    recipe.status = payload.status
    # Keep the existing reason on non-rejection transitions so admins can
    # demote / re-flag without wiping the previously recorded reason.
    if payload.status == RecipeStatus.REJECTED:
        recipe.rejection_reason = payload.rejection_reason.strip()
    elif payload.rejection_reason:
        recipe.rejection_reason = payload.rejection_reason.strip()
    db.commit()
    db.refresh(recipe)
    return RecipeListItem.model_validate(recipe)


@router.post("/trends/refresh", response_model=TrendRefreshResponse)
def refresh_trends_endpoint(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> TrendRefreshResponse:
    """Trigger a one-shot refresh of the weekly trend snapshot.

    Wraps ``app.jobs.refresh_trends.refresh_trends`` so the configured
    ``TrendsAdapter`` decides where the data comes from (mock in dev/CI,
    Naver DataLab when ``TRENDS_PROVIDER=live``).
    """
    _ = admin
    try:
        result = refresh_trends(db)
    except TrendsAdapterError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "TRENDS_UPSTREAM_ERROR",
                "message": str(exc),
                "status": 502,
            },
        ) from exc
    return TrendRefreshResponse(
        week_of=result.week_of,
        inserted=result.inserted,
        updated=result.updated,
    )


@router.get("/trends/debug", response_model=TrendDebugResponse)
def trends_debug_endpoint(
    today: date | None = Query(
        default=None,
        description="Reference date (defaults to today). Useful for back-testing.",
    ),
    limit: int = Query(default=20, ge=1, le=200),
    admin: User = Depends(get_current_admin),
) -> TrendDebugResponse:
    """Return a per-source breakdown of the currently configured discovery.

    For ``TRENDS_DISCOVERY_SOURCE=open`` (``MultiSourceDiscovery``) this is
    the *interesting* view: one provider row per registered source (static,
    google_trends_daily, naver_news, llm_expansion) with raw candidate
    count + sample + elapsed ms + error text, plus the merged ranked
    top-N where each entry lists *all* sources that emitted it (not just
    first-emitter attribution). For ``curated`` / ``shopping_insight`` we
    synthesize one provider row from the ranked output.
    """
    _ = admin
    try:
        discovery = get_trend_discovery()
    except TrendsAdapterError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "TRENDS_UPSTREAM_ERROR",
                "message": str(exc),
                "status": 502,
            },
        ) from exc
    return build_debug_response(discovery, today=today, limit=limit)
