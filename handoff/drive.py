from __future__ import annotations

import io
import os
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

    creds: Optional[Credentials] = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError(
                "OAuth token missing or invalid. Run 'python manage.py drive_auth'."
            )
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
