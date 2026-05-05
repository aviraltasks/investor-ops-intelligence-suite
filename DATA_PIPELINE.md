# DATA_PIPELINE.md

Phase 2 data pipeline currently includes:

## 1) RAG corpus ingestion

- Source manifest in `backend/app/sources/manifest.py`
  - 15 Groww mutual fund pages
  - 9 SEBI investor education pages
  - 6 additional official Groww category pages
- Ingestion pipeline in `backend/app/rag/ingest_pipeline.py`
  - fetch -> extract -> chunk -> embed -> persist in `rag_chunks`
- Extraction:
  - HTML via BeautifulSoup (`html.parser`)
  - PDF via `pypdf`
- Chunking:
  - character-window chunks with overlap (`backend/app/rag/chunking.py`)
- Embeddings:
  - default `HashEmbedder` for stable local runs
  - optional sentence-transformers backend when configured

## 2) Review ingestion with fallback

- Review pipeline in `backend/app/reviews/pipeline.py`
- Primary source:
  - Google Play Store app `com.nextbillion.groww` via `google-play-scraper`
- Fallback source:
  - CSV file path from `REVIEWS_FALLBACK_CSV`
  - sample file committed at `backend/sample_data/reviews_fallback.csv`
- Persistence:
  - upsert into `reviews` table by `external_id`

## 3) API hooks for validation

- `POST /api/data/ingest` -> run RAG ingestion
- `GET /api/data/stats` -> chunk counts by layer
- `GET /api/data/search?q=...` -> vector-style search over stored embeddings
- `POST /api/reviews/refresh` -> fetch play-store reviews, fallback to CSV if needed

## 4) Current limitations (expected at Phase 2)

- RAG retrieval is full-scan similarity over stored vectors (sufficient for current scale).
- Review pipeline does not yet produce themes/pulse output (Phase 3).
- No scheduler/agent orchestration calls yet (Phase 4 onward).
