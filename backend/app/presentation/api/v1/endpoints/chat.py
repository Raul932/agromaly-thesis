"""
Router: Chat / RAG AI Agronomist
===================================
Endpoints:
    POST /api/v1/chat/ask                     — global agronomic chatbot
    POST /api/v1/chat/parcels/{parcel_id}/ask — parcel-specific Q&A

Both require JWT authentication.  If the RagService is not available (no
OpenAI key configured), both return HTTP 503.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.services.analysis_service import _compute_anomaly_score
from app.core.security import get_current_user
from app.domain.entities.user import User
from app.presentation.api.v1.dependencies import (
    get_ndvi_repo,
    get_parcel_repo,
    get_rag_service,
)
from app.presentation.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["Chat / RAG"])


def _raise_openai_error(exc: Exception) -> None:
    """Convert OpenAI API errors into clean HTTP responses."""
    name = type(exc).__name__
    msg = str(exc)
    if "insufficient_quota" in msg or "RateLimitError" in name:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI quota exceeded. Please add credits at platform.openai.com/settings/billing.",
        )
    if "AuthenticationError" in name or "invalid_api_key" in msg:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI API key is invalid.",
        )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"AI service error: {name}",
    )


@router.post(
    "/ask",
    response_model=ChatResponse,
    summary="Global agronomic chatbot",
    description=(
        "Ask any agricultural question. The RAG pipeline retrieves relevant "
        "excerpts from the knowledge base (PDF manuals) and uses gpt-4o-mini "
        "to generate an expert answer."
    ),
    responses={
        200: {"description": "Answer generated"},
        401: {"description": "Not authenticated"},
        503: {"description": "RAG service not available (no OpenAI key)"},
    },
)
async def ask_global(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    rag=Depends(get_rag_service),
) -> ChatResponse:
    if rag is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service is not available. OPENAI_API_KEY is not configured.",
        )

    history = [{"role": m.role, "content": m.content} for m in body.history]
    try:
        answer = await rag.answer_global(body.message, history)
    except Exception as exc:
        _raise_openai_error(exc)
    return ChatResponse(answer=answer)


@router.post(
    "/parcels/{parcel_id}/ask",
    response_model=ChatResponse,
    summary="Parcel-specific AI agronomist Q&A",
    description=(
        "Ask a question about a specific parcel. The system injects the parcel's "
        "current NDVI metrics, anomaly status, and recent weather into the LLM "
        "context so answers are tailored to that parcel's situation."
    ),
    responses={
        200: {"description": "Answer generated"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorised to access this parcel"},
        404: {"description": "Parcel not found"},
        503: {"description": "RAG service not available"},
    },
)
async def ask_parcel(
    parcel_id: uuid.UUID,
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    parcel_repo=Depends(get_parcel_repo),
    ndvi_repo=Depends(get_ndvi_repo),
    rag=Depends(get_rag_service),
) -> ChatResponse:
    if rag is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service is not available. OPENAI_API_KEY is not configured.",
        )

    # Ownership check
    parcel = await parcel_repo.get_by_id(parcel_id)
    if parcel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parcel not found.")
    if parcel.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    # Build parcel context from latest NDVI
    all_records = await ndvi_repo.list_by_parcel(parcel_id, limit=90)
    reliable = [r for r in all_records if r.is_reliable]
    total = len(all_records)

    if reliable:
        cloud_gap = (total - len(reliable)) / total if total > 0 else 0.0
        analysis = _compute_anomaly_score(reliable, cloud_gap)
        crop = getattr(parcel, "crop_type", "Unknown")
        parcel_context = {
            "name": parcel.name,
            "crop_type": crop.value if hasattr(crop, "value") else str(crop),
            "area_ha": round(getattr(parcel, "area_ha", 0) or 0, 2),
            "ndvi_current": analysis.get("ndvi_current"),
            "ndvi_mean": analysis.get("ndvi_mean"),
            "ndvi_std": analysis.get("ndvi_std"),
            "ndvi_trend": analysis.get("ndvi_trend"),
            "anomaly_score": analysis.get("anomaly_score"),
            "anomaly_status": analysis.get("status"),
        }
    else:
        crop = getattr(parcel, "crop_type", "Unknown")
        parcel_context = {
            "name": parcel.name,
            "crop_type": crop.value if hasattr(crop, "value") else str(crop),
            "area_ha": round(getattr(parcel, "area_ha", 0) or 0, 2),
            "ndvi_current": "N/A",
            "ndvi_mean": "N/A",
            "ndvi_std": "N/A",
            "ndvi_trend": "N/A",
            "anomaly_score": "N/A",
            "anomaly_status": "INSUFFICIENT_DATA",
        }

    history = [{"role": m.role, "content": m.content} for m in body.history]
    try:
        answer = await rag.answer_parcel(body.message, history, parcel_context)
    except Exception as exc:
        _raise_openai_error(exc)
    return ChatResponse(answer=answer)
