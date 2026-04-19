"""Configuration for the Claim-ready backend.

Loads environment variables from `.env`, exposes API keys, and defines
shared constants (output directories, frame sampling rate, narration
chunking window). Ensures required output directories exist on import.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY")
GOOGLE_API_KEY: str | None = os.getenv("GOOGLE_API_KEY")

OUTPUT_DIR: str = "./outputs"
CHROMA_DIR: str = "./chroma_db"

KEYFRAME_FPS: int = 1
NARRATION_CHUNK_SEC: int = 7

Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
Path(CHROMA_DIR).mkdir(parents=True, exist_ok=True)
