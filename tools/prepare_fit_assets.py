# -*- coding: utf-8 -*-
"""Prepara apenas as bibliotecas locais do analisador para o artifact do Pages.

A entrada pública do analisador permanece disponível no portal principal, com
processamento local e sem envio do currículo.
"""
from pathlib import Path
from html.parser import HTMLParser
import shutil
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX = DOCS / "index.html"
VENDOR = DOCS / "vendor"


class _PublicEntryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stylesheets = set()
        self.scripts = set()
        self.classes = set()
        self.anchors = []
        self._current_anchor = None

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "link" and "stylesheet" in (attributes.get("rel") or "").split():
            self.stylesheets.add(attributes.get("href"))
        elif tag == "script":
            self.scripts.add(attributes.get("src"))

        self.classes.update((attributes.get("class") or "").split())
        if tag == "a":
            self._current_anchor = {"attributes": attributes, "text": []}

    def handle_data(self, data):
        if self._current_anchor is not None:
            self._current_anchor["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._current_anchor is not None:
            self.anchors.append(self._current_anchor)
            self._current_anchor = None

    def handle_startendtag(self, tag, attributes):
        self.handle_starttag(tag, attributes)
        self.handle_endtag(tag)


def verify_public_entry_point():
    """Ensure the public, privacy-first analyzer link remains available."""
    text = INDEX.read_text(encoding="utf-8")
    parser = _PublicEntryParser()
    parser.feed(text)
    parser.close()

    missing = []
    has_stylesheet = any(
        urlsplit(path or "").path == "./fit-entry.css"
        for path in parser.stylesheets
    )
    if not has_stylesheet:
        missing.append("stylesheet ./fit-entry.css")
    has_script = any(
        urlsplit(path or "").path == "./fit-entry.js"
        for path in parser.scripts
    )
    if not has_script:
        missing.append("script ./fit-entry.js")
    if "hero-access-grid" not in parser.classes:
        missing.append("hero-access-grid")

    valid_cta = any(
        "data-fit-entry" in anchor["attributes"]
        and urlsplit(
            anchor["attributes"].get("href") or ""
        ).path == "./aderencia/"
        and "Analisar meu currículo"
        in " ".join(" ".join(anchor["text"]).split())
        for anchor in parser.anchors
    )
    if not valid_cta:
        missing.append('CTA público "Analisar meu currículo" apontando para ./aderencia/')

    if missing:
        raise RuntimeError(
            "acesso público ao analisador ausente: " + ", ".join(missing)
        )


def copy_vendor():
    sources = {
        ROOT / "node_modules" / "pdfjs-dist" / "build" / "pdf.mjs": VENDOR / "pdf.mjs",
        ROOT / "node_modules" / "pdfjs-dist" / "build" / "pdf.worker.mjs": VENDOR / "pdf.worker.mjs",
        ROOT / "node_modules" / "mammoth" / "mammoth.browser.min.js": VENDOR / "mammoth.browser.min.js",
    }
    VENDOR.mkdir(parents=True, exist_ok=True)
    for source, target in sources.items():
        if not source.exists():
            raise RuntimeError(f"dependência ausente: {source.relative_to(ROOT)}")
        shutil.copy2(source, target)


def verify():
    verify_public_entry_point()

    required = [
        VENDOR / "pdf.mjs",
        VENDOR / "pdf.worker.mjs",
        VENDOR / "mammoth.browser.min.js",
    ]
    if any(not path.exists() or path.stat().st_size < 1000 for path in required):
        raise RuntimeError("bibliotecas locais do analisador não foram preparadas")
    if not (DOCS / "aderencia" / "index.html").exists():
        raise RuntimeError("página de aderência ausente")


def main():
    verify_public_entry_point()
    copy_vendor()
    verify()
    print("OK: analisador público local preparado sem envio do currículo")


if __name__ == "__main__":
    main()
