"""Recipe schemas covering the generate → review → publish lifecycle."""

from pydantic import BaseModel, ConfigDict, Field

from app.models.recipe import RecipeStatus
from app.schemas.document import DocumentMatch


class IngredientLine(BaseModel):
    name: str
    amount: str
    note: str = ""


class RecipeStep(BaseModel):
    title: str
    description: str
    waiting: bool = False


class RecipeGenerateRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=120)
    region: str = Field(min_length=1, max_length=60)
    diet: str = Field(default="제한 없음", max_length=60)
    menu_type: str = Field(min_length=1, max_length=60)
    document_id: str | None = None


class RecipeCandidate(BaseModel):
    """A single AI-generated recipe candidate (3 are returned per generate call)."""

    id: str
    name: str
    description: str
    tags: list[str]
    difficulty: str
    time_minutes: int
    estimated_cost_krw: int
    source_attribution: str
    is_recommended: bool
    image_url: str = ""
    status: RecipeStatus


class RecipeGenerateResponse(BaseModel):
    candidates: list[RecipeCandidate]
    matched_documents: list[DocumentMatch]


class RecipeListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    region: str
    era: str
    keyword: str
    status: RecipeStatus
    is_recommended: bool
    image_url: str
    estimated_cost_krw: int
    time_minutes: int
    rating: int = 0
    is_selling: bool = False
    rejection_reason: str = ""


class RecipeDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    region: str
    era: str
    diet: str
    menu_type: str
    keyword: str
    difficulty: str
    time_minutes: int
    servings: int
    estimated_cost_krw: int
    estimated_price_krw: int
    steps: list[RecipeStep]
    ingredients: list[IngredientLine]
    sns_caption: str
    image_url: str
    source_attribution: str
    status: RecipeStatus
    is_recommended: bool
    rating: int
    is_selling: bool
    rejection_reason: str = ""
    source_document: dict | None = None


class RecipeUpdateRequest(BaseModel):
    """Owner-editable fields on an existing recipe (star rating, sale toggle)."""

    rating: int | None = Field(default=None, ge=0, le=5)
    is_selling: bool | None = None


class RecipeStatusUpdate(BaseModel):
    status: RecipeStatus
    rejection_reason: str = ""
