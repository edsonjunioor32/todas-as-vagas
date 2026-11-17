# -*- coding: utf-8 -*-
"""Trava contra novos ``except`` amplos fora dos testes.

``except Exception``/``except BaseException``/``except:`` sem justificativa
escondem falhas de fonte.  Este teste compara a contagem por arquivo com a
baseline versionada e falha quando ela cresce.  Para um ``except`` amplo
legítimo (por exemplo, uma fronteira de isolamento), marque a linha com
``# noqa: BLE001 - motivo`` — a mesma convenção do ruff, então uma futura
adoção do linter não exige retrabalho.

Depois de reduzir excepts amplos, baixe a baseline com::

    python jobs-dashboard/tests/test_broad_except_ratchet.py --update
"""
import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).with_name("broad_except_baseline.json")
SCANNED_DIRS = ("jobs-dashboard", "tools", "ops")
ALLOW_MARKER = "noqa: BLE001"
BROAD_NAMES = {"Exception", "BaseException"}


def _is_broad(node_type):
    if node_type is None:
        return True
    if isinstance(node_type, ast.Name):
        return node_type.id in BROAD_NAMES
    if isinstance(node_type, ast.Attribute):
        return node_type.attr in BROAD_NAMES
    if isinstance(node_type, ast.Tuple):
        return any(_is_broad(element) for element in node_type.elts)
    return False


def _python_files():
    for directory in SCANNED_DIRS:
        base = REPO_ROOT / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            relative = path.relative_to(REPO_ROOT).as_posix()
            # Testes e scripts de diagnóstico (test_*.py) ficam fora da trava.
            if path.name.startswith("test_"):
                continue
            if "/tests/" in f"/{relative}" or "/__pycache__/" in f"/{relative}":
                continue
            yield relative, path


def unmarked_broad_handlers(path):
    """Linhas de ``except`` amplos sem a marcação de justificativa."""
    source = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _is_broad(node.type):
            if ALLOW_MARKER not in lines[node.lineno - 1]:
                found.append(node.lineno)
    return sorted(found)


def current_counts():
    counts = {}
    for relative, path in _python_files():
        found = unmarked_broad_handlers(path)
        if found:
            counts[relative] = found
    return counts


def load_baseline():
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


class BroadExceptRatchetTests(unittest.TestCase):
    def test_no_file_gains_unjustified_broad_excepts(self):
        baseline = load_baseline()
        violations = []
        for relative, lines in current_counts().items():
            allowed = int(baseline.get(relative, 0))
            if len(lines) > allowed:
                violations.append(
                    f"{relative}: {len(lines)} > baseline {allowed} (linhas {lines})"
                )
        self.assertFalse(
            violations,
            "Novos `except` amplos sem justificativa. Capture exceções específicas, "
            f"marque `# {ALLOW_MARKER} - motivo` ou, com justificativa no PR, rode "
            "`python jobs-dashboard/tests/test_broad_except_ratchet.py --update`.\n"
            + "\n".join(violations),
        )

    def test_detector_recognises_broad_forms_and_marker(self):
        sample = (
            "try:\n    pass\nexcept:\n    pass\n"
            "try:\n    pass\nexcept Exception:\n    pass\n"
            "try:\n    pass\nexcept (ValueError, BaseException):\n    pass\n"
            "try:\n    pass\nexcept Exception:  # noqa: BLE001 - fronteira\n    pass\n"
            "try:\n    pass\nexcept ValueError:\n    pass\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.py"
            path.write_text(sample, encoding="utf-8")
            self.assertEqual(unmarked_broad_handlers(path), [3, 7, 11])


def _update_baseline():
    counts = {relative: len(lines) for relative, lines in current_counts().items()}
    BASELINE_PATH.write_text(
        json.dumps(dict(sorted(counts.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"baseline atualizada: {sum(counts.values())} excepts amplos em {len(counts)} arquivos")


if __name__ == "__main__":
    if "--update" in sys.argv:
        _update_baseline()
    else:
        unittest.main()
