# Knowledge Base — Agricultural PDF Manuals

Drop agricultural PDF manuals into this directory. The RAG ingestion script
(`backend/scripts/ingest_knowledge_base.py`) auto-discovers all `*.pdf` files here
and embeds them into the ChromaDB vector store on startup (idempotent — only runs
when the collection is empty).

## Suggested documents

- Crop disease and pest atlases (MADR, EFSA)
- Fertilisation guides (nitrogen, phosphorus, potassium management)
- Irrigation scheduling manuals
- Integrated Pest Management (IPM) guides
- NDVI interpretation handbooks
- Regional agro-meteorological bulletins

## How to add documents

1. Place the PDF file in this directory (e.g. `guide_wheat_disease.pdf`).
2. Delete the ChromaDB collection to force re-ingestion:
   ```bash
   rm -rf backend/data/chroma
   ```
3. Restart the application (`docker compose restart api`) — ingestion runs automatically on startup.

Or run the script directly:
```bash
python backend/scripts/ingest_knowledge_base.py
```
