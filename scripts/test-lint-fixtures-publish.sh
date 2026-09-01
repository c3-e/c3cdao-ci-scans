#!/usr/bin/env bash
# Assert every publish-staging-chart caller-lint fixture's verdict by
# filename convention:
#   clean-*.yml  -> lint must PASS (exit 0)
#   bad-*.yml    -> lint must FAIL (exit 1)
# Mirrors scripts/test-lint-fixtures.sh's role for lint_caller.py (the
# security-gate caller lint), but for lint_caller_publish.py. Fixtures
# live in a separate directory (tests/fixtures/callers_publish/, not
# tests/fixtures/callers/) since lint_caller.py and lint_caller_publish.py
# look for different jobs.uses: basenames — a publish-staging-chart
# fixture run through lint_caller.py (or vice versa) would always report
# unreadable-caller regardless of the fixture's actual intent. Run
# locally or in CI.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURES="$ROOT/tests/fixtures/callers_publish"

fail=0
count=0
for f in "$FIXTURES"/*.yml; do
  [ -e "$f" ] || continue
  count=$((count + 1))
  base="$(basename "$f")"
  out="$(uv run --quiet "$ROOT/scripts/lib/lint_caller_publish.py" "$f" 2>/dev/null)"
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
[ "$fail" -eq 0 ] || { echo "== publish-lint-fixture check FAILED =="; exit 1; }
echo "== publish-lint-fixture check OK =="
