"""Recipe generation + CRUD endpoints (spec FR-03 / 5.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.config import get_settings
from app.db.session import get_db
from app.models.ingredient import Ingredient, RecipeIngredient
from app.models.recipe import Recipe, RecipeStatus
from app.models.subscription import Plan
from app.models.user import User
from app.schemas.document import DocumentMatch as DocumentMatchSchema
from app.schemas.document import DocumentOut
from app.schemas.recipe import (
    IngredientLine,
    RecipeCandidate,
    RecipeDetailOut,
    RecipeGenerateRequest,
    RecipeGenerateResponse,
    RecipeListItem,
    RecipeStep,
)
from app.services.heritage import get_heritage_adapter
from app.services.llm import get_llm_adapter
from app.services.llm.base import GenerateRecipesInput
from app.services.pdf import render_certificate_pdf, render_recipe_pdf

router = APIRouter(prefix="/private/recipes", tags=["recipes"])


@router.post("/generate", response_model=RecipeGenerateResponse)
def generate_recipes(
    payload: RecipeGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeGenerateResponse:
    _enforce_quota(current_user)

    heritage = get_heritage_adapter()
    matches = heritage.search(keyword=payload.keyword, region=payload.region, limit=3)

    matched_docs_payload = [
        {
            "title": m.document.title,
            "institution": m.document.institution,
            "region": m.document.region,
            "period": m.document.period,
            "year": m.document.year,
            "summary": m.document.summary,
        }
        for m in matches
    ]

    llm = get_llm_adapter()
    candidates = llm.generate_recipes(
        GenerateRecipesInput(
            keyword=payload.keyword,
            region=payload.region,
            diet=payload.diet,
            menu_type=payload.menu_type,
            matched_documents=matched_docs_payload,
        )
    )

    # Persist candidate recipes (status=pending_review per spec 8.2.4)
    persisted: list[Recipe] = []
    for c in candidates:
        recipe = Recipe(
            user_id=current_user.id,
            name=c.name,
            description=c.description,
            region=c.region,
            era=c.era,
            diet=c.diet,
            menu_type=c.menu_type,
            keyword=c.keyword,
            difficulty=c.difficulty,
            time_minutes=c.time_minutes,
            servings=c.servings,
            estimated_cost_krw=c.estimated_cost_krw,
            estimated_price_krw=c.estimated_price_krw,
            steps=[step.__dict__ for step in c.steps],
            sns_caption=c.sns_caption,
            image_url=c.image_url,
            source_attribution=c.source_attribution,
            is_recommended=c.is_recommended,
            status=RecipeStatus.PENDING_REVIEW,
        )
        # Attach ingredients
        for sort_order, ing in enumerate(c.ingredients):
            ingredient = db.query(Ingredient).filter(Ingredient.name == ing.name).one_or_none()
            if ingredient is None:
                ingredient = Ingredient(name=ing.name)
                db.add(ingredient)
                db.flush()
            recipe.ingredients.append(
                RecipeIngredient(
                    ingredient=ingredient, amount=ing.amount, note=ing.note, sort_order=sort_order
                )
            )
        db.add(recipe)
        persisted.append(recipe)

    # Increment usage counter (free plan only)
    if current_user.subscription and current_user.subscription.plan == Plan.FREE:
        current_user.subscription.monthly_recipe_count += 1

    db.commit()
    for r in persisted:
        db.refresh(r)

    # Build response
    response_candidates = [
        RecipeCandidate(
            id=r.id,
            name=r.name,
            description=r.description,
            tags=[r.region, r.era, r.diet] if r.diet else [r.region, r.era],
            difficulty=r.difficulty,
            time_minutes=r.time_minutes,
            estimated_cost_krw=r.estimated_cost_krw,
            source_attribution=r.source_attribution,
            is_recommended=r.is_recommended,
            image_url=r.image_url,
            status=r.status,
        )
        for r in persisted
    ]
    matched_docs = [
        DocumentMatchSchema(
            document=DocumentOut(
                id=m.document.external_id,
                title=m.document.title,
                institution=m.document.institution,
                region=m.document.region,
                period=m.document.period,
                category=m.document.category,
                year=m.document.year,
                summary=m.document.summary,
                license=m.document.license,
            ),
            match_score=m.match_score,
        )
        for m in matches
    ]
    return RecipeGenerateResponse(candidates=response_candidates, matched_documents=matched_docs)


@router.get("", response_model=list[RecipeListItem])
def list_my_recipes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RecipeListItem]:
    rows = (
        db.query(Recipe)
        .filter(Recipe.user_id == current_user.id)
        .order_by(Recipe.created_at.desc())
        .all()
    )
    return [RecipeListItem.model_validate(r) for r in rows]


@router.get("/{recipe_id}", response_model=RecipeDetailOut)
def get_recipe(
    recipe_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeDetailOut:
    recipe = _get_owned_recipe(db, recipe_id, current_user)
    return _to_detail(recipe)


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipe(
    recipe_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    recipe = _get_owned_recipe(db, recipe_id, current_user)
    db.delete(recipe)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{recipe_id}/export/pdf")
def export_recipe_pdf(
    recipe_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    recipe = _get_owned_recipe(db, recipe_id, current_user)
    watermark = current_user.subscription is None or current_user.subscription.plan == Plan.FREE
    pdf = render_recipe_pdf(recipe, watermark=watermark)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{recipe.id}.pdf"'},
    )


@router.get("/{recipe_id}/certificate")
def export_certificate(
    recipe_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    if current_user.subscription is None or current_user.subscription.plan == Plan.FREE:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "PLAN_REQUIRED",
                "message": "Certificate is available on Pro / B2B plans only.",
                "status": 402,
            },
        )
    recipe = _get_owned_recipe(db, recipe_id, current_user)
    pdf = render_certificate_pdf(recipe)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{recipe.id}-certificate.pdf"'},
    )


# -------- helpers --------


def _enforce_quota(user: User) -> None:
    settings = get_settings()
    if user.subscription is None:
        return
    if user.subscription.plan == Plan.FREE:
        if user.subscription.monthly_recipe_count >= settings.free_plan_monthly_recipe_quota:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "RECIPE_QUOTA_EXCEEDED",
                    "message": "Free plan limited to 3 recipes per month. Upgrade to Pro.",
                    "status": 429,
                },
            )


def _get_owned_recipe(db: Session, recipe_id: str, user: User) -> Recipe:
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "RECIPE_NOT_FOUND",
                "message": "Recipe does not exist or does not belong to current user.",
                "status": 404,
            },
        )
    return recipe


def _to_detail(recipe: Recipe) -> RecipeDetailOut:
    return RecipeDetailOut(
        id=recipe.id,
        name=recipe.name,
        description=recipe.description,
        region=recipe.region,
        era=recipe.era,
        diet=recipe.diet,
        menu_type=recipe.menu_type,
        keyword=recipe.keyword,
        difficulty=recipe.difficulty,
        time_minutes=recipe.time_minutes,
        servings=recipe.servings,
        estimated_cost_krw=recipe.estimated_cost_krw,
        estimated_price_krw=recipe.estimated_price_krw,
        steps=[
            RecipeStep(**s)
            if isinstance(s, dict)
            else RecipeStep(title=s.title, description=s.description)
            for s in (recipe.steps or [])
        ],
        ingredients=[
            IngredientLine(name=ri.ingredient.name, amount=ri.amount, note=ri.note)
            for ri in sorted(recipe.ingredients, key=lambda r: r.sort_order)
        ],
        sns_caption=recipe.sns_caption,
        image_url=recipe.image_url,
        source_attribution=recipe.source_attribution,
        status=recipe.status,
        is_recommended=recipe.is_recommended,
        rating=recipe.rating,
        is_selling=recipe.is_selling,
        source_document=None,
    )
