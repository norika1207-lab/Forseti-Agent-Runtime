#!/bin/sh
# Event-driven host adapter entrypoint.
#
# This intentionally does not poll, click a foreground window, or type a
# generic "continue" string. Feed it persisted AX observations as JSONL; the
# adapter only emits an original, ledger-authorized next-action packet after
# the exact target has been observed ACTIVE -> IDLE.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

# Legacy controller flags implied a polling AX loop.  This adapter accepts
# durable JSONL observations only; accepting those flags would make the
# unsafe mode look supported even though no foreground delivery is allowed.
for arg in "$@"; do
  case "$arg" in
    --interval|--idle|--once|--dry-run)
      printf '%s\n' "refusing legacy polling controller option: $arg" >&2
      exit 64
      ;;
  esac
done

exec python3 "$ROOT/apps/forseti-cli/desktop_adapter.py" "$@"
