#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
node_version="22.19.0"
node_dir="$project_dir/.tools/node-v$node_version-linux-x64"
node_archive="/tmp/node-v$node_version-linux-x64.tar.xz"
pi_dir="$project_dir/.tools/pi"

if [[ ! -x "$node_dir/bin/node" ]]; then
  mkdir -p "$project_dir/.tools"
  curl -fsSL "https://nodejs.org/dist/v$node_version/node-v$node_version-linux-x64.tar.xz" -o "$node_archive"
  tar -xJf "$node_archive" -C "$project_dir/.tools"
fi

if [[ ! -x "$pi_dir/node_modules/.bin/pi" ]]; then
  PATH="$node_dir/bin:$PATH" npm install --prefix "$pi_dir" --ignore-scripts \
    @earendil-works/pi-coding-agent@0.85.1
fi

PATH="$node_dir/bin:$PATH" "$pi_dir/node_modules/.bin/pi" --version
