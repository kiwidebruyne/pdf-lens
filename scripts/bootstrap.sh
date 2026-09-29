#!/bin/sh
set -eu

usage() { echo "Usage: bootstrap.sh [--source PATH] [--codex-home PATH]"; }
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
codex_dir=${CODEX_HOME:-"$HOME/.codex"}
action=install
while [ "$#" -gt 0 ]; do
  case "$1" in
    --source) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; source_dir=$2; shift 2 ;;
    --codex-home) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; codex_dir=$2; shift 2 ;;
    --update) action=update; shift ;;
    --state) action=state; shift ;;
    --uninstall) action=uninstall; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

source_dir=$(CDPATH= cd -- "$source_dir" && pwd)
tool_dir="$codex_dir/tool-envs/pdf-lens"
uv_dir="$tool_dir/uv"
export UV_INSTALL_DIR="$uv_dir"
export UV_NO_MODIFY_PATH=1
export UV_PYTHON_INSTALL_DIR="$tool_dir/python"
export UV_CACHE_DIR="$tool_dir/cache"
mkdir -p "$tool_dir"
if [ ! -x "$uv_dir/uv" ]; then
  echo "Installing private uv under $uv_dir"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
"$uv_dir/uv" python install --no-bin 3.13
python_path=$("$uv_dir/uv" python find --managed-python 3.13)
if [ "$action" = install ]; then
  "$python_path" "$source_dir/scripts/manage_install.py" --codex-home "$codex_dir" install --source "$source_dir"
else
  installed="$codex_dir/skills/pdf-lens/scripts/manage_install.py"
  "$python_path" "$installed" --codex-home "$codex_dir" "$action"
fi
