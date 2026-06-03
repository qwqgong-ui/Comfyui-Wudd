#!/usr/bin/env bash
set -euo pipefail

URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
DESTINATION="$REPO_ROOT/bin"
KEEP_ARCHIVE=0
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage: scripts/update_ffmpeg_linux.sh [options]

Downloads BtbN's latest Linux x86_64 GPL static FFmpeg build and installs
ffmpeg, ffprobe, and ffplay into this custom node's ./bin folder.

Options:
  --url URL             Override the FFmpeg .tar.xz download URL.
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

DESTINATION="$(mkdir -p "$DESTINATION" && cd "$DESTINATION" && pwd)"
TMP_ROOT="$(mktemp -d -t wudd_ffmpeg_XXXXXX)"
ARCHIVE_PATH="$TMP_ROOT/ffmpeg.tar.xz"
EXTRACT_DIR="$TMP_ROOT/extract"
REQUIRED_FILES=(ffmpeg ffprobe ffplay)

echo "FFmpeg source: $URL"
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

echo "Downloading FFmpeg archive..."
if command -v curl >/dev/null 2>&1; then
    curl -fL "$URL" -o "$ARCHIVE_PATH"
elif command -v wget >/dev/null 2>&1; then
    wget -O "$ARCHIVE_PATH" "$URL"
else
    echo "curl or wget is required." >&2
    exit 1
fi

echo "Extracting archive..."
tar -xJf "$ARCHIVE_PATH" -C "$EXTRACT_DIR"

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

"$DESTINATION/ffmpeg" -version | head -n 1 || true
echo "Done. Restart ComfyUI to make sure nodes use the updated binary."
