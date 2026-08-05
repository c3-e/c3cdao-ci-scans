# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Derive the single Service-backed HTTP smoke target from a rendered chart.

cluster-smoke's post-deploy probe needs one unambiguous target: the
container with an httpGet readinessProbe whose probe port a Service
routes to (the same semantics the `smoke-target` lint rule enforces —
both consume lint_rules.chart.smoke_candidates, so a chart that passes
lint always derives, and a chart that cannot derive was already blocked
in the plan job).

Output (stdout, single-line JSON): {"workload", "container", "service",
"port", "path"} — the Service name/port to port-forward and the probe
path to curl. Zero or multiple candidates exit non-zero naming every
candidate (AC-2). `--image-only` skips derivation: image-only consumers
have no rendered chart claim (prints a skip marker, exits 0).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from lint_rules.chart import smoke_candidates


def derive_smoke_target(rendered: list[dict[str, Any]]) -> dict[str, Any]:
    """The single backed candidate, or SystemExit naming the candidates."""
    backed, unbacked = smoke_candidates(rendered)
    if len(backed) == 1:
        target = dict(backed[0])
        target.pop("description", None)
        return target
    if not backed:
        detail = (
            "HTTP readiness probes exist but no Service routes to them: "
            + "; ".join(unbacked)
            if unbacked
            else "no container declares an httpGet readinessProbe"
        )
        raise SystemExit(
            "error: smoke-target: rendered chart yields no Service-backed "
            f"HTTP readiness target ({detail})"
        )
    raise SystemExit(
        "error: smoke-target: rendered chart yields multiple Service-backed "
        "HTTP readiness targets; exactly one is required: "
        + "; ".join(c["description"] for c in backed)
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Derive the cluster-smoke HTTP probe target from a rendered chart."
    )
    parser.add_argument(
        "rendered", type=Path, help="multi-doc YAML rendered by helm template"
    )
    parser.add_argument(
        "--image-only",
        action="store_true",
        help="image_only consumer: no chart claim, skip derivation",
    )
    args = parser.parse_args(argv)
    if args.image_only:
        print(json.dumps({"skipped": "image_only"}))
        return 0
    try:
        docs = [
            d
            for d in yaml.safe_load_all(args.rendered.read_text())
            if isinstance(d, dict)
        ]
    except OSError as e:
        raise SystemExit(f"error: smoke-target: {args.rendered}: {e}") from e
    except yaml.YAMLError as e:
        raise SystemExit(
            f"error: smoke-target: {args.rendered}: unparseable rendered chart: {e}"
        ) from e
    print(json.dumps(derive_smoke_target(docs), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
