#!/usr/bin/env python3
"""Google Drive CLI tool for Atlas — upload files, manage folders.

Completes the Google Workspace script suite alongside google_sheets_tool.py,
google_docs_tool.py, and gmail_tool.py. Used by the Fiverr thumbnail
delivery pipeline to upload deliverables into nested client folders.

Usage:
    google_drive_tool.py upload FILE_PATH [--folder-name "Folder"] [--parent-folder "Parent"]
    google_drive_tool.py list --folder-name "Folder"
    google_drive_tool.py get-link --file-id FILE_ID
    google_drive_tool.py create-folder --folder-name "Folder" [--parent-folder "Parent"]
    google_drive_tool.py delete --file-id FILE_ID

Examples:
    python3 google_drive_tool.py upload ./thumbnail.png --folder-name "order-001" --parent-folder "Fiverr Thumbnails"
    python3 google_drive_tool.py list --folder-name "Fiverr Thumbnails"
    python3 google_drive_tool.py get-link --file-id 1aBcDeFgHiJk
    python3 google_drive_tool.py create-folder --folder-name "order-001" --parent-folder "Fiverr Thumbnails"
    python3 google_drive_tool.py delete --file-id 1aBcDeFgHiJk

Output: JSON to stdout. Errors: {"error": "..."} + exit 1.
Delete always trashes — never hard-deletes.
"""

import argparse
import json
import mimetypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from google_auth import get_brand75_credentials

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
]

FOLDER_MIME = "application/vnd.google-apps.folder"

SHARED_DRIVE_KWARGS = {
    "supportsAllDrives": True,
    "includeItemsFromAllDrives": True,
}


def _escape(name: str) -> str:
    """Escape single quotes for Drive query language."""
    return name.replace("\\", "\\\\").replace("'", "\\'")


def _build_drive():
    creds = get_brand75_credentials(SCOPES)
    return build("drive", "v3", credentials=creds)


def _find_folder(drive, name: str, parent_id: str | None = None) -> str | None:
    q = f"mimeType='{FOLDER_MIME}' and name='{_escape(name)}' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    resp = (
        drive.files()
        .list(
            q=q,
            fields="files(id,name)",
            corpora="allDrives",
            **SHARED_DRIVE_KWARGS,
        )
        .execute()
    )
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def _create_folder(drive, name: str, parent_id: str | None = None) -> str:
    metadata = {"name": name, "mimeType": FOLDER_MIME}
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = (
        drive.files()
        .create(body=metadata, fields="id", supportsAllDrives=True)
        .execute()
    )
    return folder["id"]


def _resolve_or_create_folder(drive, folder_name: str, parent_folder: str | None = None) -> str:
    parent_id = None
    if parent_folder:
        parent_id = _find_folder(drive, parent_folder)
        if parent_id is None:
            parent_id = _create_folder(drive, parent_folder)
    folder_id = _find_folder(drive, folder_name, parent_id)
    if folder_id is None:
        folder_id = _create_folder(drive, folder_name, parent_id)
    return folder_id


def action_upload(file_path: str, folder_name: str | None, parent_folder: str | None) -> dict:
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    drive = _build_drive()

    parents = None
    if folder_name:
        folder_id = _resolve_or_create_folder(drive, folder_name, parent_folder)
        parents = [folder_id]

    mimetype, _ = mimetypes.guess_type(str(path))
    if mimetype is None:
        mimetype = "application/octet-stream"

    metadata = {"name": path.name}
    if parents:
        metadata["parents"] = parents

    media = MediaFileUpload(str(path), mimetype=mimetype, resumable=True)
    created = (
        drive.files()
        .create(
            body=metadata,
            media_body=media,
            fields="id,name,webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )
    return {
        "status": "ok",
        "id": created["id"],
        "name": created["name"],
        "webViewLink": created.get("webViewLink"),
    }


def action_list(folder_name: str) -> dict:
    drive = _build_drive()
    folder_id = _find_folder(drive, folder_name)
    if folder_id is None:
        return {"error": f"Folder not found: {folder_name}"}

    resp = (
        drive.files()
        .list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="files(id,name,createdTime,webViewLink)",
            corpora="allDrives",
            **SHARED_DRIVE_KWARGS,
        )
        .execute()
    )
    return {"folder": folder_name, "folderId": folder_id, "files": resp.get("files", [])}


def action_get_link(file_id: str) -> dict:
    drive = _build_drive()
    f = (
        drive.files()
        .get(fileId=file_id, fields="id,name,webViewLink", supportsAllDrives=True)
        .execute()
    )
    return {"id": f["id"], "name": f["name"], "webViewLink": f.get("webViewLink")}


def action_create_folder(folder_name: str, parent_folder: str | None) -> dict:
    drive = _build_drive()
    folder_id = _resolve_or_create_folder(drive, folder_name, parent_folder)
    return {"status": "ok", "id": folder_id, "name": folder_name}


def action_delete(file_id: str) -> dict:
    drive = _build_drive()
    f = drive.files().get(fileId=file_id, fields="id,name", supportsAllDrives=True).execute()
    drive.files().update(fileId=file_id, body={"trashed": True}, supportsAllDrives=True).execute()
    return {"status": "trashed", "id": f["id"], "name": f["name"]}


def main():
    parser = argparse.ArgumentParser(
        description="Google Drive tool for Atlas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  upload ./thumbnail.png --folder-name 'order-001' --parent-folder 'Fiverr Thumbnails'\n"
            "  list --folder-name 'Fiverr Thumbnails'\n"
            "  get-link --file-id 1aBcDeFgHiJk\n"
            "  create-folder --folder-name 'order-001' --parent-folder 'Fiverr Thumbnails'\n"
            "  delete --file-id 1aBcDeFgHiJk\n"
        ),
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p_up = sub.add_parser("upload", help="Upload a local file to Drive")
    p_up.add_argument("file_path", help="Local file path")
    p_up.add_argument("--folder-name", dest="folder_name", help="Destination folder name")
    p_up.add_argument("--parent-folder", dest="parent_folder", help="Parent folder name")

    p_ls = sub.add_parser("list", help="List files in a Drive folder")
    p_ls.add_argument("--folder-name", dest="folder_name", required=True)

    p_link = sub.add_parser("get-link", help="Get a file's webViewLink by ID")
    p_link.add_argument("--file-id", dest="file_id", required=True)

    p_mk = sub.add_parser("create-folder", help="Create a Drive folder")
    p_mk.add_argument("--folder-name", dest="folder_name", required=True)
    p_mk.add_argument("--parent-folder", dest="parent_folder")

    p_rm = sub.add_parser("delete", help="Move a file to trash by ID (never hard-deletes)")
    p_rm.add_argument("--file-id", dest="file_id", required=True)

    args = parser.parse_args()

    try:
        if args.action == "upload":
            result = action_upload(args.file_path, args.folder_name, args.parent_folder)
        elif args.action == "list":
            result = action_list(args.folder_name)
        elif args.action == "get-link":
            result = action_get_link(args.file_id)
        elif args.action == "create-folder":
            result = action_create_folder(args.folder_name, args.parent_folder)
        elif args.action == "delete":
            result = action_delete(args.file_id)
        print(json.dumps(result, indent=2))
        if isinstance(result, dict) and "error" in result:
            sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
