"""
Knowledge Base Ingestion Script
=================================
Loads all PDFs from ``backend/data/knowledge_base/``, chunks and embeds them,
then persists into the ChromaDB vector store at ``backend/data/chroma``.

Idempotent: if the collection already has documents, this is a no-op
(unless ``--force`` is passed to re-ingest even if the collection is populated).

Usage:
    # From repo root:
    python backend/scripts/ingest_knowledge_base.py

    # Force re-ingestion (deletes existing collection first):
    python backend/scripts/ingest_knowledge_base.py --force

    # Custom paths:
    python backend/scripts/ingest_knowledge_base.py \\
        --pdf-dir backend/data/knowledge_base \\
        --chroma-dir backend/data/chroma \\
        --collection agromaly_knowledge
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("ingest_knowledge_base")

COLLECTION_NAME = "agromaly_knowledge"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


def ingest(
    chroma_dir: str,
    pdf_dir: str,
    collection_name: str = COLLECTION_NAME,
    force: bool = False,
) -> int:
    """Ingest PDFs into ChromaDB.

    Args:
        chroma_dir:       Path to persist the ChromaDB vector store.
        pdf_dir:          Directory containing ``*.pdf`` files.
        collection_name:  Name of the ChromaDB collection.
        force:            If True, delete and recreate the collection.

    Returns:
        Number of document chunks ingested (0 if skipped).
    """
    import chromadb
    from langchain_chroma import Chroma
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_openai import OpenAIEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    # Load settings for OpenAI key
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from app.core.config import settings
        openai_api_key = settings.OPENAI_API_KEY
        embedding_model = settings.OPENAI_EMBEDDING_MODEL
    except Exception:
        import os
        openai_api_key = os.getenv("OPENAI_API_KEY", "")
        embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    if not openai_api_key:
        logger.error("OPENAI_API_KEY is not set — cannot create embeddings.")
        return 0

    pdf_path = Path(pdf_dir)
    chroma_path = Path(chroma_dir)
    chroma_path.mkdir(parents=True, exist_ok=True)

    # Check if collection already has documents
    client = chromadb.PersistentClient(path=str(chroma_path))

    if force:
        try:
            client.delete_collection(collection_name)
            logger.info("Deleted existing collection '%s' (force mode).", collection_name)
        except Exception:
            pass

    try:
        collection = client.get_collection(collection_name)
        count = collection.count()
        if count > 0 and not force:
            logger.info(
                "Collection '%s' already has %d chunks — skipping ingestion.",
                collection_name, count,
            )
            return 0
    except Exception:
        pass  # Collection doesn't exist yet — will be created by Chroma below

    # Discover PDFs
    pdf_files = sorted(pdf_path.glob("*.pdf"))
    if not pdf_files:
        logger.warning("No PDF files found in '%s'. Nothing to ingest.", pdf_dir)
        return 0

    logger.info("Found %d PDF file(s) to ingest.", len(pdf_files))

    # Load and chunk
    all_docs = []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    for pdf_file in pdf_files:
        logger.info("Loading: %s", pdf_file.name)
        try:
            loader = PyPDFLoader(str(pdf_file))
            pages = loader.load()
            chunks = splitter.split_documents(pages)
            all_docs.extend(chunks)
            logger.info("  %d pages -> %d chunks", len(pages), len(chunks))
        except Exception as e:
            logger.error("Failed to load '%s': %s", pdf_file.name, e)

    if not all_docs:
        logger.warning("No document chunks produced — nothing to ingest.")
        return 0

    # Embed and persist
    logger.info("Embedding %d chunks with model '%s'...", len(all_docs), embedding_model)
    embeddings = OpenAIEmbeddings(
        model=embedding_model,
        openai_api_key=openai_api_key,
        chunk_size=200,  # max documents per embedding API call (~50k tokens/batch)
    )

    Chroma.from_documents(
        documents=all_docs,
        embedding=embeddings,
        collection_name=collection_name,
        persist_directory=str(chroma_path),
        client=chromadb.PersistentClient(path=str(chroma_path)),
    )

    logger.info("Ingestion complete — %d chunks stored in '%s'.", len(all_docs), chroma_dir)
    return len(all_docs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest PDFs into the Agromaly knowledge base.")
    parser.add_argument(
        "--pdf-dir",
        default="backend/data/knowledge_base",
        help="Directory containing PDF files (default: backend/data/knowledge_base)",
    )
    parser.add_argument(
        "--chroma-dir",
        default="backend/data/chroma",
        help="ChromaDB persist directory (default: backend/data/chroma)",
    )
    parser.add_argument(
        "--collection",
        default=COLLECTION_NAME,
        help=f"ChromaDB collection name (default: {COLLECTION_NAME})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete and recreate the collection even if it already has documents.",
    )
    args = parser.parse_args()

    n = ingest(
        chroma_dir=args.chroma_dir,
        pdf_dir=args.pdf_dir,
        collection_name=args.collection,
        force=args.force,
    )
    sys.exit(0 if n >= 0 else 1)
