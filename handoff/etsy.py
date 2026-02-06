from __future__ import annotations

import re
from dataclasses import dataclass


TAG_MAX_LEN = 19  # Etsy: under 20 characters
TAG_PATTERN = re.compile(r"^[A-Za-z0-9 ]+$")


def normalize_tags_csv(raw: str) -> list[str]:
    parts = (raw or "").split(",")
    tags: list[str] = []
    for part in parts:
        tag = (part or "").strip()
        if not tag:
            continue
        tags.append(tag)
    return tags


def format_tags_csv(tags: list[str] | None) -> str:
    if not tags:
        return ""
    cleaned = [str(t).strip() for t in tags if str(t).strip()]
    return ", ".join(cleaned)


@dataclass(frozen=True)
class TagValidation:
    tags: list[str]
    errors: list[str]
    per_tag_errors: dict[int, list[str]]

    @property
    def ok(self) -> bool:
        return not self.errors and not any(self.per_tag_errors.values())


def validate_tags(tags: list[str] | None) -> TagValidation:
    tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
    errors: list[str] = []
    per_tag_errors: dict[int, list[str]] = {}

    if len(tags) != 13:
        errors.append(f"Expected exactly 13 tags, got {len(tags)}.")

    seen: set[str] = set()
    for idx, tag in enumerate(tags, start=1):
        tag_errors: list[str] = []
        if len(tag) > TAG_MAX_LEN:
            tag_errors.append("20+ characters")
        if not TAG_PATTERN.match(tag):
            tag_errors.append("contains special characters")
        lower = tag.lower()
        if lower in seen:
            tag_errors.append("duplicate")
        else:
            seen.add(lower)
        if tag_errors:
            per_tag_errors[idx] = tag_errors

    return TagValidation(tags=tags, errors=errors, per_tag_errors=per_tag_errors)


def suggest_title_from_filename(filename: str, suffix: str = "") -> str:
    base = (filename or "").strip()
    if not base:
        base = "Design"
    # strip extension
    if "." in base:
        base = base.rsplit(".", 1)[0].strip() or base
    # replace underscores with spaces and collapse whitespace
    base = re.sub(r"\s+", " ", base.replace("_", " ").strip())
    suffix = (suffix or "").strip()
    title = f"{base} {suffix}".strip() if suffix else base
    return title[:140]

