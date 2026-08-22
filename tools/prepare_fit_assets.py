# -*- coding: utf-8 -*-
"""Prepara a integração do analisador e bibliotecas locais no artifact do Pages."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX = DOCS / "index.html"
VENDOR = DOCS / "vendor"

STYLE_MARKER = '<link rel="stylesheet" href="./styles.css?v=14">'
SCRIPT_MARKER = '<script src="./app.js?v=13" defer></script>'
UPDATED_MARKER = '<p class="updated" id="updatedLabel"'
FIT_STYLE = '<link rel="stylesheet" href="./fit-entry.css?v=1">'
FIT_SCRIPT = '<script src="./fit-entry.js?v=1" defer></script>'
HERO_CTA = '''<div class="hero-fit-actions">
              <a class="hero-fit-cta" href="./aderencia/">Analisar meu currículo →</a>
              <span>Seu currículo fica somente no seu navegador.</span>
            </div>
            '''


def inject_index():
    text = INDEX.read_text(encoding="utf-8")
    if FIT_STYLE not in text:
        if STYLE_MARKER not in text:
            raise RuntimeError("marcador de CSS principal não encontrado")
        text = text.replace(STYLE_MARKER, STYLE_MARKER + "\n    " + FIT_STYLE, 1)
    if FIT_SCRIPT not in text:
        if SCRIPT_MARKER not in text:
            raise RuntimeError("marcador de app.js não encontrado")
        text = text.replace(SCRIPT_MARKER, SCRIPT_MARKER + "\n    " + FIT_SCRIPT, 1)
    if 'class="hero-fit-cta"' not in text:
        if UPDATED_MARKER not in text:
            raise RuntimeError("marcador de atualização do hero não encontrado")
        text = text.replace(UPDATED_MARKER, HERO_CTA + UPDATED_MARKER, 1)
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
    for marker in (FIT_STYLE, FIT_SCRIPT, 'class="hero-fit-cta"'):
        if marker not in text:
            raise RuntimeError(f"integração ausente: {marker}")
    required = [VENDOR / "pdf.mjs", VENDOR / "pdf.worker.mjs", VENDOR / "mammoth.browser.min.js"]
    if any(not path.exists() or path.stat().st_size < 1000 for path in required):
        raise RuntimeError("bibliotecas locais do analisador não foram preparadas")
    if not (DOCS / "aderencia" / "index.html").exists():
        raise RuntimeError("página de aderência ausente")


def main():
    inject_index()
    copy_vendor()
    verify()
    print("OK: integração do analisador preparada para o artifact do GitHub Pages")


if __name__ == "__main__":
    main()
