"""
Application Service: RagService
================================
RAG (Retrieval-Augmented Generation) pipeline backed by ChromaDB + OpenAI.

Three entry points:
    answer_global(question, history)
        General agronomic Q&A — no parcel context.  Used by the global chatbot.

    answer_parcel(question, history, parcel_context)
        Parcel-specific Q&A — pre-built parcel/NDVI/weather context dict
        injected into the system prompt.  Used by the bottom-sheet chat.

    generate_anomaly_recommendation(parcel_context, weather_summary)
        Called by the Celery anomaly task to produce the Alert.ai_recommendation.
        Returns a structured action-plan string.

Graceful degradation:
    If ChromaDB has no documents yet, the retriever returns an empty list
    and the LLM falls back to its pretrained agricultural knowledge.
    If OPENAI_API_KEY is missing, all methods raise RuntimeError so callers
    can return HTTP 503.

Singleton pattern (same as AnomalyDetector):
    Use get_rag_service() / initialize_rag_service() — never construct directly.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "agromaly_knowledge"
_RETRIEVER_K = 4

_GLOBAL_SYSTEM = """You are an expert AI agronomist for the Agromaly precision agriculture platform.
Your role is to help farmers understand crop health issues, diagnose problems, and take the right actions.
Answer clearly and concisely in 2-3 paragraphs. Use practical, actionable language.
Base your answers on the retrieved knowledge base excerpts and your expertise.
If the knowledge base contains relevant guidance, prioritise it.
Respond in the same language as the user's question (Romanian or English)."""

_PARCEL_SYSTEM = """You are an expert AI agronomist for the Agromaly precision agriculture platform.
You are advising a farmer about a SPECIFIC parcel. Use the parcel context below in your answer.

--- PARCEL CONTEXT ---
{context_block}
--- END CONTEXT ---

Answer in 2-3 paragraphs. Be specific — reference the NDVI values, anomaly status, and weather when relevant.
Respond in the same language as the user's question (Romanian or English)."""

_ANOMALY_SYSTEM = """You are an expert AI agronomist for the Agromaly precision agriculture platform.
A satellite anomaly has been detected on a farmer's parcel. Generate a structured action-plan recommendation.

--- PARCEL & ANOMALY CONTEXT ---
{context_block}
--- END CONTEXT ---

Write a 3-paragraph recommendation:
1. Assessment: What likely caused this anomaly (based on NDVI level, trend, and recent weather).
2. Immediate actions: What the farmer should do in the next 24-48 hours.
3. Follow-up: What to monitor over the next 2 weeks.

Be specific, practical, and reference the actual data values. Respond in Romanian."""


class RagService:
    """Singleton RAG service — load once at startup via initialize_rag_service()."""

    def __init__(
        self,
        chroma_dir: str,
        openai_api_key: str,
        embedding_model: str = "text-embedding-3-small",
        chat_model: str = "gpt-4o-mini",
        collection_name: str = _COLLECTION_NAME,
    ) -> None:
        from langchain_chroma import Chroma
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings

        self._chat_model = chat_model
        self._openai_api_key = openai_api_key

        embeddings = OpenAIEmbeddings(
            model=embedding_model,
            openai_api_key=openai_api_key,
        )

        self._llm = ChatOpenAI(
            model=chat_model,
            temperature=0.3,
            openai_api_key=openai_api_key,
        )

        # Connect to existing ChromaDB (do not recreate — that's the ingestor's job)
        import chromadb
        client = chromadb.PersistentClient(path=chroma_dir)

        self._vectorstore = Chroma(
            client=client,
            collection_name=collection_name,
            embedding_function=embeddings,
        )

        # Retriever — returns up to k relevant chunks
        self._retriever = self._vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": _RETRIEVER_K},
        )

        logger.info(
            "RagService initialized (model=%s, chroma=%s, collection=%s)",
            chat_model, chroma_dir, collection_name,
        )

    def is_knowledge_base_empty(self) -> bool:
        """Return True if ChromaDB collection has no documents."""
        try:
            return self._vectorstore._collection.count() == 0
        except Exception:
            return True

    async def answer_global(
        self,
        question: str,
        history: list[dict],
    ) -> str:
        """Answer a general agronomic question using the knowledge base.

        Args:
            question: The user's question text.
            history:  Conversation history as list of {"role": str, "content": str}.

        Returns:
            LLM answer string.
        """
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_core.output_parsers import StrOutputParser

        docs = await self._retriever.ainvoke(question)
        context = _format_docs(docs)

        messages = [SystemMessage(content=_GLOBAL_SYSTEM)]
        if context:
            messages.append(HumanMessage(content=f"Relevant knowledge base excerpts:\n{context}"))
        for msg in history[-6:]:  # last 3 turns
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))
        messages.append(HumanMessage(content=question))

        parser = StrOutputParser()
        response = await (self._llm | parser).ainvoke(messages)
        return response

    async def answer_parcel(
        self,
        question: str,
        history: list[dict],
        parcel_context: dict,
    ) -> str:
        """Answer a question scoped to a specific parcel.

        Args:
            question:       The user's question text.
            history:        Conversation history as list of {"role": str, "content": str}.
            parcel_context: Dict with keys: name, crop_type, area_ha, ndvi_current,
                            ndvi_mean, ndvi_std, ndvi_trend, anomaly_score,
                            anomaly_status, weather_summary (optional).

        Returns:
            LLM answer string.
        """
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_core.output_parsers import StrOutputParser

        docs = await self._retriever.ainvoke(question)
        context_block = _build_parcel_context_block(parcel_context)
        kb_context = _format_docs(docs)

        system_prompt = _PARCEL_SYSTEM.format(context_block=context_block)
        messages = [SystemMessage(content=system_prompt)]
        if kb_context:
            messages.append(HumanMessage(content=f"Relevant knowledge base excerpts:\n{kb_context}"))
        for msg in history[-6:]:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))
        messages.append(HumanMessage(content=question))

        parser = StrOutputParser()
        return await (self._llm | parser).ainvoke(messages)

    async def generate_anomaly_recommendation(
        self,
        parcel_context: dict,
        weather_summary: dict,
    ) -> str:
        """Generate a structured recommendation for an anomaly alert.

        Args:
            parcel_context: Dict with parcel/NDVI fields (same as answer_parcel).
            weather_summary: Dict with last-30-day weather (temp_min/max, precip, etc.).

        Returns:
            Formatted recommendation string (stored in Alert.ai_recommendation).
        """
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_core.output_parsers import StrOutputParser

        context_block = _build_parcel_context_block(parcel_context)
        if weather_summary:
            weather_lines = "\n".join(f"  {k}: {v}" for k, v in weather_summary.items())
            context_block += f"\n\nWeather (last 30 days):\n{weather_lines}"

        # Retrieve relevant knowledge
        query = (
            f"NDVI anomaly {parcel_context.get('crop_type', 'crop')} "
            f"NDVI={parcel_context.get('ndvi_current', 'low'):.3f} "
            f"treatment recommendation"
        )
        docs = await self._retriever.ainvoke(query)
        kb_context = _format_docs(docs)

        system_prompt = _ANOMALY_SYSTEM.format(context_block=context_block)
        messages = [SystemMessage(content=system_prompt)]
        if kb_context:
            messages.append(HumanMessage(content=f"Relevant knowledge base excerpts:\n{kb_context}"))
        messages.append(HumanMessage(
            content="Generate the anomaly recommendation report now."
        ))

        parser = StrOutputParser()
        return await (self._llm | parser).ainvoke(messages)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _format_docs(docs: list) -> str:
    if not docs:
        return ""
    parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source", "unknown")
        parts.append(f"[{i}] {source}\n{doc.page_content}")
    return "\n\n".join(parts)


def _build_parcel_context_block(ctx: dict) -> str:
    lines = [
        f"Parcel name: {ctx.get('name', 'N/A')}",
        f"Crop type: {ctx.get('crop_type', 'Unknown')}",
        f"Area: {ctx.get('area_ha', 'N/A')} ha",
        f"Current NDVI: {ctx.get('ndvi_current', 'N/A')}",
        f"Historical mean NDVI: {ctx.get('ndvi_mean', 'N/A')}",
        f"NDVI std deviation: {ctx.get('ndvi_std', 'N/A')}",
        f"NDVI trend (slope): {ctx.get('ndvi_trend', 'N/A')}",
        f"Anomaly score: {ctx.get('anomaly_score', 'N/A')} (0=healthy, 1=severe)",
        f"Anomaly status: {ctx.get('anomaly_status', 'N/A')}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_rag_instance: Optional[RagService] = None


def get_rag_service() -> Optional[RagService]:
    """Return the singleton RagService, or None if not initialized."""
    return _rag_instance


def initialize_rag_service() -> Optional[RagService]:
    """Initialize the singleton RagService from application settings.

    Called once in the FastAPI lifespan startup block.
    Returns None (and logs a warning) if OPENAI_API_KEY is not set.
    """
    global _rag_instance

    if _rag_instance is not None:
        return _rag_instance

    try:
        from app.core.config import settings

        if not settings.OPENAI_API_KEY:
            logger.warning(
                "OPENAI_API_KEY is not set — RagService will not be available. "
                "Chat and RAG recommendation endpoints will return HTTP 503."
            )
            return None

        _rag_instance = RagService(
            chroma_dir=settings.CHROMA_PERSIST_DIRECTORY,
            openai_api_key=settings.OPENAI_API_KEY,
            embedding_model=settings.OPENAI_EMBEDDING_MODEL,
            chat_model=settings.OPENAI_CHAT_MODEL,
        )
        return _rag_instance

    except Exception as exc:
        logger.error("Failed to initialize RagService: %s", exc, exc_info=True)
        return None
