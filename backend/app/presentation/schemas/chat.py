"""Pydantic schemas for the Chat / RAG endpoints."""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """A single turn in the conversation history."""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """Request body for POST /chat/ask and POST /chat/parcels/{id}/ask."""

    message: str = Field(..., min_length=1, max_length=2000)
    history: List[ChatMessage] = Field(default_factory=list, max_length=20)


class ChatResponse(BaseModel):
    """Response body for all chat endpoints."""

    answer: str
