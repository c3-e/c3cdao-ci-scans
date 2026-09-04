"""Structure guards for the browser-readable design documentation.

Docs-cutover additions: a drift guard (published docs never instruct the retired
v0.5 machinery), lint remediation-anchor resolution, and consumer-shape
convention coverage.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
INDEX = DOCS / "index.html"
STYLES = DOCS / "site.css"
SCRIPT = DOCS / "site.js"
SCRIPTS_LIB = ROOT / "scripts" / "lib"


class _StructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.has_main = False
        self.has_nav = False

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag == "a" and values.get("href"):
            self.links.append(str(values["href"]))
        self.has_main |= tag == "main"
        self.has_nav |= tag == "nav"


def _parse() -> tuple[str, _StructureParser]:
    text = INDEX.read_text()
    parser = _StructureParser()
    parser.feed(text)
    return text, parser


def test_design_site_has_local_assets() -> None:
    assert INDEX.is_file()
    assert STYLES.is_file()
    assert SCRIPT.is_file()
    text = INDEX.read_text()
    assert 'href="site.css"' in text
    assert 'src="site.js"' in text
    assert "https://cdn." not in text


def test_design_site_has_semantic_navigation() -> None:
    _, parser = _parse()
    assert parser.has_main
    assert parser.has_nav
    required = {
        "overview",
        "architecture",
        "contract",
        "security",
        "evidence",
        "rollout",
    }
    assert required <= parser.ids
    assert {link[1:] for link in parser.links if link.startswith("#")} <= parser.ids


def test_design_site_explains_locked_design() -> None:
    text = INDEX.read_text()
    for phrase in (
        "docker buildx bake",
        "S \\ D ⊆ B",
        "x-downloaded-dependency",
        "dependency-shape",
        "security-scan / Security Gate",
        "SECURITY_SCAN_BLOCKING",
        "Signed durable evidence",
        "DATABASE_URL",
        "One file per concern",
        "Sources of truth",
    ):
        assert phrase in text
    assert "evidence-compile" not in text


def test_design_site_supports_browser_interaction() -> None:
    script = SCRIPT.read_text()
    assert "IntersectionObserver" in script
    assert "data-theme-toggle" in script
    assert "data-view" in script


def test_design_site_avoids_marketing_and_ai_prose_patterns() -> None:
    text = INDEX.read_text()
    for phrase in (
        "One gate.",
        "What changes",
        "Why build and scan stay separate",
        "every existing security check",
        "not scan coverage",
    ):
        assert phrase.casefold() not in text.casefold()
    assert "—" not in text
    assert re.search(r"\bnot\b.{0,80}\bbut\b", text, re.IGNORECASE) is None


def test_published_docs_do_not_name_pilot_repositories() -> None:
    forbidden = (
        "petegpt",
        "c3cdao-ppubs",
        "c3cdao-apps",
        "c3cdao-dsa-ecpilot",
        "c3-joshchiu/c3cdao-ci-scans",
    )
    for path in (*DOCS.glob("*.md"), *DOCS.glob("*.html")):
        text = path.read_text().casefold()
        for name in forbidden:
            assert name not in text, f"{path.relative_to(ROOT)} names {name}"


# --- docs-cutover guards -------------------------------------------------
#
# Published pages = the four Markdown contracts, the site, and the README.

def _published_docs() -> list[Path]:
    return [*sorted(DOCS.glob("*.md")), *sorted(DOCS.glob("*.html")), ROOT / "README.md"]


# Retired v0.5 machinery: published docs must never instruct consumers to use
# it again. Historical "what changed" prose is fine; usage shapes are not.
_RETIRED_INSTRUCTIONS = (
    r"cp\s+\S*Makefile\.ci",
    r"\bmake\b[^\n`]*\bci-(manifest|build|secctx|smoke-env)\b",
    r"contract_file:",
    r"scan_image:",
    r"require_hardened_bases:",
    r"images\[0\]",
    r"templates/consumer/",
)

# require_hardened_bases: is retired only on reusable-security-gate.yml;
# publish-staging-chart.yml's own live, differently-scoped boolean of the
# same name would otherwise false-positive here.
_RETIRED_INSTRUCTIONS_EXCLUDE = {
    r"require_hardened_bases:": {"PUBLISH-STAGING-CHART.md"},
}


def test_drift_guard_docs_never_instruct_retired_machinery() -> None:
    """A doc reintroducing Makefile.ci/contract_file instructions fails."""
    violations = []
    for path in _published_docs():
        rel = path.relative_to(ROOT)
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for pattern in _RETIRED_INSTRUCTIONS:
                if path.name in _RETIRED_INSTRUCTIONS_EXCLUDE.get(pattern, ()):
                    continue
                if re.search(pattern, line, re.IGNORECASE):
                    violations.append(
                        f"{rel}:{lineno}: instructs retired machinery "
                        f"({pattern!r}): {line.strip()}"
                    )
    assert not violations, "\n".join(violations)


def _slugify(heading: str) -> str:
    """GitHub-style heading slug (enough for our ASCII rule headings)."""
    text = heading.strip().lower().replace("`", "")
    text = re.sub(r"[^a-z0-9 _-]", "", text)
    return text.replace(" ", "-")


def _emitted_remediation_anchors() -> set[str]:
    """Every #rule-<id> anchor the lint can emit, read from the sources."""
    sources = (SCRIPTS_LIB / "lint_caller.py").read_text() + "".join(
        p.read_text() for p in sorted(SCRIPTS_LIB.glob("lint_rules/*.py"))
    )
    rule_ids = set(re.findall(r"verdict\(\s*\n?\s*\"([a-z-]+)\"", sources))
    assert len(rule_ids) >= 21, f"expected >=21 emitted rule ids, found {sorted(rule_ids)}"
    return {f"rule-{rule_id}" for rule_id in rule_ids}


def test_lint_remediation_anchors_resolve() -> None:
    """Every remediation_ref anchor resolves to a CI-CONTRACT heading."""
    contract = (DOCS / "CI-CONTRACT.md").read_text()
    heading_slugs = {
        _slugify(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.+)$", contract, re.MULTILINE)
    }
    missing = sorted(_emitted_remediation_anchors() - heading_slugs)
    assert not missing, f"remediation anchors with no CI-CONTRACT.md heading: {missing}"


def test_site_lint_grid_in_sync() -> None:
    """The hand-maintained lint grid in index.html stays a true subset:
    every <code> entry is a real rule id, and the count label matches."""
    html = (DOCS / "index.html").read_text()
    grid_match = re.search(
        r'<small>(\d+) design rules</small>.*?<div class="lint-grid">(.*?)</div>',
        html,
        re.DOTALL,
    )
    assert grid_match, "lint-grid section with a '<N> design rules' label not found"
    labeled_count = int(grid_match.group(1))
    grid_ids = re.findall(r"<code>([a-z-]+)</code>", grid_match.group(2))
    assert len(grid_ids) == labeled_count, (
        f"label says {labeled_count} rules, grid lists {len(grid_ids)}"
    )
    emitted = {a.removeprefix("rule-") for a in _emitted_remediation_anchors()}
    unknown = sorted(set(grid_ids) - emitted)
    assert not unknown, f"site lint grid names rule ids the lint never emits: {unknown}"


def test_consumer_shape_assumptions_published() -> None:
    """Every consumer-shape convention row is documented for onboarding."""
    text = (DOCS / "CI-CONTRACT.md").read_text() + (DOCS / "RUNBOOK.md").read_text()
    for convention in (
        "profiles: [local]",       # C3 local-only exclusion, exact spelling
        "ten",                     # C4 matrix cap
        ":latest",                 # C5 rejected tag
        "$$",                      # B3/C6 literal-dollar escape
        "x-downloaded-dependency", # D1 marker key
        "chart-tag",               # D1 hyphen spelling
        "@sha256:",                # D2 in-image digest pin
        "exact",                   # D3 exact-string ship-set matching
        ".dockerignore",           # B5 four literal lines
        ".env",
        "*.pem",
        "*.key",
        "*credentials*",
        "TOKEN",                   # B4 secret-like arg-name heuristic
        "_KEY",
        "Deployment",              # H2 workload kinds
        "StatefulSet",
        "DaemonSet",
        "readinessProbe",          # H3
        "targetPort",              # H4 Service-backed probe-port matching
        "40-hex",                  # W1 gate pin
        "postgres-pgvector",       # W4 smoke catalog
        "gateway-crds",
        "app-database-url",        # ADR-08 decoupled DB standard
        "DATABASE_URL",
    ):
        assert convention in text, f"convention {convention!r} not published in CI-CONTRACT.md/RUNBOOK.md"
