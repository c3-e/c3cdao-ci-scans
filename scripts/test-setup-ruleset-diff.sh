#!/usr/bin/env bash
# Assert setup-ruleset.sh --diff behavior against a fake `gh` shim:
#   in-sync live ruleset      -> exit 0
#   enforcement drift         -> exit 3, diff mentions "enforcement"
#   missing live ruleset      -> non-zero with a clear error
#   evaluate is a standing target state, not just a step towards --enable:
#     in-sync evaluate          -> exit 0
#     evaluate vs active drift  -> exit 3, diff mentions "enforcement"
#     --enable and --evaluate together is a usage error
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

cat >"$TMP/config-evaluate.yaml" <<'EOF'
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
  ruleset_id: 43
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

# A repo deliberately left in evaluate — the loud-but-non-blocking standing
# state (checks run and report real pass/fail; nothing is required to merge).
cat >"$TMP/ruleset-43.json" <<'EOF'
{
  "id": 43,
  "name": "security-scan-gates",
  "target": "branch",
  "source_type": "Repository",
  "source": "acme/monorepo",
  "enforcement": "evaluate",
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
  "_links": { "html": { "href": "https://github.com/acme/monorepo/rules/43" } }
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
  repos/*/rulesets/43) cat "$FAKE_GH_DIR/ruleset-43.json" ;;
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

# (d) evaluate is an in-sync standing state on its own — not just a step
# towards --enable. Live is evaluate, --evaluate expects evaluate.
out="$("$ROOT/scripts/setup-ruleset.sh" --config "$TMP/config-evaluate.yaml" --diff --evaluate 2>&1)"
rc=$?
if [ "$rc" -eq 0 ] && grep -q "in sync" <<<"$out"; then
  echo "PASS evaluate in-sync (exit 0)"
else
  echo "FAIL evaluate in-sync: expected exit 0 + 'in sync', got $rc"; echo "$out"; fail=1
fi

# (e) evaluate vs active drift: live is evaluate, --enable expects active
out="$("$ROOT/scripts/setup-ruleset.sh" --config "$TMP/config-evaluate.yaml" --diff --enable 2>&1)"
rc=$?
if [ "$rc" -eq 3 ] && grep -q "enforcement" <<<"$out"; then
  echo "PASS evaluate-vs-active drift (exit 3, diff mentions enforcement)"
else
  echo "FAIL evaluate-vs-active drift: expected exit 3 + 'enforcement', got $rc"; echo "$out"; fail=1
fi

# (f) --enable and --evaluate together is a usage error, not silently
# resolved to one or the other.
out="$("$ROOT/scripts/setup-ruleset.sh" --config "$TMP/config.yaml" --enable --evaluate 2>&1)"
rc=$?
if [ "$rc" -ne 0 ] && grep -qi "mutually exclusive" <<<"$out"; then
  echo "PASS --enable/--evaluate conflict rejected"
else
  echo "FAIL --enable/--evaluate conflict: expected non-zero + 'mutually exclusive', got $rc"; echo "$out"; fail=1
fi

[ "$fail" -eq 0 ] || { echo "== setup-ruleset --diff check FAILED =="; exit 1; }
echo "== setup-ruleset --diff check OK =="
