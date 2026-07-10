import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from google_auth import get_brand75_credentials

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/drive.file',
]


def get_drive_service():
    creds = get_brand75_credentials(SCOPES)
    return build('drive', 'v3', credentials=creds)


def escape_query(text):
    """Escape single quotes and backslashes for Drive API query strings."""
    return text.replace('\\', '\\\\').replace("'", "\\'")


def build_title_query(title_input, folder_id=None):
    """Build Drive query with per-word partial matching, including fullText search.

    Each whitespace-delimited word becomes its own `(name contains '...' or fullText contains '...')`
    clause joined by AND.
    """
    words = title_input.split()
    name_and_fulltext_parts = []
    for w in words:
        escaped_word = escape_query(w)
        name_and_fulltext_parts.append(f"(name contains '{escaped_word}' or fullText contains '{escaped_word}')")
    
    parts = [" and ".join(name_and_fulltext_parts)] # Combine all word parts with AND
    parts.append("trashed=false")

    if folder_id:
        parts.append(f"'{escape_query(folder_id)}' in parents")
    
    return " and ".join(parts)


def build_date_range_query(after=None, before=None, folder_id=None):
    """Build Drive query for docs modified within a date range (fallback)."""
    parts = [
        "mimeType = 'application/vnd.google-apps.document'",
        "trashed=false",
    ]
    if after:
        parts.append(f"modifiedTime >= '{after}T00:00:00'")
    if before:
        parts.append(f"modifiedTime <= '{before}T23:59:59'")
    if folder_id:
        parts.append(f"'{escape_query(folder_id)}' in parents")
    return " and ".join(parts)


def search_files(drive, query, order_by="modifiedTime desc", limit=25,
                 include_all_drives=True): # Default to True
    """Run a Drive files.list query and return all results (paginated).

    When include_all_drives is True, adds includeItemsFromAllDrives and
    supportsAllDrives to reach files in Meet/Gemini auto-generated folders
    that are invisible to the standard corpus.
    """
    files = []
    page_token = None
    while True:
        kwargs = dict(
            q=query,
            fields='nextPageToken, files(id, name, mimeType, modifiedTime, createdTime, parents)', # Added parents field
            orderBy=order_by,
            pageSize=min(limit - len(files), 100),
            pageToken=page_token,
        )
        kwargs['includeItemsFromAllDrives'] = include_all_drives # Always apply this based on param
        kwargs['supportsAllDrives'] = include_all_drives # Always apply this based on param
        kwargs['spaces'] = 'drive' # Always search 'drive' space

        resp = drive.files().list(**kwargs).execute()
        files.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token or len(files) >= limit:
            break
    return files[:limit]


def fetch_file_by_id(drive, file_id):
    """Fetch a single file's metadata by direct ID (bypasses search index)."""
    return drive.files().get(
        fileId=file_id,
        fields='id, name, mimeType, modifiedTime, createdTime, parents, trashed',
        supportsAllDrives=True,
    ).execute()


def read_file_content(drive, file_id, mime_type):
    """Export or download file content as plain text."""
    if mime_type == 'application/vnd.google-apps.document':
        content = drive.files().export_media(fileId=file_id, mimeType='text/plain').execute()
        return content.decode('utf-8')
    elif mime_type.startswith('text/'):
        content = drive.files().get_media(fileId=file_id).execute()
        return content.decode('utf-8')
    else:
        return None


def download_drive_file(drive, file_id, local_path):
    """Download a file from Drive to a local path (binary mode for all types)."""
    request = drive.files().get_media(fileId=file_id)
    # Use io.FileIO and httplib2.Http for resumable downloads if needed for large files
    # For smaller files, direct execute() should work.
    try:
        file_content = request.execute()
        with open(local_path, 'wb') as f:
            f.write(file_content)
        return True
    except HttpError as e:
        print(f"Error downloading file {file_id}: {e}", file=sys.stderr)
        return False


def get_folder_id(drive, folder_name):
    query = f"name = '{escape_query(folder_name)}' and mimeType = 'application/vnd.google-apps.folder' and trashed=false"
    results = drive.files().list(q=query, spaces='drive', fields='files(id, name)', includeItemsFromAllDrives=True, supportsAllDrives=True).execute() # Added allDrives support
    items = results.get('files', [])
    return items[0]['id'] if items else None


def print_file_table(files):
    """Pretty-print a list of files."""
    if not files:
        print("  (no results)")
        return
    for f in files:
        mod = f.get('modifiedTime', '?')[:10]
        created = f.get('createdTime', '?')[:10]
        parents = ', '.join(f.get('parents', ['None']))
        print(f"  Modified: {mod}  Created: {created}  Name: {f['name']}")
        print(f"           ID: {f['id']}  Type: {f['mimeType']}  Parents: {parents}")


# ── CLI ──────────────────────────────────────────────────────────────────

def print_usage():
    usage = """Usage:
  read_gdoc_by_title.py "search words"              Search by title words (AND, includes fullText)
  read_gdoc_by_title.py --id FILE_ID                Fetch doc directly by ID
  read_gdoc_by_title.py "words" --in-folder "Name"   Search within a folder (name AND fullText)
  read_gdoc_by_title.py --after YYYY-MM-DD           List docs modified after date
  read_gdoc_by_title.py --after YYYY-MM-DD --before YYYY-MM-DD
  read_gdoc_by_title.py --list-folders               List all Drive folders
  read_gdoc_by_title.py --find-folder "Name"         Get folder ID by name
  read_gdoc_by_title.py --list-folder-contents FOLDER_ID   List all files in a specific folder
  read_gdoc_by_title.py --download-file-id FILE_ID --output-path LOCAL_PATH   Download a specific file

Options:
  --id ID        Fetch a file directly by Google Drive ID (skips search)
  --list-only    List matching files without reading content
  --limit N      Max results (default 25)
  --in-folder    Restrict search to a named folder (for title/fullText search)
  --after DATE   Fallback: list docs modified on/after YYYY-MM-DD
  --before DATE  Fallback: list docs modified on/before YYYY-MM-DD
  --list-folder-contents FOLDER_ID  List all files directly within this folder ID
  --download-file-id FILE_ID  Download a file by its ID
  --output-path LOCAL_PATH    Local path to save the downloaded file
"""
    print(usage, file=sys.stderr)


def parse_args(argv):
    args = {
        'title': None,
        'file_id': None,
        'folder_name': None,
        'after': None,
        'before': None,
        'list_only': False,
        'list_folders': False,
        'find_folder': None,
        'list_folder_contents': None,
        'download_file_id': None, # New argument
        'output_path': None,      # New argument
        'limit': 25,
    }
    i = 1
    positional_done = False
    while i < len(argv):
        a = argv[i]
        if a == '--id' and i + 1 < len(argv):
            args['file_id'] = argv[i + 1]; i += 2
        elif a == '--in-folder' and i + 1 < len(argv):
            args['folder_name'] = argv[i + 1]; i += 2
        elif a == '--after' and i + 1 < len(argv):
            args['after'] = argv[i + 1]; i += 2
        elif a == '--before' and i + 1 < len(argv):
            args['before'] = argv[i + 1]; i += 2
        elif a == '--limit' and i + 1 < len(argv):
            args['limit'] = int(argv[i + 1]); i += 2
        elif a == '--list-only':
            args['list_only'] = True; i += 1
        elif a == '--list-folders':
            args['list_folders'] = True; i += 1
        elif a == '--find-folder' and i + 1 < len(argv):
            args['find_folder'] = argv[i + 1]; i += 2
        elif a == '--list-folder-contents' and i + 1 < len(argv):
            args['list_folder_contents'] = argv[i + 1]; i += 2
        elif a == '--download-file-id' and i + 1 < len(argv): # New argument handling
            args['download_file_id'] = argv[i + 1]; i += 2
        elif a == '--output-path' and i + 1 < len(argv):      # New argument handling
            args['output_path'] = argv[i + 1]; i += 2
        elif not a.startswith('--') and not positional_done:
            args['title'] = a; positional_done = True; i += 1
        else:
            print(f"Unknown argument: {a}", file=sys.stderr)
            print_usage(); sys.exit(1)
    return args


def main():
    args = parse_args(sys.argv)
    drive = get_drive_service()

    # --download-file-id and --output-path: direct download
    if args['download_file_id'] and args['output_path']:
        file_id_to_download = args['download_file_id']
        local_output_path = os.path.expanduser(args['output_path'])
        print(f"Downloading file ID {file_id_to_download} to {local_output_path}...", file=sys.stderr)
        if download_drive_file(drive, file_id_to_download, local_output_path):
            print(f"Successfully downloaded {file_id_to_download} to {local_output_path}", file=sys.stderr)
        else:
            print(f"Failed to download file {file_id_to_download}", file=sys.stderr)
            sys.exit(1)
        return

    # --id: direct fetch by file ID (bypasses search entirely)
    if args['file_id']:
        fid = args['file_id']
        print(f"Fetching file by ID: {fid}", file=sys.stderr)
        meta = fetch_file_by_id(drive, fid)
        print(f"  name={meta['name']}", file=sys.stderr)
        print(f"  type={meta['mimeType']}", file=sys.stderr)
        print(f"  modified={meta.get('modifiedTime', '?')}\n", file=sys.stderr)

        if args['list_only']:
            print_file_table([meta])
            return

        content = read_file_content(drive, meta['id'], meta['mimeType'])
        if content:
            print(content)
        else:
            print(f"Cannot extract text from {meta['mimeType']}. Use --list-only to see matches.", file=sys.stderr)
            sys.exit(1)
        return

    # --list-folders
    if args['list_folders']:
        query = "mimeType = 'application/vnd.google-apps.folder' and trashed=false"
        folders = search_files(drive, query, limit=200)
        if not folders:
            print("No folders found.")
        else:
            for f in folders:
                print(f"  {f['name']}  (id={f['id']})")
        return

    # --find-folder
    if args['find_folder']:
        fid = get_folder_id(drive, args['find_folder'])
        if fid:
            print(f"Folder '{args['find_folder']}' → {fid}")
        else:
            print(f"Folder '{args['find_folder']}' not found.", file=sys.stderr)
            sys.exit(1)
        return

    # --list-folder-contents (New functionality)
    if args['list_folder_contents']:
        folder_id_to_list = args['list_folder_contents']
        query = f"'{escape_query(folder_id_to_list)}' in parents and trashed=false"
        print(f"Listing contents of folder ID: {folder_id_to_list}\n", file=sys.stderr)
        files = search_files(drive, query, limit=args['limit'])
        if not files:
            print(f"No files found in folder ID '{folder_id_to_list}'.", file=sys.stderr)
            sys.exit(1)
        print(f"Found {len(files)} file(s) in folder:")
        print_file_table(files)
        return

    # Resolve optional folder (for title/fullText search filtering)
    folder_id = None
    if args['folder_name']:
        folder_id = get_folder_id(drive, args['folder_name'])
        if not folder_id:
            print(f"Error: Folder '{args['folder_name']}' not found.", file=sys.stderr)
            sys.exit(1)

    # Date-range fallback (--after / --before without a title)
    if not args['title'] and (args['after'] or args['before']):
        query = build_date_range_query(args['after'], args['before'], folder_id)
        print(f"Query: {query}\n", file=sys.stderr)
        files = search_files(drive, query, limit=args['limit'])
        print(f"Found {len(files)} doc(s) modified in range:")
        print_file_table(files)
        return

    # Title/FullText search (primary path)
    if not args['title']:
        print_usage()
        sys.exit(1)

    query = build_title_query(args['title'], folder_id) # Pass folder_id if provided
    print(f"Query: {query}\n", file=sys.stderr)
    files = search_files(drive, query, limit=args['limit'])

    # Fallback 2: date-range search if provided (only if no title matches found)
    if not files and (args['after'] or args['before']):
        print("No title/fullText matches. Falling back to date-range search...\n", file=sys.stderr)
        query = build_date_range_query(args['after'], args['before'], folder_id)
        files = search_files(drive, query, limit=args['limit'])
        if not files:
            print("No documents found in date range either.", file=sys.stderr)
            sys.exit(1)
        print(f"Found {len(files)} doc(s) by date range:")
        print_file_table(files)
        return

    if not files:
        print(f"No files found matching '{args['title']}' (or containing keywords).", file=sys.stderr)
        sys.exit(1)

    if args['list_only']:
        print(f"Found {len(files)} file(s):\n")
        print_file_table(files)
        return

    # Read the first match
    target = files[0]
    print(f"Found {len(files)} match(es). Reading: {target['name']}", file=sys.stderr)
    print(f"  id={target['id']}  type={target['mimeType']}", file=sys.stderr)
    print(f"  modified={target.get('modifiedTime', '?')}  parents={', '.join(target.get('parents', ['None']))}\n", file=sys.stderr)

    content = read_file_content(drive, target['id'], target['mimeType'])
    if content:
        print(content)
    else:
        print(f"Cannot extract text from {target['mimeType']}. Use --list-only to see matches.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except HttpError as e:
        print(f"Google API error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
