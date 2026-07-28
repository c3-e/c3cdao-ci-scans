#!/usr/bin/env bash
# Assert setup-ruleset.sh --diff behavior against a fake `gh` shim:
#   in-sync live ruleset      -> exit 0
#   enforcement drift         -> exit 3, diff mentions "enforcement"
#   missing live ruleset      -> non-zero with a clear error
# Only `gh` is faked; config loading uses the real uv/python path.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat >"$TMP/config.yaml" <<'EOF'
target:
  owner: acme
  repo: monorepo
  default_branch: main
ci_scans:
  owner: acme
  repo: c3cdao-ci-scans
  ref: main
ruleset:
  profile: unified-gate
  name: security-scan-gates
  ruleset_id: 42
EOF

# Live ruleset as GitHub returns it (extra fields must be normalized away).
cat >"$TMP/ruleset-42.json" <<'EOF'
{
  "id": 42,
  "name": "security-scan-gates",
  "target": "branch",
  "source_type": "Repository",
  "source": "acme/monorepo",
  "enforcement": "disabled",
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "bypass_actors": [
    { "actor_type": "RepositoryRole", "actor_id": 5, "bypass_mode": "always" },
    { "actor_type": "OrganizationAdmin", "actor_id": null, "bypass_mode": "always" },
    { "actor_type": "RepositoryRole", "actor_id": 2, "bypass_mode": "always" }
  ],
  "rules": [{
    "type": "required_status_checks",
    "parameters": {
      "strict_required_status_checks_policy": true,
      "do_not_enforce_on_create": false,
      "required_status_checks": [
        { "context": "security-scan / Security Gate", "integration_id": 15368 }
      ]
    }
  }],
  "_links": { "html": { "href": "https://github.com/acme/monorepo/rules/42" } }
}
EOF

mkdir -p "$TMP/bin"
cat >"$TMP/bin/gh" <<'EOF'
#!/usr/bin/env bash
# fake gh: only supports `gh api repos/<owner>/<repo>/rulesets[/<id>]`
if [ "${FAKE_GH_MODE:-}" = "missing" ]; then
  echo "gh: Not Found (HTTP 404)" >&2
  exit 1
fi
case "$2" in
  repos/*/rulesets/42) cat "$FAKE_GH_DIR/ruleset-42.json" ;;
  *) echo "fake gh: unexpected args: $*" >&2; exit 1 ;;
esac
EOF
chmod +x "$TMP/bin/gh"
export PATH="$TMP/bin:$PATH"
export FAKE_GH_DIR="$TMP"

fail=0

# (a) in sync: live is disabled, no --enable
out="$("$ROOT/scripts/setup-ruleset.sh" --config "$TMP/config.yaml" --diff 2>&1)"
rc=$?
if [ "$rc" -eq 0 ] && grep -q "in sync" <<<"$out"; then
  echo "PASS in-sync (exit 0)"
else
  echo "FAIL in-sync: expected exit 0 + 'in sync', got $rc"; echo "$out"; fail=1
fi

# (b) enforcement drift: --enable expects active, live is disabled
out="$("$ROOT/scripts/setup-ruleset.sh" --config "$TMP/config.yaml" --diff --enable 2>&1)"
rc=$?
if [ "$rc" -eq 3 ] && grep -q "enforcement" <<<"$out"; then
  echo "PASS enforcement drift (exit 3, diff mentions enforcement)"
else
  echo "FAIL enforcement drift: expected exit 3 + 'enforcement', got $rc"; echo "$out"; fail=1
fi

# (c) missing live ruleset -> clear error, non-zero
out="$(FAKE_GH_MODE=missing "$ROOT/scripts/setup-ruleset.sh" --config "$TMP/config.yaml" --diff 2>&1)"
rc=$?
if [ "$rc" -ne 0 ] && [ "$rc" -ne 3 ] && grep -q "no live ruleset" <<<"$out"; then
  echo "PASS missing ruleset (exit $rc, clear error)"
else
  echo "FAIL missing ruleset: expected non-zero + 'no live ruleset', got $rc"; echo "$out"; fail=1
fi

[ "$fail" -eq 0 ] || { echo "== setup-ruleset --diff check FAILED =="; exit 1; }
echo "== setup-ruleset --diff check OK =="
