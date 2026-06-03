#!/usr/bin/env bash
set -euo pipefail

URL=""
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
DESTINATION="$REPO_ROOT/bin"
KEEP_ARCHIVE=0
DRY_RUN=0
RELEASES_API="https://api.github.com/repos/libjxl/libjxl/releases"

usage() {
    cat <<'EOF'
Usage: scripts/update_jpegli_linux.sh [options]

Downloads the newest libjxl Linux x86_64 static release asset that contains
cjpegli, then installs cjpegli and djpegli into this custom node's ./bin folder.

Options:
  --url URL             Override the libjxl .tar.gz download URL.
  --destination DIR     Install destination. Defaults to ../bin.
  --keep-archive        Keep downloaded/extracted temporary files.
  --dry-run             Print actions without downloading or writing files.
  -h, --help            Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --url)
            URL="${2:?missing value for --url}"
            shift 2
            ;;
        --destination)
            DESTINATION="${2:?missing value for --destination}"
            shift 2
            ;;
        --keep-archive)
            KEEP_ARCHIVE=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "$URL" ]]; then
    PYTHON_BIN="${PYTHON:-}"
    if [[ -z "$PYTHON_BIN" ]]; then
        if command -v python3 >/dev/null 2>&1; then
            PYTHON_BIN="python3"
        elif command -v python >/dev/null 2>&1; then
            PYTHON_BIN="python"
        fi
    fi

    if [[ -z "$PYTHON_BIN" ]]; then
        echo "python3 or python is required to discover the latest libjxl Linux static asset." >&2
        echo "Pass --url to use a specific release archive without discovery." >&2
        exit 1
    fi

    URL="$("$PYTHON_BIN" - "$RELEASES_API" <<'PY'
import json
import sys
import urllib.request

api_url = sys.argv[1]
with urllib.request.urlopen(api_url) as response:
    releases = json.load(response)

for release in releases:
    if release.get("draft"):
        continue
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith("jxl-linux-x86_64-static") and name.endswith(".tar.gz"):
            print(asset["browser_download_url"])
            raise SystemExit(0)

raise SystemExit("No jxl-linux-x86_64-static*.tar.gz asset found in libjxl releases.")
PY
)"
fi

DESTINATION="$(mkdir -p "$DESTINATION" && cd "$DESTINATION" && pwd)"
TMP_ROOT="$(mktemp -d -t wudd_jpegli_XXXXXX)"
ARCHIVE_PATH="$TMP_ROOT/jxl-linux-static.tar.gz"
EXTRACT_DIR="$TMP_ROOT/extract"
REQUIRED_FILES=(cjpegli)
OPTIONAL_FILES=(djpegli)

echo "Jpegli source: $URL"
echo "Destination:   $DESTINATION"

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Dry run only; no files will be downloaded or changed."
    rm -rf "$TMP_ROOT"
    exit 0
fi

cleanup() {
    if [[ "$KEEP_ARCHIVE" -eq 0 ]]; then
        rm -rf "$TMP_ROOT"
    else
        echo "Kept temporary files at $TMP_ROOT"
    fi
}
trap cleanup EXIT

mkdir -p "$EXTRACT_DIR"

echo "Downloading Jpegli archive..."
if command -v curl >/dev/null 2>&1; then
    curl -fL "$URL" -o "$ARCHIVE_PATH"
elif command -v wget >/dev/null 2>&1; then
    wget -O "$ARCHIVE_PATH" "$URL"
else
    echo "curl or wget is required." >&2
    exit 1
fi

echo "Extracting archive..."
tar -xzf "$ARCHIVE_PATH" -C "$EXTRACT_DIR"

for file_name in "${REQUIRED_FILES[@]}"; do
    match="$(find "$EXTRACT_DIR" -type f -name "$file_name" | head -n 1)"
    if [[ -z "$match" ]]; then
        echo "Archive did not contain $file_name" >&2
        exit 1
    fi
    cp -f "$match" "$DESTINATION/$file_name"
    chmod +x "$DESTINATION/$file_name"
    echo "Updated $DESTINATION/$file_name"
done

for file_name in "${OPTIONAL_FILES[@]}"; do
    match="$(find "$EXTRACT_DIR" -type f -name "$file_name" | head -n 1)"
    if [[ -n "$match" ]]; then
        cp -f "$match" "$DESTINATION/$file_name"
        chmod +x "$DESTINATION/$file_name"
        echo "Updated $DESTINATION/$file_name"
    fi
done

"$DESTINATION/cjpegli" --help >/dev/null 2>&1 || true
echo "Done. Restart ComfyUI to make sure nodes use the updated binary."
