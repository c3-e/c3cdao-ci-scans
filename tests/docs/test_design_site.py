"""Structure guards for the browser-readable design documentation."""

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
INDEX = DOCS / "index.html"
STYLES = DOCS / "site.css"
SCRIPT = DOCS / "site.js"


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
        "S ⊆ B ∪ E",
        "security-scan / Security Gate",
        "SECURITY_SCAN_BLOCKING",
        "evidence-compile",
    ):
        assert phrase in text


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
