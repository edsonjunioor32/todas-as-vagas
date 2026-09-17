# -*- coding: utf-8 -*-
"""Prepara apenas as bibliotecas locais do analisador para o artifact do Pages.

A entrada pública do analisador permanece disponível no portal principal, com
processamento local e sem envio do currículo.
"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX = DOCS / "index.html"
VENDOR = DOCS / "vendor"


def verify_public_entry_point():
    """Ensure the public, privacy-first analyzer link remains available."""
    text = INDEX.read_text(encoding="utf-8")
    required = (
        "fit-entry.css",
        "hero-fit-actions",
        "data-fit-entry",
        "./aderencia/",
    )
    missing = [marker for marker in required if marker not in text]
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
