#!/bin/sh
# Unbidden installer: one wheel, verified, installed as a uv tool with its own Python 3.12.
#
#   curl -LsSf <release>/install.sh | sh                 (once a release exists; see docs/INSTALL.md)
#   sh install.sh --version 0.10.2                        (a fixed version, also a rollback)
#   UNBIDDEN_INSTALL_BASE=http://127.0.0.1:8777 sh install.sh --yes --version 0.10.2   (local artifacts)
#   sh install.sh --uninstall                            (keeps ~/.unbidden and every .unbidden/)
#
# Options     --version X.Y.Z   the release to install (env UNBIDDEN_VERSION); default: the latest GitHub release
#             --yes             no questions: install uv if missing, print PATH lines instead of editing rc files
#             --uninstall       uv tool uninstall unbidden-ai; data stays
#             --help
# Environment UNBIDDEN_INSTALL_BASE  where <base>/unbidden_ai-X.Y.Z-py3-none-any.whl and <base>/SHA256SUMS live
#                                    (default: the GitHub release of that version). http:// only to loopback.
#             UNBIDDEN_REPO          owner/name on GitHub (default satisfymath/unbidden-ai)
#             UV_TOOL_DIR, UV_TOOL_BIN_DIR, UV_INSTALL_DIR  honored as uv does; useful to isolate a test install
#
# Supported: macOS on Apple Silicon (Darwin/arm64) and Linux x86_64 with glibc >= 2.28. Nothing runs with sudo.
# This script is also shipped inside the package (unbidden/distribution/install.sh) for `unbidden update`.

set -eu

NAME="unbidden-ai"
REPO="${UNBIDDEN_REPO:-satisfymath/unbidden-ai}"
VERSION="${UNBIDDEN_VERSION:-}"
BASE="${UNBIDDEN_INSTALL_BASE:-}"
YES=0
UNINSTALL=0

say() { printf '%s\n' "$*" >&2; }
die() { say "unbidden install: $1"; exit "${2:-1}"; }

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --version) [ $# -ge 2 ] || die "--version needs a value"; VERSION="$2"; shift 2 ;;
    --version=*) VERSION="${1#--version=}"; shift ;;
    --yes|-y) YES=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" 2 ;;
  esac
done

if [ -t 0 ] && [ -t 1 ]; then TTY=1; else TTY=0; fi

# A yes/no question; the default is yes. Non-interactive runs take the default without asking.
ask() {
  if [ "$YES" = 1 ] || [ "$TTY" = 0 ]; then return 0; fi
  printf '%s [Y/n] ' "$1" >&2
  read -r answer || answer=""
  case "$answer" in n|N|no|NO|No) return 1 ;; *) return 0 ;; esac
}

# --- platform -------------------------------------------------------------------------------------------------

OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS/$ARCH" in
  Darwin/arm64) PLATFORM="macos-arm64"; SHA256="shasum -a 256" ;;
  Linux/x86_64) PLATFORM="linux-x86_64"; SHA256="sha256sum" ;;
  *)
    die "unsupported platform: $OS $ARCH. Unbidden ships for macOS on Apple Silicon and Linux x86_64 (glibc >= 2.28);
  a source install with uv may still work: https://github.com/$REPO#readme" 3
    ;;
esac
for tool in curl mktemp; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool is required and was not found"
done
command -v ${SHA256%% *} >/dev/null 2>&1 || die "${SHA256%% *} is required to verify the download"

# --- uv -------------------------------------------------------------------------------------------------------

find_uv() {
  if command -v uv >/dev/null 2>&1; then command -v uv; return 0; fi
  for candidate in "${UV_INSTALL_DIR:-}/uv" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [ -n "${candidate%/uv}" ] && [ -x "$candidate" ]; then printf '%s\n' "$candidate"; return 0; fi
  done
  return 1
}

UV="$(find_uv || true)"
if [ -z "$UV" ]; then
  if [ "$UNINSTALL" = 1 ]; then die "uv is not installed, so there is no uv tool to uninstall"; fi
  say "uv (https://docs.astral.sh/uv/) is not installed. It brings Python 3.12 and keeps unbidden in its own environment."
  if ask "Install uv with its official installer (https://astral.sh/uv/install.sh) into ${UV_INSTALL_DIR:-$HOME/.local/bin}?"; then
    curl -LsSf --proto '=https' --tlsv1.2 https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh >&2
    UV="$(find_uv || true)"
    [ -n "$UV" ] || die "uv was installed but not found; add it to PATH and run this again"
  else
    die "install uv first, then run this again" 4
  fi
fi
say "uv: $UV ($("$UV" --version 2>/dev/null || echo unknown))"

BIN_DIR="$("$UV" tool dir --bin)"
DATA_HOME="${UNBIDDEN_HOME:-$HOME/.unbidden}"

# --- uninstall ------------------------------------------------------------------------------------------------

if [ "$UNINSTALL" = 1 ]; then
  if "$UV" tool list 2>/dev/null | grep -q "^$NAME "; then
    if ask "Uninstall $NAME (uv tool uninstall)? Your data stays."; then
      "$UV" tool uninstall "$NAME" >&2
    else
      say "nothing removed"
      exit 0
    fi
  else
    say "$NAME is not installed as a uv tool; nothing to remove."
  fi
  say ""
  say "Kept, untouched:"
  say "  $DATA_HOME            machine-wide state (spend ledger, web canvas, shared credentials in .env)"
  say "  .unbidden/ in every repository you ran unbidden in (mandate, store, records)"
  say "Delete them yourself if you want them gone; uv and its Python stay for other tools."
  exit 0
fi

# --- which version, from where -------------------------------------------------------------------------------

if [ -z "$VERSION" ]; then
  if [ -n "$BASE" ]; then
    die "UNBIDDEN_INSTALL_BASE is set; say which version to take from it: --version X.Y.Z" 2
  fi
  say "Looking up the latest release of $REPO..."
  api="https://api.github.com/repos/$REPO/releases/latest"
  body="$(curl -sS --proto '=https' --tlsv1.2 -H 'Accept: application/vnd.github+json' "$api" 2>/dev/null || true)"
  tag="$(printf '%s' "$body" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
  if [ -z "$tag" ]; then
    die "no published release found at https://github.com/$REPO/releases (nothing is published yet, or GitHub
  could not be reached). Pass --version X.Y.Z, and UNBIDDEN_INSTALL_BASE when the files are not on GitHub." 5
  fi
  VERSION="${tag#v}"
fi
case "$VERSION" in
  v*) VERSION="${VERSION#v}" ;;
esac
printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+([.+-][A-Za-z0-9.+-]*)?$' || die "not a version: $VERSION" 2

if [ -z "$BASE" ]; then
  BASE="https://github.com/$REPO/releases/download/v$VERSION"
fi
BASE="${BASE%/}"
case "$BASE" in
  https://*) ;;
  http://127.0.0.1*|http://localhost*|http://\[::1\]*) ;;
  http://*) die "refusing a plain http:// base that is not loopback: $BASE" 2 ;;
  *) die "UNBIDDEN_INSTALL_BASE must be an http(s) URL: $BASE" 2 ;;
esac

WHEEL="unbidden_ai-$VERSION-py3-none-any.whl"

# --- download and verify ---------------------------------------------------------------------------------------

TMP="$(mktemp -d "${TMPDIR:-/tmp}/unbidden-install.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT INT TERM

fetch() {
  # $1 url, $2 destination
  curl -fsSL --proto '=https,http' --tlsv1.2 --retry 2 -o "$2" "$1" || die "could not download $1" 6
}

say "Downloading $WHEEL from $BASE"
fetch "$BASE/$WHEEL" "$TMP/$WHEEL"
fetch "$BASE/SHA256SUMS" "$TMP/SHA256SUMS"

expected="$(awk -v w="$WHEEL" '{ f = $2; sub(/^\*/, "", f); if (f == w) { print tolower($1); exit } }' "$TMP/SHA256SUMS")"
[ -n "$expected" ] || die "SHA256SUMS at $BASE does not list $WHEEL; refusing to install an unverified file" 7
actual="$(cd "$TMP" && $SHA256 "$WHEEL" | awk '{ print tolower($1) }')"
if [ "$expected" != "$actual" ]; then
  die "checksum mismatch for $WHEEL
  expected $expected
  got      $actual
  Nothing was installed. The download is corrupt or was tampered with; try again or report it." 8
fi
say "sha256 verified: $actual"

# --- install ---------------------------------------------------------------------------------------------------

say "Installing $NAME $VERSION with Python 3.12 (uv downloads an interpreter if none is managed, ~30 MB, once)"
"$UV" tool install --python 3.12 --reinstall "$TMP/$WHEEL" >&2

INSTALLED="$("$BIN_DIR/unbidden" --version 2>/dev/null | sed 's/^unbidden //' || true)"
[ "$INSTALLED" = "$VERSION" ] || die "installed, but $BIN_DIR/unbidden reports '$INSTALLED' instead of $VERSION" 9

# --- PATH -------------------------------------------------------------------------------------------------------

on_path=0
case ":$PATH:" in *":$BIN_DIR:"*) on_path=1 ;; esac
if [ "$on_path" = 0 ]; then
  say ""
  say "$BIN_DIR is not on your PATH."
  if [ "$YES" = 0 ] && [ "$TTY" = 1 ] && ask "Let uv add it to your shell's startup file (uv tool update-shell)?"; then
    "$UV" tool update-shell >&2 || true
    say "Open a new terminal, or run the line below in this one."
  fi
  say "Add it yourself with one of:"
  say "  zsh:   echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
  say "  bash:  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
  say "  fish:  fish_add_path $BIN_DIR"
fi

# --- done --------------------------------------------------------------------------------------------------------

say ""
say "unbidden-ai $VERSION installed: $BIN_DIR/unbidden"
TOOL_PY="$("$UV" tool dir)/$NAME/bin/python"
say "  platform: $PLATFORM; python: $("$TOOL_PY" --version 2>/dev/null || echo 'in the tool environment')"
say "  next:     cd your-repo && unbidden"
say "  update:   unbidden update        rollback: sh install.sh --version <previous>        remove: sh install.sh --uninstall"
