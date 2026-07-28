#!/usr/bin/env bash
# Step 2b–3: create or update a dedicated security-scan ruleset (starts disabled).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$ROOT/scripts/lib/common.sh"

usage() {
  cat <<'EOF'
usage: setup-ruleset.sh --config <yaml> [--enable] [--dry-run] [--diff]

Creates/updates ruleset requiring the security-scan / Security Gate check.
Default enforcement: disabled (safe rollout).

--diff: read-only drift check — fetch the live ruleset from GitHub and diff
it against what this config would produce. Exit 0 when in sync, 3 on drift
(prints a unified diff), dies if no live ruleset exists. The expected
enforcement derives from --enable, so pass --enable with --diff when the
ruleset is expected to be active.
EOF
}

CONFIG=""
ENABLE=0
DRY_RUN=0
DIFF=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --enable) ENABLE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --diff) DIFF=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown arg: $1" ;;
  esac
done
[[ -n "$CONFIG" ]] || { usage; exit 1; }

require_cmd gh
require_cmd jq

json="$(load_config_json "$CONFIG")"
owner="$(json_get "$json" '.target.owner')"
repo="$(json_get "$json" '.target.repo')"
ruleset_name="$(json_get "$json" '.ruleset.name')"
ruleset_id="$(json_get "$json" '.ruleset.ruleset_id')"
integration_id="$(json_get "$json" '.ruleset.github_actions_integration_id')"
target_branch="$(json_get "$json" '.ruleset.target_branch')"
[[ -z "$integration_id" ]] && integration_id=15368
[[ -z "$ruleset_name" ]] && ruleset_name="security-scan-gates"

# Default: apply to the repo's actual configured default branch. Set
# ruleset.target_branch in config to pin a specific branch instead (e.g. a
# scratch integration branch for a pilot on a shared repo) — the ruleset then
# targets that literal ref, independent of what Settings > Branches says.
ref_include="[\"~DEFAULT_BRANCH\"]"
[[ -n "$target_branch" ]] && ref_include="[\"refs/heads/${target_branch}\"]"

enforcement="disabled"
[[ "$ENABLE" -eq 1 ]] && enforcement="active"

# The one supported profile (unified-gate) always resolved to this single
# check context; the profile YAML indirection was removed as dead weight.
checks_json="$(jq -n '[{context: "security-scan / Security Gate", integration_id: '"$integration_id"'}]')"

payload="$(jq -n \
  --arg name "$ruleset_name" \
  --arg enforcement "$enforcement" \
  --argjson checks "$checks_json" \
  --argjson ref_include "$ref_include" \
  '{
    name: $name,
    target: "branch",
    enforcement: $enforcement,
    conditions: { ref_name: { include: $ref_include, exclude: [] } },
    bypass_actors: [
      { actor_type: "OrganizationAdmin", actor_id: null, bypass_mode: "always" },
      { actor_type: "RepositoryRole", actor_id: 2, bypass_mode: "always" },
      { actor_type: "RepositoryRole", actor_id: 5, bypass_mode: "always" }
    ],
    rules: [{
      type: "required_status_checks",
      parameters: {
        strict_required_status_checks_policy: true,
        do_not_enforce_on_create: false,
        required_status_checks: $checks
      }
    }]
  }')"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "$payload" | jq .
  exit 0
fi

if [[ "$DIFF" -eq 1 ]]; then
  # Read-only: fetch the live ruleset and compare a normalized subset.
  if [[ -n "$ruleset_id" && "$ruleset_id" != "null" ]]; then
    live="$(gh api "repos/${owner}/${repo}/rulesets/${ruleset_id}")" \
      || die "no live ruleset id=$ruleset_id on ${owner}/${repo}"
  else
    live_id="$(gh api "repos/${owner}/${repo}/rulesets" \
      --jq "[.[] | select(.name == \"$ruleset_name\")][0].id // empty")" \
      || die "failed to list rulesets on ${owner}/${repo}"
    [[ -n "$live_id" ]] || die "no live ruleset named '$ruleset_name' on ${owner}/${repo}"
    live="$(gh api "repos/${owner}/${repo}/rulesets/${live_id}")" \
      || die "no live ruleset id=$live_id on ${owner}/${repo}"
  fi
  normalize='{
    name, target, enforcement,
    conditions: { ref_name: .conditions.ref_name },
    bypass_actors: ((.bypass_actors // []) | sort_by(.actor_type, .actor_id, .bypass_mode)),
    rules: [.rules[] | { type }
      + (if .type == "required_status_checks"
         then { required_status_checks:
                  [.parameters.required_status_checks[] | { context, integration_id }] }
         else {} end)]
  }'
  if diff -u \
      --label "expected (config: $CONFIG, enforcement=$enforcement)" \
      --label "live (github: ${owner}/${repo})" \
      <(jq "$normalize" <<<"$payload") <(jq "$normalize" <<<"$live"); then
    echo "in sync: live ruleset matches config"
    exit 0
  else
    echo "drift: live ruleset differs from config" >&2
    exit 3
  fi
fi

if [[ -n "$ruleset_id" && "$ruleset_id" != "null" ]]; then
  echo "Updating ruleset id=$ruleset_id ($ruleset_name) enforcement=$enforcement"
  gh api -X PUT "repos/${owner}/${repo}/rulesets/${ruleset_id}" --input - <<<"$payload" \
    --jq '{id, name, enforcement, url: ._links.html.href}'
else
  echo "Creating ruleset $ruleset_name enforcement=$enforcement"
  gh api -X POST "repos/${owner}/${repo}/rulesets" --input - <<<"$payload" \
    --jq '{id, name, enforcement, url: ._links.html.href}'
  echo "Tip: persist returned id in config as ruleset.ruleset_id"
fi
