"""Admin review queue endpoints (spec section 8.2)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_admin
from app.db.session import get_db
from app.models.recipe import Recipe, RecipeStatus
from app.models.user import User
from app.schemas.recipe import RecipeListItem, RecipeStatusUpdate

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
    recipe.status = payload.status
    recipe.rejection_reason = payload.rejection_reason or ""
    db.commit()
    db.refresh(recipe)
    return RecipeListItem.model_validate(recipe)
