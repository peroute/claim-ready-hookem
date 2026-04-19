"""FastAPI HTTP interface for the claim-ready pipeline.

Endpoints:
  POST /claims                       upload video + policy + intake, kick off
                                     pipeline, return claim_id immediately
  GET  /claims/{claim_id}/status     latest pipeline progress
  GET  /claims/{claim_id}/packet     packet metadata JSON (for review UI)
  GET  /claims/{claim_id}/pdf        the rendered packet PDF
  POST /claims/{claim_id}/regenerate re-render packet from edited items

Progress is tracked in a process-local dict (`PROGRESS_STATE`). For a
single-server demo this is fine; in production you'd back this with
Redis or similar.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

import config
from generate_packet import generate_packet
from ingest_policy import ingest_policy
from pipeline import PipelineProgress, run_pipeline
from schemas import InventoryItem


# ---------------------------------------------------------------------------
# App + CORS
# ---------------------------------------------------------------------------

app = FastAPI(title="Claim-ready API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Shared progress state
# ---------------------------------------------------------------------------

PROGRESS_STATE: dict[str, PipelineProgress] = {}


def _set_progress(progress: PipelineProgress) -> None:
    PROGRESS_STATE[progress.claim_id] = progress


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _claim_dir(claim_id: str) -> Path:
    return Path(config.OUTPUT_DIR) / claim_id


def _video_path(claim_id: str) -> Path:
    return _claim_dir(claim_id) / "video.mp4"


def _policy_path(claim_id: str) -> Path:
    return _claim_dir(claim_id) / "policy.pdf"


def _packet_meta_path(claim_id: str) -> Path:
    return _claim_dir(claim_id) / "packet.json"


def _packet_pdf_path(claim_id: str) -> Path:
    return _claim_dir(claim_id) / "packet.pdf"


def _intake_path(claim_id: str) -> Path:
    return _claim_dir(claim_id) / "intake.json"


def _frame_path(claim_id: str, frame_id: str) -> Path:
    # Accept either "frame_0042" or "frame_0042.jpg" — strip the suffix.
    name = frame_id[:-4] if frame_id.endswith(".jpg") else frame_id
    return _claim_dir(claim_id) / "frames" / f"{name}.jpg"


# ---------------------------------------------------------------------------
# Upload helpers
# ---------------------------------------------------------------------------

def _save_upload(upload: UploadFile, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as out:
        shutil.copyfileobj(upload.file, out)
    upload.file.close()


def _save_intake(claim_id: str, intake: dict) -> None:
    """Persist intake to disk so /packet can return it.

    Lets the frontend regenerate without having to stash claimant_name,
    cause, and location in localStorage.
    """
    path = _intake_path(claim_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(intake, f, indent=2)


def _load_intake(claim_id: str) -> dict | None:
    path = _intake_path(claim_id)
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _parse_intake(intake_json: str) -> dict:
    try:
        data = json.loads(intake_json)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid intake JSON: {e}"
        )
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=400, detail="intake must be a JSON object"
        )
    return data


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------

def _run_pipeline_bg(
    claim_id: str, video_path: str, policy_path: str, intake: dict
) -> None:
    """Run the pipeline and stream its progress into PROGRESS_STATE.

    Wrapped in a try/except so background-task errors are captured in
    the progress dict (the foreground response has long since returned).
    """
    try:
        run_pipeline(
            claim_id=claim_id,
            video_path=video_path,
            policy_path=policy_path,
            intake=intake,
            progress_callback=_set_progress,
        )
    except Exception as e:
        _set_progress(PipelineProgress(
            stage="error",
            percent=-1.0,
            message=str(e),
            claim_id=claim_id,
        ))


# ---------------------------------------------------------------------------
# POST /claims
# ---------------------------------------------------------------------------

@app.post("/claims")
async def create_claim(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    policy: UploadFile = File(...),
    intake: str = Form(...),
) -> dict:
    intake_data = _parse_intake(intake)
    claim_id = uuid.uuid4().hex[:12]

    video_path = _video_path(claim_id)
    policy_path = _policy_path(claim_id)
    _save_upload(video, video_path)
    _save_upload(policy, policy_path)
    _save_intake(claim_id, intake_data)

    _set_progress(PipelineProgress(
        stage="queued",
        percent=0.0,
        message="Pipeline queued",
        claim_id=claim_id,
    ))

    background_tasks.add_task(
        _run_pipeline_bg,
        claim_id,
        str(video_path),
        str(policy_path),
        intake_data,
    )

    return {"claim_id": claim_id}


# ---------------------------------------------------------------------------
# GET /claims/{claim_id}/status
# ---------------------------------------------------------------------------

@app.get("/claims/{claim_id}/status")
async def get_status(claim_id: str) -> JSONResponse:
    progress = PROGRESS_STATE.get(claim_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="claim_id not found")

    if progress.stage == "error":
        return JSONResponse(
            status_code=500,
            content={
                "claim_id": claim_id,
                "stage": "error",
                "percent": -1,
                "message": progress.message,
            },
        )

    if progress.stage == "complete":
        return JSONResponse(content={
            "claim_id": claim_id,
            "stage": "complete",
            "percent": 100.0,
            "message": "ready",
        })

    return JSONResponse(content={
        "claim_id": claim_id,
        "stage": progress.stage,
        "percent": progress.percent,
        "message": progress.message,
    })


# ---------------------------------------------------------------------------
# GET /claims/{claim_id}/packet
# ---------------------------------------------------------------------------

@app.get("/claims/{claim_id}/packet")
async def get_packet_meta(claim_id: str) -> JSONResponse:
    p = _packet_meta_path(claim_id)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="packet.json not found")
    with open(p, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # Strip per-section embeddings — they bloat the wire by ~1.5KB/section
    # and the frontend never uses them. Done here (not at write time) so
    # the on-disk packet.json remains the full ground truth.
    sections = meta.get("policy_sections_cited")
    if isinstance(sections, list):
        for s in sections:
            if isinstance(s, dict):
                s.pop("embedding", None)

    intake = _load_intake(claim_id)
    if intake is not None:
        meta["intake"] = intake

    return JSONResponse(content=meta)


# ---------------------------------------------------------------------------
# GET /claims/{claim_id}/pdf
# ---------------------------------------------------------------------------

@app.get("/claims/{claim_id}/pdf")
async def get_packet_pdf(claim_id: str) -> FileResponse:
    p = _packet_pdf_path(claim_id)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="packet.pdf not found")
    return FileResponse(
        path=str(p),
        media_type="application/pdf",
        filename=f"claim_{claim_id}.pdf",
    )


# ---------------------------------------------------------------------------
# GET /claims/{claim_id}/video  (range-aware; required by HTML5 <video>)
# GET /claims/{claim_id}/frames/{frame_id}
# ---------------------------------------------------------------------------

def _range_response(
    path: Path, request: Request, media_type: str
) -> "JSONResponse | FileResponse | StreamingResponse":
    """Serve `path` with HTTP Range support so browser <video> can seek.

    Starlette's FileResponse doesn't honor the Range header on its own,
    so we parse it manually and stream the requested byte slice. Falls
    back to a normal 200 FileResponse when no Range header is present.
    """
    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(str(path), media_type=media_type)

    units, _, raw = range_header.partition("=")
    if units.strip().lower() != "bytes":
        return FileResponse(str(path), media_type=media_type)

    start_str, _, end_str = raw.partition("-")
    try:
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
    except ValueError:
        return FileResponse(str(path), media_type=media_type)

    if start >= file_size or start < 0:
        raise HTTPException(
            status_code=416, detail="Range not satisfiable"
        )
    end = min(end, file_size - 1)
    length = end - start + 1

    def chunk_iter():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                buf = f.read(min(64 * 1024, remaining))
                if not buf:
                    break
                remaining -= len(buf)
                yield buf

    return StreamingResponse(
        chunk_iter(),
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        },
    )


@app.get("/claims/{claim_id}/video")
async def get_video(claim_id: str, request: Request):
    p = _video_path(claim_id)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="video not found")
    return _range_response(p, request, "video/mp4")


@app.get("/claims/{claim_id}/frames/{frame_id}")
async def get_frame(claim_id: str, frame_id: str) -> FileResponse:
    p = _frame_path(claim_id, frame_id)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="frame not found")
    return FileResponse(str(p), media_type="image/jpeg")


# ---------------------------------------------------------------------------
# POST /claims/{claim_id}/regenerate
# ---------------------------------------------------------------------------

def _coerce_items(raw_items: Any) -> list[InventoryItem]:
    if not isinstance(raw_items, list):
        raise HTTPException(
            status_code=400, detail="'items' must be a list"
        )
    out: list[InventoryItem] = []
    for i, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=400, detail=f"item[{i}] must be an object"
            )
        try:
            out.append(InventoryItem(**raw))
        except TypeError as e:
            raise HTTPException(
                status_code=400,
                detail=f"item[{i}] missing/invalid fields: {e}",
            )
    return out


@app.post("/claims/{claim_id}/regenerate")
def regenerate_packet(claim_id: str, body: dict) -> dict:
    # NOTE: sync def on purpose. generate_packet() internally calls
    # asyncio.run(...) for Playwright; that works only when there's no
    # running event loop. FastAPI dispatches sync endpoints to a
    # threadpool worker (no loop), so this stays safe.
    if not _claim_dir(claim_id).is_dir():
        raise HTTPException(status_code=404, detail="claim_id not found")

    policy_pdf = _policy_path(claim_id)
    if not policy_pdf.is_file():
        raise HTTPException(
            status_code=404, detail="original policy PDF missing"
        )

    items = _coerce_items(body.get("items", []))
    intake = body.get("intake")
    if not isinstance(intake, dict):
        raise HTTPException(
            status_code=400, detail="'intake' object required"
        )

    # Persist the (possibly user-edited) intake so future GETs see it.
    _save_intake(claim_id, intake)

    sections = ingest_policy(str(policy_pdf))

    packet = generate_packet(
        claim_id=claim_id,
        items=items,
        policy_sections=sections,
        intake=intake,
        video_source_path=str(_video_path(claim_id)),
        policy_source_path=str(policy_pdf),
    )

    meta_path = _packet_meta_path(claim_id)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(asdict(packet), f, indent=2)

    return {"pdf_url": f"/claims/{claim_id}/pdf"}


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    print("\n=== claim-ready API ===")
    print("Server: http://localhost:8000")
    print("\nTest commands:\n")
    print("  # 1. Upload (returns {\"claim_id\": \"...\"})")
    print('  curl -X POST http://localhost:8000/claims \\')
    print('    -F "video=@real-video.mp4" \\')
    print('    -F "policy=@demo_policy.pdf" \\')
    print('    -F \'intake={"incident_date":"April 18, 2026",'
          '"cause":"Water damage from pipe burst",'
          '"location":"Living room","claimant_name":"Hedi Bouassida"}\'')
    print("")
    print("  # 2. Poll progress")
    print("  curl http://localhost:8000/claims/<claim_id>/status")
    print("")
    print("  # 3. Fetch packet metadata for the review UI")
    print("  curl http://localhost:8000/claims/<claim_id>/packet")
    print("")
    print("  # 4. Open the rendered PDF in a browser")
    print("  start http://localhost:8000/claims/<claim_id>/pdf")
    print("")
    print("  # 5. Regenerate after frontend edits")
    print('  curl -X POST http://localhost:8000/claims/<claim_id>/regenerate \\')
    print('    -H "Content-Type: application/json" \\')
    print('    -d \'{"items":[...edited items...],"intake":{...}}\'')
    print("")

    uvicorn.run(app, host="0.0.0.0", port=8000)
