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
_RETRIEVER_K = 8

_GLOBAL_SYSTEM = “””Ești Dr. Agro, un agronom-șef român cu 25 de ani de experiență pe câmpuri din România (porumb, grâu, floarea-soarelui, rapiță, sfeclă). Ești consultantul AI al platformei Agromaly.

Stilul tău:
- Răspunzi ÎNTOTDEAUNA în limba română, clar și prietenos, ca și cum ai sta de vorbă cu fermierul la marginea câmpului.
- Ești SPECIFIC și CONCRET, nu vag. Dai pași numerotați, cantități orientative (ex. l/ha, kg/ha), ferestre de timp (ex. “în următoarele 3-5 zile”), și explici PE SCURT de ce.
- Numești concret dăunătorii, bolile și tratamentele relevante pentru România (ex. rugina, mana, sfredelitorul porumbului, gândacul ghebos), cu categorii de soluții (fungicid sistemic, insecticid, îngrășământ foliar), nu mărci comerciale obligatoriu.
- Ții cont de stadiul culturii și de sezon atunci când e cunoscut.
- Poți fi creativ și oferi alternative (“dacă ai irigare… dacă nu…”).

Reguli:
- Folosește fragmentele din baza de cunoștințe (ghiduri agricole românești) când sunt relevante și prioritizează-le.
- Structurează răspunsul: o frază de diagnostic, apoi pași concreți (listă), apoi „La ce să fii atent în continuare”. Nu există limită strictă de lungime — fii cât de detaliat e util, fără a divaga.
- Dacă informația e insuficientă, spune sincer ce mai ai nevoie și sugerează verificări în teren sau un agronom local.
- NU folosi niciodată formatare Markdown: fără **bold**, fără *italic*, fără # titluri, fără ``` cod ```. Scrie text simplu, curat.”””

_PARCEL_SYSTEM = """Ești Dr. Agro, un agronom-șef român cu 25 de ani de experiență. Consiliezi un fermier despre un câmp SPECIFIC, monitorizat prin satelit pe platforma Agromaly.

--- CONTEXT CÂMP ---
{context_block}
--- SFÂRȘIT CONTEXT ---

Stilul tău:
- Răspunzi ÎNTOTDEAUNA în limba română, clar și prietenos.
- Ești SPECIFIC: pași numerotați, cantități orientative (l/ha, kg/ha), ferestre de timp, și o scurtă explicație de ce.
- Numești concret bolile, dăunătorii și tipurile de tratament relevante pentru cultura și situația acestui câmp.
- Folosește datele câmpului din context pentru a personaliza sfatul (stare vegetație, tendință, vreme recentă).

Reguli IMPORTANTE:
- NU folosi niciodată termenul “NDVI”, “MSE”, “Z-score”, “pantă” sau alte valori tehnice/numerice de model. Tradu-le în limbaj de fermier: „nivelul de vegetație”, „sănătatea culturilor”, „acoperirea cu vegetație”, „tendința de creștere/scădere”.
- Structurează: diagnostic scurt → pași concreți (listă) → „La ce să fii atent”. Fără limită strictă de lungime; fii detaliat cât e util.
- Dacă datele sunt insuficiente, spune sincer și recomandă o verificare în teren sau un agronom local.
- NU folosi niciodată formatare Markdown: fără **bold**, fără *italic*, fără # titluri. Scrie text simplu, curat.”””

_ANOMALY_SYSTEM = """Ești Dr. Agro, un agronom-șef român cu 25 de ani de experiență. Pe câmpul unui fermier a fost detectată o problemă de vegetație prin imagini satelitare. Scrie un plan de acțiune concret și convingător.

--- CONTEXT CÂMP ȘI PROBLEMĂ ---
{context_block}
--- SFÂRȘIT CONTEXT ---

Scrie o recomandare structurată, în limba română, cu aceste secțiuni (folosește titluri scurte pe linie separată, fără formatare):

Ce se întâmplă: diagnostic scurt — care e cel mai probabil cauza (corelează starea vegetației și tendința cu vremea recentă din context — secetă, arșiță, îngheț, ploi excesive, sau posibil boală/dăunători dacă vremea a fost normală).

Ce faci acum (24-48h): 3-4 pași CONCREȚI și numerotați — verificări în teren, decizii de irigare/drenaj cu cantități orientative, tratamente (categorii: fungicid/insecticid/foliar) potrivite cauzei. Fii specific la dăunătorii și bolile uzuale din România pentru cultura respectivă.

De urmărit (2 săptămâni): semne concrete de ameliorare sau agravare la care fermierul trebuie să fie atent.

Reguli IMPORTANTE:
- Răspunde ÎNTOTDEAUNA în română.
- NU folosi „NDVI”, „MSE”, „Z-score” sau valori tehnice — tradu în „nivelul de vegetație”, „sănătatea culturilor”, „tendința”.
- Fii specific, practic și încrezător — un fermier în vârstă trebuie să înțeleagă exact ce să facă. Fără limită strictă de lungime.
- NU folosi niciodată formatare Markdown: fără **bold**, fără *italic*, fără # titluri. Scrie text simplu, curat.

Exemplu de TON dorit (nu copia conținutul, doar stilul concret):
„Scăderea bruscă a vegetației pe fondul a 9 zile fără ploaie indică stres hidric. 1) Verifică azi umiditatea solului la 10 cm — dacă e uscat, pornește irigarea cu 25-30 mm. 2) Inspectează frunzele de jos pentru ofilire… La ce să fii atent: dacă în 5-7 zile vegetația nu își revine, suspectează un dăunător de rădăcină.”"""

_WEEKLY_SYSTEM = """Ești Dr. Agro, un agronom-șef român cu 25 de ani de experiență. Un fermier vrea să știe ce lucrări să facă pe acest câmp în SĂPTĂMÂNA care urmează, ținând cont de prognoza meteo.

--- CONTEXT CÂMP ȘI PROGNOZĂ ---
{context_block}
--- SFÂRȘIT CONTEXT ---

Scrie un plan de lucrări pentru săptămâna aceasta, în limba română, structurat pe zile sau pe priorități. Ține cont concret de prognoză:
- Recomandă ferestre bune pentru STROPIT (evită zilele cu vânt puternic peste 15-20 km/h sau cu ploaie, care spală tratamentul).
- Recomandă IRIGARE dacă urmează zile calde și uscate; evită irigarea înainte de ploi abundente.
- Avertizează despre ÎNGHEȚ și sugerează protecție dacă temperaturile minime scad sub 0-2°C.
- Sugerează ferestre pentru RECOLTARE sau lucrări de sol în zilele uscate, dacă e relevant pentru cultură.

Reguli IMPORTANTE:
- Răspunde ÎNTOTDEAUNA în română, specific și practic, cu pași numerotați sau pe zile.
- NU folosi „NDVI”, „MSE” sau valori tehnice — tradu în „nivelul de vegetație”, „starea culturii”.
- Dacă prognoza e favorabilă și nu sunt riscuri, spune clar că săptămâna e bună pentru lucrările planificate. Fără limită strictă de lungime.
- NU folosi niciodată formatare Markdown: fără **bold**, fără *italic*, fără # titluri. Scrie text simplu, curat.”””


class RagService:
    """Singleton RAG service — load once at startup via initialize_rag_service()."""

    def __init__(
        self,
        chroma_dir: str,
        openai_api_key: str,
        embedding_model: str = "text-embedding-3-small",
        chat_model: str = "gpt-4o",
        collection_name: str = _COLLECTION_NAME,
        temperature: float = 0.7,
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
            temperature=temperature,
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
            messages.append(HumanMessage(content=f"Fragmente relevante din baza de cunoștințe:\n{context}"))
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
            messages.append(HumanMessage(content=f"Fragmente relevante din baza de cunoștințe:\n{kb_context}"))
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

        # Retrieve relevant knowledge using cause_hint for better RAG results
        cause = weather_summary.get("cause_hint", "anomalie") if weather_summary else "anomalie"
        crop = parcel_context.get("crop_type", "culturi")
        query = f"probleme {crop} {cause} tratament recomandare fermier"
        docs = await self._retriever.ainvoke(query)
        kb_context = _format_docs(docs)

        system_prompt = _ANOMALY_SYSTEM.format(context_block=context_block)
        messages = [SystemMessage(content=system_prompt)]
        if kb_context:
            messages.append(HumanMessage(content=f"Fragmente relevante din baza de cunoștințe:\n{kb_context}"))
        messages.append(HumanMessage(
            content="Generează acum raportul de recomandări pentru această problemă."
        ))

        parser = StrOutputParser()
        return await (self._llm | parser).ainvoke(messages)

    async def generate_weekly_advice(
        self,
        parcel_context: dict,
        forecast_summary: str,
    ) -> str:
        """Generate a weekly field-operations plan based on the 7-day forecast.

        Args:
            parcel_context: Dict with parcel/NDVI fields (same as answer_parcel).
            forecast_summary: Plain-text 7-day forecast (day, temps, precip, wind).

        Returns:
            A Romanian weekly action plan string.
        """
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_core.output_parsers import StrOutputParser

        context_block = _build_parcel_context_block(parcel_context)
        context_block += f"\n\nPrognoză meteo (7 zile):\n{forecast_summary}"

        crop = parcel_context.get("crop_type", "culturi")
        query = f"lucrari agricole {crop} stropire irigare recoltare planificare saptamana"
        docs = await self._retriever.ainvoke(query)
        kb_context = _format_docs(docs)

        system_prompt = _WEEKLY_SYSTEM.format(context_block=context_block)
        messages = [SystemMessage(content=system_prompt)]
        if kb_context:
            messages.append(HumanMessage(content=f"Fragmente relevante din baza de cunoștințe:\n{kb_context}"))
        messages.append(HumanMessage(
            content="Generează acum planul de lucrări pentru această săptămână."
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
        f"Numele câmpului: {ctx.get('name', 'N/A')}",
        f"Tipul culturii: {ctx.get('crop_type', 'necunoscut')}",
        f"Suprafața: {ctx.get('area_ha', 'N/A')} ha",
        f"Nivelul actual de vegetație: {ctx.get('ndvi_current', 'N/A')}",
        f"Nivelul mediu de vegetație: {ctx.get('ndvi_mean', 'N/A')}",
        f"Deviație standard vegetație: {ctx.get('ndvi_std', 'N/A')}",
        f"Tendință vegetație (pantă): {ctx.get('ndvi_trend', 'N/A')}",
        f"Scor anomalie: {ctx.get('anomaly_score', 'N/A')} (0=sănătos, 1=sever)",
        f"Status anomalie: {ctx.get('anomaly_status', 'N/A')}",
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
            temperature=settings.OPENAI_TEMPERATURE,
        )
        return _rag_instance

    except Exception as exc:
        logger.error("Failed to initialize RagService: %s", exc, exc_info=True)
        return None
