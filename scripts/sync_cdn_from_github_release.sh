#!/usr/bin/env bash
# Sync native + Electron installers from GitHub Releases to VPS CDN.
# Modes:
#   install (default) — copy to /opt/krexion/downloads/ on krexion-vps runner
#   download-only     — write to ./dist-cdn/ for SCP from ubuntu-latest CI job
set -euo pipefail

VER="${1:-$(tr -d '[:space:]' < backend/VERSION)}"
REPO="${GITHUB_REPOSITORY:-krexion-com-final/krexion.com-final}"
TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
MODE="${CDN_SYNC_MODE:-install}"
if [ -z "$TOKEN" ]; then
  echo "::warning::No GH token — skipping CDN sync"
  exit 0
fi

ROOT_DIR="$(pwd)"
if [ "$MODE" = "download-only" ]; then
  NAT_INSTALL_DIR="$ROOT_DIR/dist-cdn/windows"
  DESK_INSTALL_DIR="$ROOT_DIR/dist-cdn/desktop"
else
  NAT_INSTALL_DIR="/opt/krexion/downloads/windows"
  DESK_INSTALL_DIR="/opt/krexion/downloads/desktop"
fi

WORKDIR="${RUNNER_TEMP:-/tmp}/krexion-cdn-sync-$$"
mkdir -p "$WORKDIR"
trap 'rm -rf "$WORKDIR"' EXIT

download_release_assets() {
  local TAG="$1"
  local OUTDIR="$2"
  shift 2
  local -a PATTERNS=("$@")
  mkdir -p "$OUTDIR"
  echo ">> Fetching release tag: $TAG"
  local HTTP
  HTTP=$(curl -sS --max-time 45 -o "$WORKDIR/rel.json" -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$REPO/releases/tags/$TAG" || echo "000")
  if [ "$HTTP" != "200" ]; then
    echo "::warning::Release $TAG not found (HTTP $HTTP) — skip"
    return 0
  fi
  mapfile -t ASSETS < <(python3 - "$WORKDIR/rel.json" "${PATTERNS[@]}" <<'PY'
import json, sys
path, *patterns = sys.argv[1:]
with open(path) as f:
    data = json.load(f)
for asset in data.get("assets", []):
    name = asset.get("name") or ""
    if any(name.startswith(p) or name == p for p in patterns):
        print(f"{asset['url']}\t{name}")
PY
)
  if [ "${#ASSETS[@]}" -eq 0 ]; then
    echo "::warning::No matching assets on $TAG"
    return 0
  fi
  for row in "${ASSETS[@]}"; do
    [ -z "$row" ] && continue
    URL="${row%%$'\t'*}"
    NAME="${row#*$'\t'}"
    echo ">> Downloading $NAME ..."
    curl -sSL --max-time 3600 --retry 3 --retry-delay 5 \
      -H "Authorization: Bearer $TOKEN" \
      -H "Accept: application/octet-stream" \
      -o "$OUTDIR/$NAME" "$URL"
    ls -lah "$OUTDIR/$NAME"
  done
}

# ── Native Windows installer ──
NAT_DIR="$WORKDIR/native"
download_release_assets "v${VER}" "$NAT_DIR" "Krexion-Setup-"
if compgen -G "$NAT_DIR/Krexion-Setup-*.exe" >/dev/null; then
  if [ "$MODE" != "download-only" ]; then
    AVAIL_KB=$(df -Pk /opt/krexion/downloads 2>/dev/null | awk 'NR==2{print $4}')
    if [ -n "$AVAIL_KB" ] && [ "$AVAIL_KB" -lt 2500000 ]; then
      echo "::error::VPS disk low (<2.5GB free) — prune old installers first"
      df -h /opt/krexion/downloads || true
      exit 1
    fi
  fi
  mkdir -p "$NAT_INSTALL_DIR"
  cp -f "$NAT_DIR"/Krexion-Setup-*.exe "$NAT_INSTALL_DIR/"
  if [ "$MODE" != "download-only" ]; then
  cd "$NAT_INSTALL_DIR"
  if [ -f "Krexion-Setup-v${VER}.exe" ]; then
    cp -f "Krexion-Setup-v${VER}.exe" "Krexion-Setup-latest.exe"
  else
    NEWEST=$(ls -1t Krexion-Setup-v*.exe 2>/dev/null | head -1)
    [ -n "$NEWEST" ] && cp -f "$NEWEST" "Krexion-Setup-latest.exe"
  fi
  KEEP_N=2
  mapfile -t KEEP_VER < <(ls -1t Krexion-Setup-v*.exe 2>/dev/null | head -n "$KEEP_N")
  for f in Krexion-Setup-v*.exe; do
    [ -f "$f" ] || continue
    keep=0
    for k in "${KEEP_VER[@]}"; do [ "$f" = "$k" ] && keep=1 && break; done
    [ "$keep" = "0" ] && rm -f -- "$f" && echo "pruned $f"
  done
  chmod -R a+r .
  fi
  echo "✅ Native CDN: Krexion-Setup-v${VER}.exe"
fi

# ── Electron desktop installer ──
DESK_DIR="$WORKDIR/desktop"
download_release_assets "desktop-v${VER}" "$DESK_DIR" "Krexion-Desktop-Setup-" "latest.yml"
if compgen -G "$DESK_DIR/Krexion-Desktop-Setup-*.exe" >/dev/null || [ -f "$DESK_DIR/latest.yml" ]; then
  mkdir -p "$DESK_INSTALL_DIR"
  cp -f "$DESK_DIR"/Krexion-Desktop-Setup-*.exe "$DESK_INSTALL_DIR/" 2>/dev/null || true
  cp -f "$DESK_DIR"/Krexion-Desktop-Setup-*.exe.blockmap "$DESK_INSTALL_DIR/" 2>/dev/null || true
  cp -f "$DESK_DIR/latest.yml" "$DESK_INSTALL_DIR/" 2>/dev/null || true
  if [ "$MODE" != "download-only" ]; then
  cd "$DESK_INSTALL_DIR"
  if [ -f "Krexion-Desktop-Setup-${VER}.exe" ]; then
    cp -f "Krexion-Desktop-Setup-${VER}.exe" "Krexion-Desktop-Setup-latest.exe"
  else
    NEWEST=$(ls -1t Krexion-Desktop-Setup-*.exe 2>/dev/null | grep -v latest | head -1)
    [ -n "$NEWEST" ] && cp -f "$NEWEST" "Krexion-Desktop-Setup-latest.exe"
  fi
  KEEP_LIST="Krexion-Desktop-Setup-latest.exe latest.yml"
  if [ -f latest.yml ]; then
    YML_PATH=$(grep -E '^[[:space:]]*path:' latest.yml | head -1 | sed 's/.*path:[[:space:]]*//' | tr -d '"' | tr -d "'" | tr -d '\r')
    [ -n "$YML_PATH" ] && KEEP_LIST="$KEEP_LIST $YML_PATH ${YML_PATH}.blockmap"
  fi
  mapfile -t KEEP_VER < <(ls -1t Krexion-Desktop-Setup-*.exe 2>/dev/null | grep -v latest | head -n 2)
  for f in "${KEEP_VER[@]}"; do KEEP_LIST="$KEEP_LIST $f ${f}.blockmap"; done
  for f in Krexion-Desktop-Setup-*.exe Krexion-Desktop-Setup-*.exe.blockmap; do
    [ -f "$f" ] || continue
    keep=0
    for k in $KEEP_LIST; do [ "$f" = "$k" ] && keep=1 && break; done
    [ "$f" = "Krexion-Desktop-Setup-latest.exe" ] && keep=1
    [ "$keep" = "0" ] && rm -f -- "$f" && echo "pruned $f"
  done
  chmod -R a+r .
  fi
  echo "✅ Desktop CDN: Krexion-Desktop-Setup-${VER}.exe"
fi

echo "CDN sync complete for v${VER}"
