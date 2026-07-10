#!/usr/bin/env python3
"""Google Docs CLI tool for Atlas — create and write documents.

Replaces gog docs create / gog docs write.

Usage:
    google_docs_tool.py create "Document Title" [--folder FOLDER_ID]
    google_docs_tool.py write DOC_ID "Content to write"
    google_docs_tool.py write DOC_ID --stdin

Output (create): JSON with {"file": {"id": "...", "name": "..."}}
Output (write):  JSON with {"status": "ok", "documentId": "..."}
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from google_auth import get_brand75_credentials

from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
]


def action_create(title: str, folder_id: str | None = None) -> dict:
    creds = get_brand75_credentials(SCOPES)
    drive = build("drive", "v3", credentials=creds)

    metadata = {"name": title, "mimeType": "application/vnd.google-apps.document"}
    if folder_id:
        metadata["parents"] = [folder_id]

    doc = drive.files().create(body=metadata, fields="id,name").execute()
    return {"file": {"id": doc["id"], "name": doc["name"]}}


def action_write(doc_id: str, content: str) -> dict:
    creds = get_brand75_credentials(SCOPES)
    docs = build("docs", "v1", credentials=creds)

    # Clear existing body content (except the trailing newline), then insert new text.
    doc = docs.documents().get(documentId=doc_id).execute()
    body = doc.get("body", {})
    end_index = body.get("content", [{}])[-1].get("endIndex", 1)

    requests = []
    # Delete existing content if any (preserve the mandatory trailing newline at index end_index-1)
    if end_index > 2:
        requests.append({"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}})
    # Insert new content
    requests.append({"insertText": {"location": {"index": 1}, "text": content}})

    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    return {"status": "ok", "documentId": doc_id}


def main():
    parser = argparse.ArgumentParser(description="Google Docs tool for Atlas")
    sub = parser.add_subparsers(dest="action", required=True)

    p_create = sub.add_parser("create", help="Create a new Google Doc")
    p_create.add_argument("title", help="Document title")
    p_create.add_argument("--folder", dest="folder_id", help="Parent folder ID")

    p_write = sub.add_parser("write", help="Write content to an existing doc")
    p_write.add_argument("doc_id", help="Document ID")
    p_write.add_argument("content", nargs="?", default=None, help="Content to write")
    p_write.add_argument("--stdin", action="store_true", help="Read content from stdin")

    args = parser.parse_args()

    try:
        if args.action == "create":
            result = action_create(args.title, args.folder_id)
        elif args.action == "write":
            if args.stdin:
                content = sys.stdin.read()
            elif args.content is not None:
                content = args.content
            else:
                print(json.dumps({"error": "Provide content as argument or use --stdin"}))
                sys.exit(1)
            result = action_write(args.doc_id, content)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
