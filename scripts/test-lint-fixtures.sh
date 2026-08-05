#!/usr/bin/env bash
# Assert every caller-lint fixture's verdict by filename convention:
#   clean-*.yml  -> lint must PASS (exit 0)
#   bad-*.yml    -> lint must FAIL (exit 1)
# Gates the caller-structure rules of the v0.6 lint (gate-ref-pin, explicit
# four-secret mapping, unknown/removed inputs): a rule that silently stops
# firing flips its bad-* fixture to exit 0 and this check goes red. The
# compose/Dockerfile/chart convention rules are unit-tested in
# tests/lib/test_lint_rules.py and exercised end to end at the plan-job
# integration gate. Run locally or in CI.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURES="$ROOT/tests/fixtures/callers"

fail=0
count=0
for f in "$FIXTURES"/*.yml; do
  [ -e "$f" ] || continue
  count=$((count + 1))
  base="$(basename "$f")"
  out="$(uv run --quiet "$ROOT/scripts/lib/lint_caller.py" "$f" 2>/dev/null)"
  rc=$?
  case "$base" in
    clean-*)
      if [ "$rc" -eq 0 ]; then
        echo "PASS $base (clean)"
      else
        echo "FAIL $base: expected exit 0, got $rc"; echo "$out"; fail=1
      fi
      ;;
    bad-*)
      if [ "$rc" -eq 1 ]; then
        echo "PASS $base (rejected)"
      else
        echo "FAIL $base: expected exit 1, got $rc"; fail=1
      fi
      ;;
    *)
      echo "FAIL $base: fixture name must start with 'clean-' or 'bad-'"; fail=1
      ;;
  esac
done

if [ "$count" -eq 0 ]; then
  echo "FAIL: no fixtures found under $FIXTURES"
  exit 1
fi
echo "checked $count fixture(s)"
[ "$fail" -eq 0 ] || { echo "== lint-fixture check FAILED =="; exit 1; }
echo "== lint-fixture check OK =="
