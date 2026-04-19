# Claim-ready

Turn an insurance claimant's video walkthrough and policy PDF into a
submission-ready claim packet — in under three minutes.

Built at Hook 'Em Hacks 2026.

---

## What it does

1. **Upload** a damage walkthrough video (MP4/MOV) and a policy PDF.
2. **Process** — keyframes extracted, audio transcribed, both indexed
   into ChromaDB, then Gemini 2.5 Flash + CLIP detect every damaged
   item visible or named in the narration.
3. **Cite** — each detected item is matched against the relevant
   sections of the policy.
4. **Render** — a polished PDF packet (cover page, incident summary,
   AI-generated FNOL letter, itemized inventory with thumbnails, policy
   excerpts) is produced via Jinja2 + Playwright.
5. **Review** — claimant edits values, ticks receipts, deletes false
   positives in a Linear-style review screen, then regenerates.

## Stack

| Layer    | Tech                                                     |
| -------- | -------------------------------------------------------- |
| Frontend | Next.js 14 (App Router) · TypeScript · Tailwind · shadcn/ui |
| Backend  | FastAPI · Python 3.11+                                   |
| Vision   | Google `gemini-2.5-flash` (multimodal)                   |
| Audio    | Groq `whisper-large-v3`                                  |
| Embeds   | OpenAI CLIP `ViT-B-32` (image), MiniLM (text)            |
| Vector   | ChromaDB (persistent, per-claim collections)             |
| PDF      | Jinja2 → Playwright (headless Chromium)                  |

## Quick start

### 1. Backend (port 8000)

```powershell
cd backend
python -m venv ..\.venv
..\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
# Edit .env and fill in GROQ_API_KEY and GOOGLE_API_KEY
python api.py
```

### 2. Frontend (port 3000)

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```



### Optional: pointing the frontend at a non-default backend

```powershell
copy frontend\.env.local.example frontend\.env.local
# edit NEXT_PUBLIC_API_BASE
```

## Env vars

| Var                    | Where         | Notes                                      |
| ---------------------- | ------------- | ------------------------------------------ |
| `GROQ_API_KEY`         | `backend/.env` | Whisper transcription (`gsk_...` prefix)   |
| `GOOGLE_API_KEY`       | `backend/.env` | Gemini detection (Tier 1 billing required) |
| `NEXT_PUBLIC_API_BASE` | `frontend/.env.local` | Defaults to `http://localhost:8000` |

## API surface

All endpoints under `http://localhost:8000`.

| Method | Path                                  | Purpose                                   |
| ------ | ------------------------------------- | ----------------------------------------- |
| POST   | `/claims`                             | Upload video + policy + intake; kicks off the background pipeline; returns `{claim_id}` |
| GET    | `/claims/{id}/status`                 | Poll pipeline progress (`stage`, `percent`, `message`) |
| GET    | `/claims/{id}/packet`                 | Packet metadata for the review UI (items, citations, intake) |
| GET    | `/claims/{id}/pdf`                    | The rendered PDF (`application/pdf`)      |
| GET    | `/claims/{id}/video`                  | Source walkthrough video, range-aware     |
| GET    | `/claims/{id}/frames/{frame_id}`      | Individual keyframe JPG                   |
| POST   | `/claims/{id}/regenerate`             | Re-render the packet from edited items    |

## CLI (no frontend)

The full pipeline runs from the command line too:

```powershell
cd backend
python pipeline.py test outputs\test\real-video.mp4 demo_policy.pdf
```

## Frontend routes

| Route                            | What it shows                                |
| -------------------------------- | -------------------------------------------- |
| `/`                              | Upload landing page (intake + dropzones)     |
| `/claim/{id}/processing`         | Live pipeline progress + stage checklist     |
| `/claim/{id}/review`             | Inventory table + video player + summary stats |
| `/claim/{id}/packet`             | Final PDF preview + download                 |

## Project layout

```
claim-ready/
├── backend/             FastAPI service + pipeline modules
│   ├── api.py           HTTP layer
│   ├── pipeline.py      Stage orchestrator (CLI + import target)
│   ├── ingest_video.py  Frames + transcription
│   ├── ingest_policy.py PDF parsing + sectioning
│   ├── detect_inventory.py  Gemini multimodal item detection
│   ├── search_policy.py Per-item policy citation lookup
│   ├── generate_packet.py   PDF rendering via Playwright
│   ├── vector_store.py  ChromaDB wrapper
│   ├── schemas.py       Dataclasses shared across the pipeline
│   └── templates/packet.html  Jinja template for the PDF
└── frontend/            Next.js 14 app
    ├── app/             Routes (App Router)
    ├── components/      UI components (shadcn primitives + brand)
    └── lib/             Typed API client, formatting, hooks
```

## Notes & known limitations (V1)

- Item value estimation is **deferred to V2** — values are user-entered
  during the review step.
- Gemini detection requires a Tier 1 (billing-enabled) Google Cloud
  project; the free tier's 20 req/day limit is hit very quickly.
- Whisper occasionally mis-transcribes brand names (e.g. "Highsense"
  for "Hisense"); per-brand fixes live in `detect_inventory.py` and
  `generate_packet.py`.
- In-memory progress state in `api.py` — single-server only. Production
  would back this with Redis or similar.
