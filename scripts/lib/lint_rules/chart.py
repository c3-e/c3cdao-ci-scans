"""Rendered-chart convention rules and the smoke-resource catalog rule.

Rule ids here: chart-readiness, smoke-target, ship-set, built-unscheduled
(warn only), smoke-resource-unknown. Chart rules are pure functions over
parsed rendered documents; `render_chart` owns the helm template
invocation. Non-image_only paths only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

from lint_rules import Verdict, verdict

WORKLOAD_KINDS = ("DaemonSet", "Deployment", "StatefulSet")
SMOKE_CATALOG = ("gateway-crds", "postgres-pgvector")


def render_chart(
    chart_path: Path, values: list[Path] | None = None
) -> list[dict[str, Any]]:
    """Parsed documents from `helm template` over the chart's local values.

    Fails closed (SystemExit with helm's stderr) when the chart does not
    render — the chart rules cannot run over an unrenderable chart.
    """
    command = ["helm", "template", str(chart_path)]
    for values_file in values or []:
        command += ["-f", str(values_file)]
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(
            f"error: helm template failed on {chart_path} "
            f"(exit {proc.returncode}); helm stderr follows\n{proc.stderr}"
        )
    try:
        return [doc for doc in yaml.safe_load_all(proc.stdout) if isinstance(doc, dict)]
    except yaml.YAMLError as e:
        raise SystemExit(
            f"error: helm template output for {chart_path} is unparseable: {e}"
        ) from e


def _workload_containers(
    rendered: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """(workload, pod_spec, container) triples for deployable workloads."""
    triples = []
    for doc in rendered:
        if not isinstance(doc, dict) or doc.get("kind") not in WORKLOAD_KINDS:
            continue
        pod_spec = ((doc.get("spec") or {}).get("template") or {}).get("spec") or {}
        for container in pod_spec.get("containers") or []:
            triples.append((doc, pod_spec, container))
    return triples


def _name(doc: dict[str, Any]) -> str:
    return str((doc.get("metadata") or {}).get("name", "<unnamed>"))


def chart_readiness(rendered: list[dict[str, Any]]) -> list[Verdict]:
    """Every container of every rendered deployable workload has readiness."""
    verdicts = []
    for workload, _, container in _workload_containers(rendered):
        if not container.get("readinessProbe"):
            verdicts.append(
                verdict(
                    "chart-readiness",
                    f"{workload['kind']} '{_name(workload)}' container "
                    f"'{container.get('name')}' has no readinessProbe",
                )
            )
    return verdicts


def _pod_labels(workload: dict[str, Any]) -> dict[str, Any]:
    template = (workload.get("spec") or {}).get("template") or {}
    return (template.get("metadata") or {}).get("labels") or {}


def _service_backs(
    service: dict[str, Any], workload: dict[str, Any], probe_port: Any
) -> bool:
    spec = service.get("spec") or {}
    selector = spec.get("selector") or {}
    labels = _pod_labels(workload)
    if not selector or any(labels.get(k) != v for k, v in selector.items()):
        return False
    for port in spec.get("ports") or []:
        if port.get("targetPort", port.get("port")) == probe_port:
            return True
    return False


def smoke_target(rendered: list[dict[str, Any]]) -> list[Verdict]:
    """Exactly one Service-backed HTTP readiness target must exist.

    Candidates are containers with an httpGet readinessProbe whose probe
    port is routed by a Service selecting the workload's pods; the
    post-deploy curl check needs one unambiguous target.
    """
    services = [
        d for d in rendered if isinstance(d, dict) and d.get("kind") == "Service"
    ]
    backed = []
    unbacked = []
    for workload, _, container in _workload_containers(rendered):
        http_get = (container.get("readinessProbe") or {}).get("httpGet")
        if not http_get:
            continue
        candidate = (
            f"{workload['kind']}/{_name(workload)} container '{container.get('name')}'"
        )
        matches = [
            _name(svc)
            for svc in services
            if _service_backs(svc, workload, http_get.get("port"))
        ]
        if matches:
            backed.append(f"{candidate} via Service {matches}")
        else:
            unbacked.append(candidate)
    if len(backed) == 1:
        return []
    if not backed:
        detail = (
            "HTTP readiness probes exist but no Service routes to them: "
            + "; ".join(unbacked)
            if unbacked
            else "no container declares an httpGet readinessProbe"
        )
        return [
            verdict(
                "smoke-target",
                f"rendered chart yields no Service-backed HTTP readiness "
                f"target ({detail})",
            )
        ]
    return [
        verdict(
            "smoke-target",
            "rendered chart yields multiple Service-backed HTTP readiness "
            "targets; exactly one is required: " + "; ".join(backed),
        )
    ]


# --- ship-set invariant -----------------------------------------------------------


def _built_tags(compose: dict[str, Any], classified: dict[str, Any]) -> set[str]:
    """B: the explicit image tags of the non-local build services."""
    return {
        str(compose["services"][name].get("image")) for name in classified["targets"]
    }


def _rendered_images(rendered: list[dict[str, Any]]) -> set[str]:
    """S: every container and init-container reference in the render."""
    images = set()
    for doc in rendered:
        if not isinstance(doc, dict) or doc.get("kind") not in WORKLOAD_KINDS:
            continue
        pod_spec = ((doc.get("spec") or {}).get("template") or {}).get("spec") or {}
        for key in ("containers", "initContainers"):
            for container in pod_spec.get(key) or []:
                if container.get("image"):
                    images.add(str(container["image"]))
    return images


def _repository(reference: str) -> str:
    return reference.rpartition("@")[0].partition(":")[0] or reference.partition(":")[0]


def ship_set(
    compose: dict[str, Any],
    classified: dict[str, Any],
    rendered: list[dict[str, Any]],
) -> list[Verdict]:
    """Enforce S \\ D subset-of B: every scheduled image is built-and-scanned
    or a declared dependency.

    Dependencies match by repository AND declared chart-tag, so a
    chart-side version bump blocks until the reviewed Compose declaration
    is updated (the block names both tags).
    """
    built = _built_tags(compose, classified)
    dependencies = classified["dependencies"]
    verdicts = []
    for image in sorted(_rendered_images(rendered)):
        if image in built:
            continue
        chart_tags = {dep["chart_tag"] for dep in dependencies}
        if image in chart_tags:
            continue
        repo_matches = [
            dep["chart_tag"]
            for dep in dependencies
            if _repository(dep["chart_tag"]) == _repository(image)
        ]
        if repo_matches:
            verdicts.append(
                verdict(
                    "ship-set",
                    f"chart schedules '{image}' but the declared dependency "
                    f"pins chart-tag '{repo_matches[0]}'; update the reviewed "
                    "Compose declaration to match",
                )
            )
        else:
            verdicts.append(
                verdict(
                    "ship-set",
                    f"chart schedules '{image}', which is neither built from "
                    "the compose file nor a declared downloaded dependency",
                )
            )
    return verdicts


def built_unscheduled(
    compose: dict[str, Any],
    classified: dict[str, Any],
    rendered: list[dict[str, Any]],
) -> list[Verdict]:
    """A built tag the chart never schedules is scanned anyway — warn only."""
    scheduled = _rendered_images(rendered)
    return [
        verdict(
            "built-unscheduled",
            f"built tag '{tag}' is never scheduled by the rendered chart; "
            "it is still built and scanned",
            level="warn",
        )
        for tag in sorted(_built_tags(compose, classified) - scheduled)
    ]


def smoke_resource_unknown(smoke_resources: str) -> list[Verdict]:
    """`smoke_resources` names gate-owned catalog modules only.

    A missing module is a ci-scans feature request, not a consumer escape
    hatch.
    """
    requested = [e.strip() for e in smoke_resources.split(",") if e.strip()]
    return [
        verdict(
            "smoke-resource-unknown",
            f"smoke resource '{entry}' is not in the gate catalog "
            f"{list(SMOKE_CATALOG)}",
        )
        for entry in requested
        if entry not in SMOKE_CATALOG
    ]
