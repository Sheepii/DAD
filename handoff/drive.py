from __future__ import annotations

import io
import os
import json
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.utils import timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as SACredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload, MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME = "application/vnd.google-apps.folder"


def _path(value: str | Path) -> Path:
    return value if isinstance(value, Path) else Path(value)


def _get_app_setting():
    try:
        from handoff.models import AppSettings

        return AppSettings.objects.first()
    except Exception:
        return None


def _get_setting(name: str, default: str = ""):
    app_settings = _get_app_setting()
    if app_settings and hasattr(app_settings, name):
        value = getattr(app_settings, name)
        if value not in (None, ""):
            return value
    return getattr(settings, name, default)


def get_drive_service():
    if _get_setting("drive_use_service_account", False):
        sa_file = _path(
            _get_setting("drive_service_account_file_path", "")
            or _get_setting("GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE", "")
        )
        if not sa_file or not sa_file.exists():
            raise RuntimeError("Missing service account file.")
        creds = SACredentials.from_service_account_file(sa_file, scopes=SCOPES)
        return build("drive", "v3", credentials=creds)

    credentials_env = os.environ.get("GOOGLE_DRIVE_CREDENTIALS_JSON", "")
    token_env = os.environ.get("GOOGLE_DRIVE_TOKEN_JSON", "")
    credentials_file = _path(
        _get_setting("drive_credentials_file_path", "")
        or _get_setting("GOOGLE_DRIVE_CREDENTIALS_FILE", "")
    )
    token_file = _path(
        _get_setting("drive_token_file_path", "")
        or _get_setting("GOOGLE_DRIVE_TOKEN_FILE", "")
    )

    if not credentials_env and not credentials_file.exists():
        raise RuntimeError("Missing OAuth client credentials file.")

    creds: Optional[Credentials] = None
    if token_env:
        creds = Credentials.from_authorized_user_info(json.loads(token_env), SCOPES)
    elif token_file.exists():
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError(
                "OAuth token missing or invalid. Run 'python manage.py drive_auth'."
            )
        if not token_env:
            token_file.write_text(creds.to_json(), encoding="utf-8")

    return build("drive", "v3", credentials=creds)


def run_local_auth() -> Path:
    credentials_file = _path(
        _get_setting("drive_credentials_file_path", "")
        or _get_setting("GOOGLE_DRIVE_CREDENTIALS_FILE", "")
    )
    token_file = _path(
        _get_setting("drive_token_file_path", "")
        or _get_setting("GOOGLE_DRIVE_TOKEN_FILE", "")
    )
    if not credentials_file.exists():
        raise RuntimeError("Missing OAuth client credentials file.")
    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
    creds = flow.run_local_server(port=0)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return token_file


def _escape_query(value: str) -> str:
    return value.replace("'", "\\'")


def _delete_existing_named_files(service, parent_id: str, filename: str) -> None:
    safe_name = _escape_query(filename)
    query = (
        f"name='{safe_name}' and '{parent_id}' in parents and trashed=false"
    )
    response = service.files().list(q=query, fields="files(id)").execute()
    files = response.get("files", [])
    for file in files:
        file_id = file.get("id")
        if file_id:
            service.files().delete(fileId=file_id).execute()


def _safe_folder_name(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "Store"
    return value.replace("/", "-").replace("\\", "-")


def _store_label(store) -> str:
    if store is None:
        return ""
    name = getattr(store, "name", None)
    return _safe_folder_name(str(name or store))


def ensure_bucket(service, root_id: str, bucket: str, store=None) -> str:
    base_id = ensure_folder(service, bucket, root_id)
    label = _store_label(store)
    if label:
        return ensure_folder(service, label, base_id)
    return base_id


def ensure_store_drive_folders(store=None) -> dict[str, str]:
    root_id = _get_setting("drive_root_folder_id", "") or _get_setting(
        "GOOGLE_DRIVE_ROOT_FOLDER_ID", ""
    )
    if not root_id:
        raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set.")
    service = get_drive_service()
    folder_ids = {}
    for bucket in ("Dump_Zone", "Scheduled", "Done", "Error", "Mockups"):
        folder_ids[bucket] = ensure_bucket(service, root_id, bucket, store=store)
    return folder_ids


def get_dump_zone_folder_id(store=None) -> str:
    root_id = _get_setting("drive_root_folder_id", "") or _get_setting(
        "GOOGLE_DRIVE_ROOT_FOLDER_ID", ""
    )
    if not root_id:
        raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set.")
    service = get_drive_service()
    return ensure_bucket(service, root_id, "Dump_Zone", store=store)


def get_file_metadata(file_id: str, fields: str = "id,name,parents,mimeType") -> dict:
    service = get_drive_service()
    return service.files().get(fileId=file_id, fields=fields).execute()


def file_name_exists(service, parent_id: str, filename: str) -> bool:
    safe_name = _escape_query(filename)
    query = (
        f"name='{safe_name}' and '{parent_id}' in parents and trashed=false"
    )
    response = service.files().list(q=query, fields="files(id)").execute()
    return bool(response.get("files", []))


def move_file_to_folder(
    file_id: str,
    new_parent_id: str,
    new_name: str | None = None,
    service=None,
) -> dict:
    service = service or get_drive_service()
    meta = service.files().get(fileId=file_id, fields="parents").execute()
    parents = meta.get("parents", [])
    body = {}
    if new_name:
        body["name"] = new_name
    return (
        service.files()
        .update(
            fileId=file_id,
            addParents=new_parent_id,
            removeParents=",".join(parents),
            body=body,
            fields="id,name,parents",
        )
        .execute()
    )


def copy_file_to_folder(
    file_id: str,
    new_parent_id: str,
    new_name: str | None = None,
    service=None,
) -> dict:
    service = service or get_drive_service()
    body = {"parents": [new_parent_id]}
    if new_name:
        body["name"] = new_name
    return (
        service.files()
        .copy(fileId=file_id, body=body, fields="id,name,parents")
        .execute()
    )


def ensure_folder(service, name: str, parent_id: str) -> str:
    safe_name = _escape_query(name)
    query = (
        f"mimeType='{FOLDER_MIME}' and name='{safe_name}' "
        f"and '{parent_id}' in parents and trashed=false"
    )
    response = service.files().list(q=query, fields="files(id,name)").execute()
    files = response.get("files", [])
    if files:
        return files[0]["id"]
    metadata = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
    created = service.files().create(body=metadata, fields="id").execute()
    return created["id"]


def ensure_date_folder(service, parent_id: str, category: str, date_value=None) -> str:
    date_value = date_value or timezone.localdate()
    category_id = ensure_folder(service, category, parent_id)
    date_id = ensure_folder(service, date_value.isoformat(), category_id)
    return date_id


def ensure_date_bucket(service, root_id: str, category: str, date_value=None, store=None) -> str:
    date_value = date_value or timezone.localdate()
    base_id = ensure_bucket(service, root_id, category, store=store)
    return ensure_folder(service, date_value.isoformat(), base_id)


def upload_file(
    file_path: str | Path, filename: str, parent_id: str, service=None
) -> str:
    service = service or get_drive_service()
    metadata = {"name": filename, "parents": [parent_id]}
    media = MediaFileUpload(str(file_path), resumable=True)
    created = (
        service.files()
        .create(body=metadata, media_body=media, fields="id")
        .execute()
    )
    return created["id"]


def upload_file_bytes(
    data: bytes,
    filename: str,
    parent_id: str,
    mime_type: str = "application/octet-stream",
    service=None,
) -> str:
    service = service or get_drive_service()
    metadata = {"name": filename, "parents": [parent_id]}
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=True)
    created = (
        service.files()
        .create(body=metadata, media_body=media, fields="id")
        .execute()
    )
    return created["id"]


def upload_design_file(file_path: str | Path, filename: str, due_date=None) -> str:
    root_id = _get_setting("drive_root_folder_id", "") or _get_setting(
        "GOOGLE_DRIVE_ROOT_FOLDER_ID", ""
    )
    if not root_id:
        raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set.")
    service = get_drive_service()
    folder_id = ensure_date_folder(service, root_id, "Designs", due_date)
    return upload_file(file_path, filename, folder_id, service=service)


def upload_mockup_file(file_path: str | Path, filename: str, due_date=None) -> str:
    root_id = _get_setting("drive_root_folder_id", "") or _get_setting(
        "GOOGLE_DRIVE_ROOT_FOLDER_ID", ""
    )
    if not root_id:
        raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set.")
    service = get_drive_service()
    folder_id = ensure_date_folder(service, root_id, "Mockups", due_date)
    _delete_existing_named_files(service, folder_id, filename)
    return upload_file(file_path, filename, folder_id, service=service)


def get_mockups_folder_id(due_date=None) -> str:
    root_id = _get_setting("drive_root_folder_id", "") or _get_setting(
        "GOOGLE_DRIVE_ROOT_FOLDER_ID", ""
    )
    if not root_id:
        raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set.")
    service = get_drive_service()
    return ensure_date_folder(service, root_id, "Mockups", due_date)


def upload_mockup_bytes(
    data: bytes, filename: str, due_date=None, mime_type: str = "image/png"
) -> str:
    root_id = _get_setting("drive_root_folder_id", "") or _get_setting(
        "GOOGLE_DRIVE_ROOT_FOLDER_ID", ""
    )
    if not root_id:
        raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set.")
    service = get_drive_service()
    folder_id = ensure_date_folder(service, root_id, "Mockups", due_date)
    _delete_existing_named_files(service, folder_id, filename)
    return upload_file_bytes(
        data, filename, folder_id, mime_type=mime_type, service=service
    )


def upload_mockup_bytes_to_bucket(
    data: bytes,
    filename: str,
    due_date=None,
    store=None,
    mime_type: str = "image/png",
) -> str:
    root_id = _get_setting("drive_root_folder_id", "") or _get_setting(
        "GOOGLE_DRIVE_ROOT_FOLDER_ID", ""
    )
    if not root_id:
        raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set.")
    service = get_drive_service()
    folder_id = ensure_date_bucket(service, root_id, "Mockups", due_date, store=store)
    _delete_existing_named_files(service, folder_id, filename)
    return upload_file_bytes(
        data, filename, folder_id, mime_type=mime_type, service=service
    )


def upload_template_asset(file_path: str | Path, filename: str) -> str:
    root_id = _get_setting("drive_root_folder_id", "") or _get_setting(
        "GOOGLE_DRIVE_ROOT_FOLDER_ID", ""
    )
    if not root_id:
        raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set.")
    service = get_drive_service()
    folder_id = ensure_folder(service, "Static Assets", root_id)
    return upload_file(file_path, filename, folder_id, service=service)


def upload_template_asset_bytes(
    data: bytes,
    filename: str,
    template_name: str,
    slide_order: int,
    kind: str,
    mime_type: str = "image/png",
) -> str:
    root_id = _get_setting("drive_root_folder_id", "") or _get_setting(
        "GOOGLE_DRIVE_ROOT_FOLDER_ID", ""
    )
    if not root_id:
        raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set.")
    service = get_drive_service()
    base_folder = ensure_folder(service, "Mockup Templates", root_id)
    safe_template = template_name or "Template"
    template_folder = ensure_folder(service, safe_template, base_folder)
    slide_folder = ensure_folder(service, f"Slide-{slide_order}", template_folder)
    final_name = f"{kind}-{filename}"
    return upload_file_bytes(
        data, final_name, slide_folder, mime_type=mime_type, service=service
    )


def upload_admin_note_image_bytes(
    data: bytes,
    filename: str,
    note_date=None,
    mime_type: str = "image/png",
) -> str:
    root_id = _get_setting("drive_root_folder_id", "") or _get_setting(
        "GOOGLE_DRIVE_ROOT_FOLDER_ID", ""
    )
    if not root_id:
        raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set.")
    service = get_drive_service()
    folder_id = ensure_date_folder(service, root_id, "Admin Notes", note_date)
    safe_name = os.path.basename(filename or "").strip() or "note-image.png"
    return upload_file_bytes(
        data, safe_name, folder_id, mime_type=mime_type, service=service
    )


def archive_design_file(file_id: str, store=None) -> dict:
    root_id = _get_setting("drive_root_folder_id", "") or _get_setting(
        "GOOGLE_DRIVE_ROOT_FOLDER_ID", ""
    )
    if not root_id:
        raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set.")
    service = get_drive_service()
    scheduled_id = ensure_bucket(service, root_id, "Scheduled", store=store)
    done_id = ensure_bucket(service, root_id, "Done", store=store)

    meta = get_file_metadata(file_id, fields="id,name,parents")
    parents = meta.get("parents", [])
    if scheduled_id not in parents:
        return {"moved": False, "reason": "not_in_scheduled"}

    name = meta.get("name", file_id)
    final_name = name
    if file_name_exists(service, done_id, name):
        stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
        if "." in name:
            base, ext = name.rsplit(".", 1)
            final_name = f"{base}-{stamp}.{ext}"
        else:
            final_name = f"{name}-{stamp}"

    move_file_to_folder(
        file_id,
        new_parent_id=done_id,
        new_name=final_name if final_name != name else None,
        service=service,
    )
    return {"moved": True, "name": final_name}


def list_folder_images(folder_id: str) -> list[dict]:
    service = get_drive_service()
    query = (
        f"'{folder_id}' in parents and trashed=false and mimeType contains 'image/'"
    )
    response = (
        service.files()
        .list(
            q=query,
            fields="files(id,name,thumbnailLink)",
            orderBy="name",
            pageSize=100,
        )
        .execute()
    )
    return response.get("files", [])


def download_file_bytes(file_id: str) -> tuple[str, str, bytes]:
    service = get_drive_service()
    meta = service.files().get(fileId=file_id, fields="name,mimeType").execute()
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return meta.get("name", file_id), meta.get("mimeType", ""), buffer.getvalue()
