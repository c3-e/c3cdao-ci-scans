# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Canonical, script-generated fleet-status table (Issue K).

Replaces hand-maintained prose (a memory file, a Confluence page edited by
hand) with a table derived live from the GitHub API every time it's run —
one row per (pilot, branch) pair listed in configs/fleet-pilots.yaml. Columns:

  - gate pin: security-gate.yml's `uses:` ref, resolved to its actual commit
    SHA (a ref/tag can move; the SHA is what actually ran)
  - hook mechanism: whether the branch's Helm chart declares a
    `helm.sh/hook: test` resource anywhere under helm/**/templates/**
  - publish contract: whether publish-staging-chart-caller.yml exists, and
    whether it's on the current `compose_file`-derived contract or the
    retired hand-typed `images:` shape
  - VEX: whether `.openvex/templates/main.openvex.json` exists on the branch
  - ruleset: security-scan-gates enforcement (only meaningful on a repo's
    default branch — rulesets scope to ~DEFAULT_BRANCH)
  - last real run: the most recent completed Security Scan run's date and
    conclusion on that branch, not inferred from a green checkmark alone

Requires `gh` authenticated in the environment; makes no writes anywhere.
Usage: uv run scripts/fleet_status.py [--config configs/fleet-pilots.yaml] [--format md|json]
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _gh_json(*args: str) -> Any:
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _gh_content(owner: str, repo: str, path: str, ref: str) -> str | None:
    # NOTE: `-f ref=<ref>` silently switches gh api to POST (404s every
    # time) unless `-X GET` is explicit; an inline query string avoids the
    # footgun entirely.
    data = _gh_json("api", f"repos/{owner}/{repo}/contents/{path}?ref={ref}")
    if not data or "content" not in data:
        return None
    return base64.b64decode(data["content"]).decode("utf-8", errors="replace")


def _gh_text(*args: str) -> str | None:
    # `--jq` renders a scalar as plain text, not JSON — json.loads on that
    # (e.g. a bare hex SHA) throws, so this path needs its own helper
    # rather than reusing _gh_json.
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _resolve_ref_sha(owner: str, repo: str, ref: str) -> str | None:
    # `uses: ...@<ref>` can be a branch, tag, or already a full 40-hex SHA.
    return _gh_text("api", f"repos/{owner}/{repo}/commits/{ref}", "--jq", ".sha")


def _extract_pin(content: str) -> str | None:
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("uses:") and "c3cdao-ci-scans" in line:
            after_at = line.split("@", 1)
            if len(after_at) == 2:
                return after_at[1].split()[0].split("#")[0].strip()
    return None


def _tree_paths(owner: str, repo: str, branch: str) -> list[str]:
    data = _gh_json(
        "api", f"repos/{owner}/{repo}/git/trees/{branch}?recursive=true"
    )
    if not data or "tree" not in data:
        return []
    return [entry["path"] for entry in data["tree"] if entry.get("type") == "blob"]


def _grep_hook_annotation(owner: str, repo: str, branch: str, paths: list[str]) -> bool:
    # Match on the Helm convention (a `templates/` directory somewhere in
    # the path), not a `helm/`-prefixed top-level dir — some pilots nest
    # their chart elsewhere (e.g. ppubs: apps/patent-search/helm/...).
    chart_yaml_paths = [
        p for p in paths if "/templates/" in p and p.endswith((".yaml", ".yml"))
    ]
    for path in chart_yaml_paths:
        content = _gh_content(owner, repo, path, branch)
        if content and "helm.sh/hook" in content and "test" in content:
            # Cheap pre-filter; a false positive here just costs one extra
            # look — acceptable for a status report, not a lint gate.
            if "helm.sh/hook:" in content or '"helm.sh/hook"' in content:
                return True
    return False


def _ruleset_enforcement(owner: str, repo: str, name: str = "security-scan-gates") -> str:
    rulesets = _gh_json("api", f"repos/{owner}/{repo}/rulesets")
    if not rulesets:
        return "none"
    for rs in rulesets:
        if rs.get("name") == name:
            return rs.get("enforcement", "unknown")
    return "none"


def _last_gate_run(owner: str, repo: str, branch: str) -> str:
    # Match by workflow FILENAME, not display name — at least one repo
    # (cra) has two workflows both displayed as "Security Scan", which
    # makes `--workflow "Security Scan"` ambiguous and errors out.
    # `--branch` matches a run's HEAD ref, not its PR base — a run whose
    # PR targeted this branch but whose head was a feature branch won't
    # match, so an empty result here doesn't necessarily mean "never
    # tested," just "never ran with this exact branch checked out."
    runs = _gh_json(
        "run", "list",
        "--repo", f"{owner}/{repo}",
        "--branch", branch,
        "--workflow", "security-gate.yml",
        "--limit", "5",
        "--json", "conclusion,status,createdAt",
    )
    if not runs:
        return "no run w/ this branch checked out (may still be tested via a PR head branch)"
    for run in runs:
        if run.get("status") == "completed":
            date = run["createdAt"].split("T")[0]
            return f"{date} ({run['conclusion']})"
    return "no completed run found"


def gather_row(owner: str, repo: str, branch: str) -> dict[str, str]:
    gate_content = _gh_content(owner, repo, ".github/workflows/security-gate.yml", branch)
    publish_content = _gh_content(owner, repo, ".github/workflows/publish-staging-chart-caller.yml", branch)

    gate_pin_ref = _extract_pin(gate_content) if gate_content else None
    # The ref is on c3cdao-ci-scans (the callee), never on the pilot repo
    # itself — resolving it against `repo` here always 404s.
    gate_pin_sha = (
        _resolve_ref_sha(owner, "c3cdao-ci-scans", gate_pin_ref) if gate_pin_ref else None
    )

    if publish_content is None:
        publish_contract = "not configured"
    elif "compose_file:" in publish_content:
        publish_contract = "compose_file (current)"
    elif "images:" in publish_content:
        publish_contract = "images: (RETIRED, needs migration)"
    else:
        publish_contract = "unknown shape"

    paths = _tree_paths(owner, repo, branch)
    hook = _grep_hook_annotation(owner, repo, branch, paths) if paths else False
    vex = any(p == ".openvex/templates/main.openvex.json" for p in paths)

    return {
        "pilot": repo.removeprefix("c3cdao-"),
        "repo": repo,
        "branch": branch,
        "gate_onboarded": "yes" if gate_content else "no",
        "gate_pin": f"{gate_pin_ref or '?'} @ {gate_pin_sha[:8] if gate_pin_sha else '?'}",
        "hook_mechanism": "yes" if hook else "no (fallback path)",
        "publish_contract": publish_contract,
        "vex": "yes" if vex else "no",
        "ruleset": _ruleset_enforcement(owner, repo) if branch != "ci-scans" else "n/a (non-default branch)",
        "last_run": _last_gate_run(owner, repo, branch),
    }


def render_markdown(rows: list[dict[str, str]]) -> str:
    header = "| Pilot | Branch | Gate pin | Hook mechanism | Publish contract | VEX | Ruleset | Last real run |"
    sep = "| --- | --- | --- | --- | --- | --- | --- | --- |"
    lines = [header, sep]
    for r in rows:
        lines.append(
            f"| {r['pilot']} | {r['branch']} | `{r['gate_pin']}` | {r['hook_mechanism']} "
            f"| {r['publish_contract']} | {r['vex']} | {r['ruleset']} | {r['last_run']} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "configs" / "fleet-pilots.yaml"))
    parser.add_argument("--format", choices=["md", "json"], default="md")
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text())
    owner = config["owner"]

    rows: list[dict[str, str]] = []
    for pilot in config["pilots"]:
        repo = pilot["repo"]
        for branch in pilot["branches"]:
            rows.append(gather_row(owner, repo, branch))

    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        print(render_markdown(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
