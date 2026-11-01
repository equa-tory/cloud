#!/bin/sh
set -eu
cloud_source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p "$HOME/.local/bin"
install -m 755 "$cloud_source_dir/cloud" "$HOME/.local/bin/cloud"
printf '%s\n' 'Installed ~/.local/bin/cloud. Run cloud to open the manager.' 'Ensure ~/.local/bin is on your PATH.'
