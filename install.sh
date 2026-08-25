#!/usr/bin/env bash
# Put ccex on your PATH by linking to this checkout, so `git pull` updates it.
set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
bindir=${1:-$HOME/.local/bin}

mkdir -p "$bindir"
ln -sfn "$here/bin/ccex" "$bindir/ccex"
printf 'ccex: linked %s -> %s\n' "$bindir/ccex" "$here/bin/ccex"

case ":$PATH:" in
  *":$bindir:"*) ;;
  *) printf 'ccex: %s is not on your PATH\n' "$bindir" >&2 ;;
esac
command -v python3 >/dev/null || printf 'ccex: needs python3\n' >&2
command -v claude   >/dev/null || printf 'ccex: needs the claude CLI\n' >&2
