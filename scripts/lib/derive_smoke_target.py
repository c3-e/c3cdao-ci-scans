# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Derive the single Service-backed HTTP smoke target from a rendered chart.

Consumes the same `lint_rules.chart.smoke_candidates` as the
`smoke-target` lint rule, so a chart that passes lint always derives here.

Output (stdout, single-line JSON): {"workload", "container", "service",
"port", "path"}. Zero or multiple candidates exit non-zero naming them.
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
    args = parser.parse_args(argv)
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
