from __future__ import annotations

from pydantic import BaseModel


class StructuredOutputModel(BaseModel):
    """Baseclass for JSON schema structured outputs."""


__all__ = ["StructuredOutputModel"]
