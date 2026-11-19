import io

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from src.constants.gsheets import SHEETS_AUTHENTICATION_FILE

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _get_drive_service():
    credentials = service_account.Credentials.from_service_account_file(
        SHEETS_AUTHENTICATION_FILE, scopes=DRIVE_SCOPES
    )
    return build("drive", "v3", credentials=credentials)


def find_latest_matching_file(folder_id: str, name_contains: str) -> dict | None:
    """The most recently modified file in the given Drive folder whose name
    contains name_contains (case-insensitive), as Drive's id/name/
    modifiedTime fields, or None if no file in the folder matches."""
    response = (
        _get_drive_service()
        .files()
        .list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="files(id, name, modifiedTime)",
            orderBy="modifiedTime desc",
        )
        .execute()
    )
    name_contains = name_contains.lower()
    return next(
        (f for f in response.get("files", []) if name_contains in f["name"].lower()),
        None,
    )


def download_file(file_id: str) -> bytes:
    request = _get_drive_service().files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def download_latest_matching_file(folder_id: str, name_contains: str) -> bytes | None:
    """Raw bytes of find_latest_matching_file's match, or None if no file in
    the folder matches."""
    match = find_latest_matching_file(folder_id, name_contains)
    return None if match is None else download_file(match["id"])
