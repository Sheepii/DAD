from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class TagGenerationResult:
    tags: list[str]
    raw_text: str


def _get_env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value)


def _extract_output_text(payload: dict[str, Any]) -> str:
    # OpenAI Responses API returns output[] with content[] items.
    for item in payload.get("output", []) or []:
        content = item.get("content") or []
        for part in content:
            if part.get("type") == "output_text" and part.get("text"):
                return str(part["text"])
    # Fallback: some SDKs include output_text at top-level.
    if payload.get("output_text"):
        return str(payload["output_text"])
    return ""


def _parse_json_array(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty model response.")
    # Try exact
    try:
        value = json.loads(text)
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
    except Exception:
        pass
    # Try to extract first [...] block
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        raise ValueError("Model did not return a JSON array.")
    value = json.loads(match.group(0))
    if not isinstance(value, list):
        raise ValueError("Model JSON was not a list.")
    return [str(v).strip() for v in value if str(v).strip()]


def generate_etsy_tags(title: str, description: str, product_hint: str = "") -> TagGenerationResult:
    api_key = _get_env("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY.")

    model = _get_env("OPENAI_MODEL", "gpt-4o-mini")
    base_url = _get_env("OPENAI_BASE_URL", "https://api.openai.com")

    instruction = (
        "Generate Etsy tags for a single listing.\n"
        "Return ONLY a JSON array of exactly 13 strings.\n"
        "Rules for each tag:\n"
        "- Under 20 characters (max 19)\n"
        "- Letters, numbers, and spaces only (no punctuation/symbols)\n"
        "- No leading/trailing spaces\n"
        "- Avoid duplicates (case-insensitive)\n"
    )
    if product_hint:
        instruction += f"\nProduct hint: {product_hint}\n"

    user_input = (
        f"Title: {title.strip()}\n\n"
        f"Description: {(description or '').strip()}\n"
    )

    resp = requests.post(
        f"{base_url.rstrip('/')}/v1/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "input": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": user_input},
            ],
        },
        timeout=45,
    )

    if resp.status_code >= 400:
        raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text}")

    payload = resp.json()
    output_text = _extract_output_text(payload)
    tags = _parse_json_array(output_text)
    return TagGenerationResult(tags=tags, raw_text=output_text)

