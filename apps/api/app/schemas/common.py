"""Common schema types."""

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    error: str
    message: str
    status: int
