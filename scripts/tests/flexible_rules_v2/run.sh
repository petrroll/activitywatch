#!/usr/bin/env bash
set -euo pipefail

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO="$(CDPATH= cd -- "$HERE/../../.." && pwd)"
PYTHON="${PYTHON:-python3}"

run_rust=true
for argument in "$@"; do
  case "$argument" in
    --python-only|--skip-rust) run_rust=false ;;
  esac
done

cd "$REPO"
"$PYTHON" "$HERE/runner.py" "$@"

# Keep document-boundary and settings protocol behavior paired with the semantic
# matrix. These focused suites exercise forward/malformed native reads, aggregate
# selected-set budgets, CAS/recovery revisions, and legacy-write status codes.
"$PYTHON" -m pytest -p no:cacheprovider -o addopts="" \
  aw-client/tests/test_rules_v2.py aw-server/tests/test_rules_settings.py -q
if "$run_rust"; then
  (
    cd "$REPO/aw-server-rust"
    "${CARGO:-cargo}" test -p aw-client-rust rules_v2 --lib --quiet
    "${CARGO:-cargo}" test -p aw-server --test api --quiet
  )
fi
