from __future__ import annotations

import os
import random

from django.utils import timezone

from .drive import copy_file_to_folder, ensure_bucket, get_drive_service, get_file_metadata
from .models import DesignFile, ScheduledDesign


def _ext_from_design(design: DesignFile, fallback_name: str | None = None) -> str:
    ext = (design.ext or "").strip()
    if ext:
        return ext if ext.startswith(".") else f".{ext}"
    name = fallback_name or design.filename or ""
    _, ext = os.path.splitext(name)
    return ext


def _scheduled_ids_excluding(date_value) -> set[str]:
    return set(
        ScheduledDesign.objects.exclude(due_date=date_value).values_list(
            "drive_design_file_id", flat=True
        )
    )


def ensure_emergency_design(date_value=None, store=None) -> dict | None:
    date_value = date_value or timezone.localdate()
    if store:
        if ScheduledDesign.objects.filter(due_date=date_value, store=store).exists():
            return None
    else:
        if ScheduledDesign.objects.filter(due_date=date_value).exists():
            return None

    scheduled_ids = _scheduled_ids_excluding(date_value)
    candidates = (
        DesignFile.objects.filter(status=DesignFile.STATUS_POSTED)
        .exclude(drive_file_id__in=scheduled_ids)
    )
    if store:
        candidates = candidates.filter(store=store)
    candidates = list(candidates)
    if not candidates:
        return None

    picked = random.choice(candidates)
    service = get_drive_service()
    meta = get_file_metadata(picked.drive_file_id, fields="id,name")
    ext = _ext_from_design(picked, fallback_name=meta.get("name", ""))
    new_name = f"{date_value.isoformat()}{ext}"

    root_id = None
    try:
        from django.conf import settings
        from .models import AppSettings

        settings_row = AppSettings.objects.first()
        if settings_row and settings_row.drive_root_folder_id:
            root_id = settings_row.drive_root_folder_id
        else:
            root_id = getattr(settings, "GOOGLE_DRIVE_ROOT_FOLDER_ID", "")
    except Exception:
        root_id = ""
    if not root_id:
        raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set.")

    scheduled_id = ensure_bucket(service, root_id, "Scheduled", store=store)
    copied = copy_file_to_folder(
        picked.drive_file_id,
        new_parent_id=scheduled_id,
        new_name=new_name,
        service=service,
    )
    new_file_id = copied.get("id")
    if not new_file_id:
        return None

    new_design = DesignFile.objects.create(
        filename=new_name,
        date_assigned=date_value,
        status=DesignFile.STATUS_RECYCLED,
        drive_file_id=new_file_id,
        size_mb=picked.size_mb or 0,
        ext=ext.lstrip("."),
        store=store,
        source_folder="Scheduled",
    )
    ScheduledDesign.objects.update_or_create(
        due_date=date_value,
        recurring_task=None,
        store=store,
        defaults={"drive_design_file_id": new_file_id},
    )
    return {"design": new_design, "source": picked}
