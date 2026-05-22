"""Heritage document schemas."""

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    institution: str
    region: str
    period: str
    category: str
    year: int | None
    summary: str
    license: str


class DocumentMatch(BaseModel):
    """A document returned by vector/keyword search, paired with a match score."""

    document: DocumentOut
    match_score: float
