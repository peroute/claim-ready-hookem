"""Data schemas for the Claim-ready pipeline.

Defines the dataclasses used to represent intermediate and final
artifacts produced while turning a claimant's video walkthrough and
policy PDF into a structured claim packet.
"""

from dataclasses import dataclass, field
from typing import Optional, Literal


@dataclass
class KeyFrame:
    frame_id: str
    timestamp_sec: float
    image_path: str
    embedding: Optional[list[float]] = None


@dataclass
class NarrationChunk:
    chunk_id: str
    start_sec: float
    end_sec: float
    text: str
    embedding: Optional[list[float]] = None


@dataclass
class PolicySection:
    section_id: str
    title: str
    text: str
    embedding: Optional[list[float]] = None


@dataclass
class InventoryItem:
    item_id: str
    name: str
    category: Literal["electronics", "furniture", "textile", "appliance", "decor", "clothing", "other"]
    description: str
    damage_observed: str
    confidence: float
    source_frame_ids: list[str]
    source_narration_ids: list[str]
    first_seen_sec: float
    last_seen_sec: float
    brand_recognized: bool
    estimated_value: Optional[float] = None
    value_source: Literal["web_lookup", "user_input", "unknown"] = "unknown"
    proof_attached: bool = False
    policy_citations: list[str] = field(default_factory=list)


@dataclass
class ClaimPacket:
    claim_id: str
    incident_summary: str
    incident_date: str
    items: list[InventoryItem]
    total_estimated_value: float
    verified_value: float
    policy_sections_cited: list[PolicySection]
    fnol_letter: str
    video_source_path: str
    policy_source_path: str
    pdf_path: Optional[str] = None
