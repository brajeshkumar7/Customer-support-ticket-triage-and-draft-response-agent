"""Fail-closed deployment configuration for the controlled Zoho worker."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DeploymentConfig:
    mode: str
    database_url: str
    organization_id: str
    knowledge_hash: str
    poll_seconds: int = 60

    @classmethod
    def from_env(cls) -> "DeploymentConfig":
        mode = os.getenv("DEPLOYMENT_MODE", "off").strip().lower()
        if mode not in {"off", "shadow", "test", "live"}:
            raise ValueError("DEPLOYMENT_MODE must be off, shadow, test, or live.")
        if mode == "live":
            # No authoritative commerce/billing adapter or release audit exists.
            raise ValueError("Live customer sending is unavailable until provider validation and a separate release decision.")
        database_url = os.getenv("DATABASE_URL", "").strip()
        org = os.getenv("ZOHO_DESK_ORG_ID", "").strip()
        knowledge_hash = os.getenv("APPROVED_KNOWLEDGE_SHA256", "").strip().lower()
        if mode != "off" and (not database_url or not org.isdigit()):
            raise ValueError("DATABASE_URL and numeric ZOHO_DESK_ORG_ID are required.")
        if mode == "test" and not knowledge_hash:
            raise ValueError("Test sending requires APPROVED_KNOWLEDGE_SHA256.")
        return cls(mode, database_url, org, knowledge_hash)
