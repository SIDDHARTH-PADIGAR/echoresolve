#!/usr/bin/env bash
set -euo pipefail

source /etc/os-release
if [ "${ID:-}" != "ubuntu" ] || [ "$(uname -m)" != "x86_64" ]; then
    echo "ERROR: Expected Ubuntu x86_64."
    exit 2
fi

for cmd in curl ldd python3; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: Missing required Linux tool: $cmd"
        exit 2
    fi
done

BASE="$HOME/.local/share/echoresolve/voice-runtime"
BIN="$BASE/bin"
MODEL="$BASE/model"
mkdir -p "$BIN" "$MODEL"

echo "Distribution: $PRETTY_NAME"
echo "Memory:"
free -h
echo "Disk:"
df -h "$HOME"

download() {
    local url="$1"
    local dest="$2"

    if [ -s "$dest" ]; then
        echo "Already downloaded: $(basename "$dest")"
        return
    fi

    echo "Downloading $(basename "$dest")"
    curl -fL --retry 3 --retry-delay 2 "$url" -o "$dest.part"
    mv "$dest.part" "$dest"
}

ROOT="https://huggingface.co/LiquidAI/LFM2.5-Audio-1.5B-GGUF/resolve/main"
SERVER="$(find "$BIN" -type f -name llama-liquid-audio-server -print -quit || true)"

if [ -z "$SERVER" ]; then
    ARCHIVE="$BASE/runner.zip"

    download "$ROOT/runners/llama-liquid-audio-ubuntu-x64.zip?download=true" "$ARCHIVE"

    python3 -c \
        'import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' \
        "$ARCHIVE" "$BIN"

    SERVER="$(find "$BIN" -type f -name llama-liquid-audio-server -print -quit || true)"
    rm -f "$ARCHIVE"
fi

if [ -z "$SERVER" ] || [ ! -f "$SERVER" ]; then
    echo "ERROR: Expected audio server was not found in the runner archive."
    find "$BIN" -maxdepth 4 -type f -print
    exit 3
fi

chmod +x "$SERVER"
export LD_LIBRARY_PATH="$(dirname "$SERVER"):$BIN:$BIN/lib:${LD_LIBRARY_PATH:-}"

echo
echo "========== CHECKING SERVER LIBRARIES =========="
DEPS="$(ldd "$SERVER" 2>&1 || true)"
printf '%s\n' "$DEPS"

if grep -q "not found" <<< "$DEPS"; then
    echo "ERROR: Native library dependency is missing."
    exit 3
fi

echo
echo "========== DOWNLOADING Q4 MODEL FILES =========="

download "$ROOT/LFM2.5-Audio-1.5B-Q4_0.gguf?download=true" \
    "$MODEL/LFM2.5-Audio-1.5B-Q4_0.gguf"

download "$ROOT/mmproj-LFM2.5-Audio-1.5B-Q4_0.gguf?download=true" \
    "$MODEL/mmproj-LFM2.5-Audio-1.5B-Q4_0.gguf"

download "$ROOT/tokenizer-LFM2.5-Audio-1.5B-Q4_0.gguf?download=true" \
    "$MODEL/tokenizer-LFM2.5-Audio-1.5B-Q4_0.gguf"

download "$ROOT/vocoder-LFM2.5-Audio-1.5B-Q4_0.gguf?download=true" \
    "$MODEL/vocoder-LFM2.5-Audio-1.5B-Q4_0.gguf"

# Reject incomplete or unexpected downloads before attempting inference.
test "$(stat -c %s "$MODEL/LFM2.5-Audio-1.5B-Q4_0.gguf")" -gt 500000000
test "$(stat -c %s "$MODEL/mmproj-LFM2.5-Audio-1.5B-Q4_0.gguf")" -gt 150000000
test "$(stat -c %s "$MODEL/tokenizer-LFM2.5-Audio-1.5B-Q4_0.gguf")" -gt 30000000
test "$(stat -c %s "$MODEL/vocoder-LFM2.5-Audio-1.5B-Q4_0.gguf")" -gt 75000000

du -h "$MODEL"/*.gguf

echo
echo "========== STARTING NATIVE AUDIO SERVER =========="

# Do not kill or reuse a server that this script does not own.
if [ -f "$BASE/server.pid" ]; then
    OLD_PID="$(cat "$BASE/server.pid")"
    if [[ "$OLD_PID" =~ ^[0-9]+$ ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" || true
        sleep 2
    fi
    rm -f "$BASE/server.pid"
fi

if curl -fsS http://127.0.0.1:8080/v1/models -o /dev/null 2>/dev/null; then
    echo "ERROR: Port 8080 already serves an API. Refusing to reuse it."
    exit 4
fi

nohup "$SERVER" \
    -m "$MODEL/LFM2.5-Audio-1.5B-Q4_0.gguf" \
    -mm "$MODEL/mmproj-LFM2.5-Audio-1.5B-Q4_0.gguf" \
    -mv "$MODEL/vocoder-LFM2.5-Audio-1.5B-Q4_0.gguf" \
    --tts-speaker-file "$MODEL/tokenizer-LFM2.5-Audio-1.5B-Q4_0.gguf" \
    > "$BASE/server.log" 2>&1 < /dev/null &

echo $! > "$BASE/server.pid"

READY=0
for attempt in $(seq 1 120); do
    if curl -fsS http://127.0.0.1:8080/v1/models \
        -o "$BASE/models.json" 2>/dev/null; then
        READY=1
        break
    fi

    PID="$(cat "$BASE/server.pid")"
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "ERROR: Audio server exited."
        tail -n 80 "$BASE/server.log" || true
        exit 4
    fi
    sleep 1
done

if [ "$READY" -ne 1 ]; then
    echo "ERROR: Audio server readiness timed out."
    tail -n 80 "$BASE/server.log" || true
    exit 4
fi

echo "Model server API is responding. Inference still needs to be tested."
cat "$BASE/models.json"
echo
echo "VOICE_SERVER_STARTED"