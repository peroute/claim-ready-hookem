"""Shared embedding helpers for the Claim-ready pipeline.

Centralizes loading of the CLIP image encoder (ViT-B-32, openai
weights) and the sentence-transformers text encoder
(all-MiniLM-L6-v2). All downstream modules (video ingest, policy
ingest, search, detection) should import from here so that each model
is loaded at most once per process.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import torch
from PIL import Image


@lru_cache(maxsize=1)
def _load_clip() -> tuple[Any, Any, str]:
    """Load open_clip ViT-B-32 (openai weights) once per process."""
    import open_clip

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="openai"
    )
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    return model, preprocess, device


@lru_cache(maxsize=1)
def _load_text_encoder() -> Any:
    """Load sentence-transformers all-MiniLM-L6-v2 once per process."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("all-MiniLM-L6-v2")


def embed_image(image_path: str) -> list[float]:
    """L2-normalized CLIP embedding of an image on disk (512-dim)."""
    model, preprocess, device = _load_clip()
    img = Image.open(image_path).convert("RGB")
    tensor = preprocess(img).unsqueeze(0).to(device)
    with torch.no_grad():
        feat = model.encode_image(tensor)
        feat = feat / feat.norm(dim=-1, keepdim=True)
    return feat.squeeze(0).cpu().tolist()


def embed_text(text: str) -> list[float]:
    """L2-normalized sentence-transformers embedding of text (384-dim)."""
    encoder = _load_text_encoder()
    vec = encoder.encode(text, normalize_embeddings=True)
    return vec.tolist()
