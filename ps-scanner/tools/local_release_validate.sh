#!/usr/bin/env bash
set -euo pipefail

VERSION="6.8.2"
EXPECTED_BRANCH="release/ps-scanner-v6.8.2-performance"
LINUX_PLATFORM="${LINUX_PLATFORM:-linux/amd64}"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$PS_DIR" rev-parse --show-toplevel)"
BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
DIST_DIR="$REPO_ROOT/dist"
TMP_ROOT="$(mktemp -d "$REPO_ROOT/.psscanner-v682.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

echo "PS Scanner Quant v$VERSION local release validation"
echo "Repository: $REPO_ROOT"
echo "Branch:     $BRANCH"
echo "HEAD:       $HEAD_SHA"
echo

if [[ "$BRANCH" != "$EXPECTED_BRANCH" && "${ALLOW_ANY_REF:-0}" != "1" ]]; then
  fail "expected branch $EXPECTED_BRANCH (set ALLOW_ANY_REF=1 only for deliberate ref validation)"
fi

if ! git -C "$REPO_ROOT" cat-file -e "$HEAD_SHA:ps-scanner/psscanner_quant/constants.py"; then
  fail "HEAD does not contain PS Scanner source"
fi

ARCHIVE_ROOT="$TMP_ROOT/archive"
mkdir -p "$ARCHIVE_ROOT"
git -C "$REPO_ROOT" archive --format=tar "$HEAD_SHA" ps-scanner | tar -xf - -C "$ARCHIVE_ROOT"
SRC="$ARCHIVE_ROOT/ps-scanner"

ACTUAL_VERSION="$(grep -E '^VERSION = ' "$SRC/psscanner_quant/constants.py" | sed -E 's/.*"([^"]+)".*/\1/' | head -1)"
[[ "$ACTUAL_VERSION" == "$VERSION" ]] || fail "source VERSION is $ACTUAL_VERSION, expected $VERSION"

run_native() {
  echo "== Native macOS regression =="
  command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "$PYTHON_BIN is required (Python 3.12)"
  command -v node >/dev/null 2>&1 || fail "node is required for UI JavaScript syntax validation"
  command -v zsh >/dev/null 2>&1 || fail "zsh is required for installer/run-script syntax validation"

  NATIVE_ROOT="$TMP_ROOT/native"
  cp -R "$SRC" "$NATIVE_ROOT"
  "$PYTHON_BIN" -m venv "$TMP_ROOT/native-venv"
  # shellcheck disable=SC1091
  source "$TMP_ROOT/native-venv/bin/activate"
  python -m pip install --upgrade pip
  pip install -r "$NATIVE_ROOT/requirements.txt"

  (
    cd "$NATIVE_ROOT"
    python -m compileall -q psscanner_quant tests tools
    python -c "from psscanner_quant.db import init_db; init_db()"
    python -m unittest discover -s tests -v

    python - <<'PY'
from pathlib import Path
html=Path("static/index.html").read_text()
js=html.rsplit("<script>",1)[1].split("</script>",1)[0]
Path("/tmp/ps-scanner-ui-v682.js").write_text(js)
PY
    node --check /tmp/ps-scanner-ui-v682.js
    zsh -n install.sh
    zsh -n run.sh
  )
  deactivate
  echo "PASS: native macOS regression"
  echo
}

run_linux() {
  echo "== Linux regression in local container =="
  local engine=""
  if command -v docker >/dev/null 2>&1; then
    engine="docker"
  elif command -v podman >/dev/null 2>&1; then
    engine="podman"
  else
    fail "Docker or Podman is required for the Linux parity gate"
  fi

  "$engine" run --rm --platform "$LINUX_PLATFORM" \
    -v "$SRC:/src:ro" \
    python:3.12-bookworm \
    bash -lc '
      set -euo pipefail
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq
      apt-get install -y -qq nodejs zsh >/dev/null
      cp -R /src /tmp/ps-scanner
      cd /tmp/ps-scanner
      python -m venv /tmp/ps-venv
      . /tmp/ps-venv/bin/activate
      python -m pip install --upgrade pip >/dev/null
      pip install -r requirements.txt >/dev/null
      python -m compileall -q psscanner_quant tests tools
      python -c "from psscanner_quant.db import init_db; init_db()"
      python -m unittest discover -s tests -v
      python - <<'"'"'PY'"'"'
from pathlib import Path
html=Path("static/index.html").read_text()
js=html.rsplit("<script>",1)[1].split("</script>",1)[0]
Path("/tmp/ps-scanner-ui-v682.js").write_text(js)
PY
      node --check /tmp/ps-scanner-ui-v682.js
      zsh -n install.sh
      zsh -n run.sh
    '

  echo "PASS: Linux container regression ($LINUX_PLATFORM)"
  echo
}

build_package() {
  echo "== Build tracked-source release ZIP =="
  mkdir -p "$DIST_DIR"
  rm -rf "$TMP_ROOT/PS_Scanner_Quant_v$VERSION"
  cp -R "$SRC" "$TMP_ROOT/PS_Scanner_Quant_v$VERSION"
  find "$TMP_ROOT/PS_Scanner_Quant_v$VERSION" -name '__pycache__' -type d -prune -exec rm -rf {} +
  find "$TMP_ROOT/PS_Scanner_Quant_v$VERSION" -name '*.pyc' -delete

  ZIP_PATH="$DIST_DIR/PS_Scanner_Quant_v$VERSION.zip"
  rm -f "$ZIP_PATH"
  (
    cd "$TMP_ROOT"
    zip -qr "$ZIP_PATH" "PS_Scanner_Quant_v$VERSION"
  )
  unzip -t "$ZIP_PATH" >/dev/null

  if command -v shasum >/dev/null 2>&1; then
    SHA256="$(shasum -a 256 "$ZIP_PATH" | awk '{print $1}')"
  elif command -v sha256sum >/dev/null 2>&1; then
    SHA256="$(sha256sum "$ZIP_PATH" | awk '{print $1}')"
  else
    fail "no SHA-256 utility found"
  fi

  echo "PASS: ZIP integrity"
  echo "Artifact: $ZIP_PATH"
  echo "SHA-256:  $SHA256"
  echo "Source:   $HEAD_SHA"
  echo
  echo "NEXT: install this ZIP on the real Mac, then run:"
  echo "  cd ~/Applications/PS_Scanner_Final"
  echo "  python3 tools/post_install_validate.py"
}

run_native
run_linux
build_package
