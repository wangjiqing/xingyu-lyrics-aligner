#!/usr/bin/env bash
set -euo pipefail

FORCE=0
LOCALE=""
while [[ $# -gt 0 ]]; do
  arg="$1"
  case "$arg" in
    --force)
      FORCE=1
      shift
      ;;
    --locale)
      if [[ $# -lt 2 ]]; then
        echo "--locale requires en-US or zh-CN." >&2
        exit 2
      fi
      LOCALE="$2"
      shift 2
      ;;
    -h|--help)
      cat <<'USAGE'
Install xingyu-align from a local source checkout on macOS.

Usage:
  ./scripts/install-macos.sh [--force] [--locale en-US|zh-CN]

This script does not install Homebrew, does not modify shell config, and does not
download alignment models. Run `xingyu-align models pull --language zh` after install.
USAGE
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ -n "$LOCALE" && "$LOCALE" != "en-US" && "$LOCALE" != "zh-CN" ]]; then
  echo "Unsupported locale: $LOCALE. Supported: en-US, zh-CN." >&2
  exit 2
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer only supports macOS." >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
LAUNCHER_DIR="$HOME/.local/bin"
LAUNCHER="$LAUNCHER_DIR/xingyu-align"

if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="python3.11"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "Python 3.11+ is required. Install Python first, then rerun this script." >&2
  exit 2
fi

PYTHON_VERSION="$("$PYTHON_BIN" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
case "$PYTHON_VERSION" in
  3.11|3.12|3.13)
    ;;
  *)
    echo "Python $PYTHON_VERSION is not supported. Use Python >=3.11,<3.14." >&2
    exit 2
    ;;
esac

if ! command -v ffmpeg >/dev/null 2>&1; then
  cat >&2 <<'FFMPEG'
ffmpeg was not found on PATH.

Install it with:
  brew install ffmpeg

This installer will not install Homebrew or ffmpeg automatically.
FFMPEG
  exit 2
fi

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -e "$REPO_DIR[alignment]"

if [[ ! -x "$VENV_DIR/bin/xingyu-align" ]]; then
  echo "Install failed: $VENV_DIR/bin/xingyu-align is not executable." >&2
  exit 2
fi

if [[ -z "$LOCALE" && -t 0 ]]; then
  cat <<'EOF'

Choose default CLI language:
  1) English (en-US)
  2) 简体中文 (zh-CN)
Press Enter for English.
EOF
  read -r -p "Selection [1/2]: " selection
  case "$selection" in
    2)
      LOCALE="zh-CN"
      ;;
    *)
      LOCALE="en-US"
      ;;
  esac
fi

if [[ -n "$LOCALE" ]]; then
  "$VENV_DIR/bin/xingyu-align" config set-locale "$LOCALE"
fi

mkdir -p "$LAUNCHER_DIR"
if [[ -e "$LAUNCHER" && "$FORCE" != "1" ]]; then
  cat >&2 <<EOF
Launcher already exists:
  $LAUNCHER

Rerun with --force to replace it.
EOF
  exit 2
fi

cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec "$VENV_DIR/bin/xingyu-align" "\$@"
EOF
chmod +x "$LAUNCHER"

if [[ ":$PATH:" != *":$LAUNCHER_DIR:"* ]]; then
  cat <<EOF

$LAUNCHER_DIR is not on PATH.

Add it to zsh with:
  echo 'export PATH="\$HOME/.local/bin:\$PATH"' >> ~/.zshrc
  source ~/.zshrc

If you use bash, add it with:
  echo 'export PATH="\$HOME/.local/bin:\$PATH"' >> ~/.bash_profile
  source ~/.bash_profile
EOF
fi

cat <<EOF

xingyu-align installed.

Next steps:
  xingyu-align doctor
  xingyu-align models pull --language zh
  xingyu-align align --help
EOF
