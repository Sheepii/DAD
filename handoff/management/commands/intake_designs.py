from __future__ import annotations

import datetime as dt
import os
import re
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from handoff.drive import FOLDER_MIME, ensure_bucket, get_drive_service
from handoff.models import AppSettings, DesignFile, ScheduledDesign, Store

VALID_MIME = {"image/png", "image/jpeg", "image/jpg"}
MAX_BYTES = 20 * 1024 * 1024
DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


def _get_root_id() -> str:
    settings_row = AppSettings.objects.first()
    if settings_row and settings_row.drive_root_folder_id:
        return settings_row.drive_root_folder_id
    return (
        getattr(settings, "GOOGLE_DRIVE_ROOT_FOLDER_ID", "")
        or os.environ.get("GOOGLE_DRIVE_ROOT_FOLDER_ID", "")
    )


def _list_files(service, folder_id: str, order_by: str | None = None) -> list[dict]:
    files = []
    page_token = None
    while True:
        response = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id,name,mimeType,size,parents,createdTime)",
                orderBy=order_by or "name",
                pageSize=1000,
                pageToken=page_token,
            )
            .execute()
        )
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return files


def _parse_date_from_name(name: str) -> dt.date | None:
    match = DATE_RE.search(name or "")
    if not match:
        return None
    try:
        return dt.datetime.strptime(match.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_valid_image(mime_type: str, filename: str) -> bool:
    if mime_type in VALID_MIME:
        return True
    ext = os.path.splitext(filename or "")[1].lower()
    return ext in {".png", ".jpg", ".jpeg"}


def _file_ext(mime_type: str, filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in {".png", ".jpg", ".jpeg"}:
        return ext
    if mime_type in ("image/jpeg", "image/jpg"):
        return ".jpg"
    if mime_type == "image/png":
        return ".png"
    return ""


def _size_mb(size_bytes: int) -> Decimal:
    mb = Decimal(size_bytes) / Decimal(1024 * 1024)
    return mb.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _move_file(service, file_id: str, old_parent: str, new_parent: str, new_name: str | None, dry_run: bool) -> None:
    if dry_run:
        return
    body = {}
    if new_name:
        body["name"] = new_name
    service.files().update(
        fileId=file_id,
        addParents=new_parent,
        removeParents=old_parent,
        body=body,
        fields="id,parents,name",
    ).execute()


class Command(BaseCommand):
    help = "Move designs from Dump_Zone to Scheduled with date-based naming."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show actions without modifying Drive.")
        parser.add_argument("--store", help="Optional store name or ID to bucket designs.")

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        store_value = options.get("store")
        store = None
        if store_value:
            try:
                store = Store.objects.get(pk=int(store_value))
            except (ValueError, Store.DoesNotExist):
                store = Store.objects.filter(name__iexact=str(store_value).strip()).first()
            if not store:
                raise RuntimeError(f"Store not found: {store_value}")
        root_id = _get_root_id()
        if not root_id:
            raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set.")

        service = get_drive_service()
        dump_id = ensure_bucket(service, root_id, "Dump_Zone", store=store)
        scheduled_id = ensure_bucket(service, root_id, "Scheduled", store=store)
        error_id = ensure_bucket(service, root_id, "Error", store=store)

        scheduled_files = _list_files(service, scheduled_id, order_by="name")
        latest_date = None
        for item in scheduled_files:
            found = _parse_date_from_name(item.get("name", ""))
            if found and (latest_date is None or found > latest_date):
                latest_date = found

        next_date = latest_date + dt.timedelta(days=1) if latest_date else timezone.localdate()

        dump_files = _list_files(service, dump_id, order_by="createdTime")
        if not dump_files:
            self.stdout.write("No new files in Dump_Zone.")
            return

        for item in dump_files:
            file_id = item.get("id")
            name = item.get("name", "")
            mime_type = item.get("mimeType", "")
            size_bytes = int(item.get("size") or 0)

            if mime_type == FOLDER_MIME:
                self.stdout.write(f"Skipping folder: {name}")
                continue

            if not _is_valid_image(mime_type, name):
                self.stdout.write(f"Invalid file type for {name}. Moving to /Error.")
                _move_file(service, file_id, dump_id, error_id, None, dry_run)
                DesignFile.objects.update_or_create(
                    drive_file_id=file_id,
                    defaults={
                        "filename": name,
                        "status": DesignFile.STATUS_ERROR,
                        "size_mb": _size_mb(size_bytes),
                        "ext": _file_ext(mime_type, name).lstrip("."),
                        "store": store,
                        "source_folder": "Error",
                    },
                )
                continue

            if size_bytes > MAX_BYTES:
                self.stdout.write(f"File too large ({size_bytes} bytes) for {name}. Moving to /Error.")
                _move_file(service, file_id, dump_id, error_id, None, dry_run)
                DesignFile.objects.update_or_create(
                    drive_file_id=file_id,
                    defaults={
                        "filename": name,
                        "status": DesignFile.STATUS_ERROR,
                        "size_mb": _size_mb(size_bytes),
                        "ext": _file_ext(mime_type, name).lstrip("."),
                        "store": store,
                        "source_folder": "Error",
                    },
                )
                continue

            ext = _file_ext(mime_type, name)
            new_name = f"{next_date.isoformat()}{ext}"
            self.stdout.write(f"Scheduling {name} -> {new_name}")
            _move_file(service, file_id, dump_id, scheduled_id, new_name, dry_run)
            DesignFile.objects.update_or_create(
                drive_file_id=file_id,
                defaults={
                    "filename": new_name,
                    "date_assigned": next_date,
                    "status": DesignFile.STATUS_SCHEDULED,
                    "size_mb": _size_mb(size_bytes),
                    "ext": ext.lstrip("."),
                    "store": store,
                    "source_folder": "Scheduled",
                },
            )
            if not dry_run:
                ScheduledDesign.objects.update_or_create(
                    due_date=next_date,
                    recurring_task=None,
                    store=store,
                    defaults={"drive_design_file_id": file_id},
                )
            next_date += dt.timedelta(days=1)

        if dry_run:
            self.stdout.write("Dry run complete. No changes were applied.")
