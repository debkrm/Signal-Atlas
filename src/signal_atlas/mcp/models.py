"""
models.py - Standard Response Envelope and Domain Models for Signal Atlas FastMCP Server.
"""

import datetime
from typing import Any, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class MCPResponseEnvelope(BaseModel, Generic[T]):
    """
    Standard envelope enforced across all Signal Atlas MCP tools per Architecture Section 14.
    """
    as_of: str = Field(description="Market date to which the data or analysis applies (YYYY-MM-DD)")
    retrieved_at: str = Field(description="ISO-8601 UTC timestamp when this response was generated")
    source: str = Field(default="NSE / Signal Atlas Core", description="Primary data source and calculation engine")
    data_status: str = Field(description="Status classification: FRESH, STALE, RESTRICTED, DATA_NOT_AVAILABLE")
    warnings: List[str] = Field(default_factory=list, description="Advisory or non-blocking warnings")
    result: T = Field(description="Domain-specific structured result payload")

    @classmethod
    def create(
        cls,
        as_of: str,
        result: T,
        data_status: str = "FRESH",
        warnings: Optional[List[str]] = None,
        source: str = "NSE / Signal Atlas Core",
    ) -> "MCPResponseEnvelope[T]":
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return cls(
            as_of=as_of,
            retrieved_at=now_utc,
            source=source,
            data_status=data_status,
            warnings=warnings or [],
            result=result,
        )
