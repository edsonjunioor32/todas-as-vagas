# -*- coding: utf-8 -*-
"""Prepara apenas as bibliotecas locais do analisador para o artifact do Pages.

Os acessos visíveis ao analisador permanecem temporariamente ocultos do portal
principal enquanto a lógica de aderência é revisada.
"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX = DOCS / "index.html"
VENDOR = DOCS / "vendor"


def remove_public_entry_points():
    text = INDEX.read_text(encoding="utf-8")
    text = text.replace('    <link rel="stylesheet" href="./fit-entry.css?v=1">\n', '')
    text = text.replace('    <script src="./fit-entry.js?v=1" defer></script>\n', '')

    start = text.find('<div class="hero-fit-actions">')
    if start >= 0:
        end = text.find('</div>', start)
        if end >= 0:
            text = text[:start] + text[end + len('</div>'):]

    INDEX.write_text(text, encoding="utf-8")


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
    text = INDEX.read_text(encoding="utf-8")
    forbidden = ('fit-entry.css', 'fit-entry.js', 'hero-fit-cta', 'Analisar meu currículo')
    for marker in forbidden:
        if marker in text:
            raise RuntimeError(f"acesso público ao analisador ainda presente: {marker}")

    required = [VENDOR / "pdf.mjs", VENDOR / "pdf.worker.mjs", VENDOR / "mammoth.browser.min.js"]
    if any(not path.exists() or path.stat().st_size < 1000 for path in required):
        raise RuntimeError("bibliotecas locais do analisador não foram preparadas")
    if not (DOCS / "aderencia" / "index.html").exists():
        raise RuntimeError("página de aderência ausente")


def main():
    remove_public_entry_points()
    copy_vendor()
    verify()
    print("OK: analisador mantido sem acessos visíveis no portal público")


if __name__ == "__main__":
    main()
