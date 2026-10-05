import contextlib
import io
import json
import sys
import tempfile
import os
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "jobs-dashboard"))
import fit_requirements as fr
import pipeline_fit as pf
import validate_fit as vf


class FitRequirementsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.taxonomy = json.loads((ROOT / "docs" / "data" / "fit-taxonomy.json").read_text(encoding="utf-8"))

    def test_fit_writers_share_the_expanded_raw_size_cap(self):
        """The metadata-enrichment step must accept the current catalogue size."""
        self.assertEqual(pf.fit_requirements.DEFAULT_MAX_RAW_MB, fr.DEFAULT_MAX_RAW_MB)
        self.assertGreater(fr.DEFAULT_MAX_RAW_MB, 8.0)

    def test_dotnet_requirements_split_mandatory_and_preferred(self):
        job = {"description": (
            "Requisitos: Experiência com C#, .NET Framework e ASP.NET MVC (Razor); "
            "Conhecimento em SQL Server, HTML, CSS, JavaScript e jQuery; Vivência com sustentação de aplicações. "
            "Conhecimento em APIs REST, Git ou Azure DevOps será um diferencial. "
            "Diferenciais: Docker, Linux e inglês intermediário. Informações adicionais: benefícios."
        ), "skills": []}
        result = fr.extract_requirements(job, self.taxonomy)
        self.assertIn("C#", result["mandatory"])
        self.assertIn(".NET", result["mandatory"])
        self.assertIn("SQL Server", result["mandatory"])
        self.assertIn("APIs REST", result["preferred"])
        self.assertIn("Linux", result["preferred"])
        self.assertNotIn("Microsoft Azure", result["mandatory"])
        self.assertGreaterEqual(result["confidence"], 85)

    def test_plsql_does_not_duplicate_sql(self):
        result = fr.extract_requirements({"description": "Requisitos: Experiência com Oracle, Java e PL/SQL.", "skills": []}, self.taxonomy)
        self.assertIn("PL/SQL", result["mandatory"])
        self.assertNotIn("SQL", result["mandatory"])

    def test_unknown_technology_is_kept_as_dynamic_requirement(self):
        result = fr.extract_requirements({"description": "Requisitos: Experiência com Oracle. Diferenciais: Familiaridade com APIs, Postman e Keycloak. Conhecimento em KCS.", "skills": []}, self.taxonomy)
        self.assertIn("Keycloak", result["preferred"])
        self.assertIn("KCS", result["preferred"])

    def test_manual_constraints_are_not_resume_gaps(self):
        result = fr.extract_requirements({"description": "Requisitos: SQL e Linux. Disponibilidade para viagens e atuação em escala de plantão.", "skills": []}, self.taxonomy)
        self.assertIn("Disponibilidade para viagens", result["manual"])
        self.assertIn("Disponibilidade de horário/turno", result["manual"])

    def test_export_does_not_store_description(self):
        rows = [{
            "url": "https://example.com/job/1",
            "description": (
                "Sobre a oportunidade. Requisitos: experiência com SQL e Linux para análise de incidentes, "
                "consulta de dados e troubleshooting em produção. Diferenciais: Docker e conhecimento em APIs REST. "
                "A pessoa atuará em conjunto com times de engenharia e operações na sustentação da plataforma."
            ),
            "skills": [],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fit.json"
            count, size_mb = fr.export_fit_index(rows, out, taxonomy_path=ROOT / "docs" / "data" / "fit-taxonomy.json")
            self.assertEqual(count, 1)
            self.assertLess(size_mb, 1)
            text = out.read_text(encoding="utf-8")
            self.assertNotIn("análise de incidentes", text)
            self.assertIn("https://example.com/job/1", json.loads(text)["jobs"])

    def test_export_skips_job_without_internal_description(self):
        rows = [{
            "url": "https://example.com/job/skills-only",
            "description": "",
            "skills": ["SQL", "Linux", "Docker"],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fit.json"
            count, _ = fr.export_fit_index(rows, out, taxonomy_path=ROOT / "docs" / "data" / "fit-taxonomy.json")
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(count, 0)
            self.assertEqual(payload["count"], 0)
            self.assertEqual(payload["jobs"], {})

    def test_export_skips_too_short_description(self):
        rows = [{
            "url": "https://example.com/job/short",
            "description": "Requisitos: SQL e Linux.",
            "skills": ["SQL", "Linux"],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fit.json"
            count, _ = fr.export_fit_index(rows, out, taxonomy_path=ROOT / "docs" / "data" / "fit-taxonomy.json")
            self.assertEqual(count, 0)

    def test_pii_terms_are_quarantined_and_job_indexes_are_rebuilt(self):
        payload = {
            "schema_version": 1,
            "count": 2,
            "terms": ["Python", "user@example.com", "SQL", "00000000000", "Docker"],
            "jobs": {
                "https://example.com/job/kept": {
                    "m": [0, 1, 4], "p": [3], "c": [2], "x": [], "q": 95,
                },
                "https://example.com/job/removed": {
                    "m": [3], "p": [], "c": [], "x": [], "q": 45,
                },
            },
        }

        clean, summary = pf.quarantine_pii_terms(payload)

        self.assertEqual(clean["terms"], ["Python", "SQL", "Docker"])
        self.assertEqual(clean["jobs"]["https://example.com/job/kept"]["m"], [0, 2])
        self.assertEqual(clean["jobs"]["https://example.com/job/kept"]["p"], [])
        self.assertEqual(clean["jobs"]["https://example.com/job/kept"]["c"], [1])
        self.assertNotIn("https://example.com/job/removed", clean["jobs"])
        self.assertEqual(clean["count"], 1)
        self.assertEqual(summary, {"terms": 2, "references": 3, "entries": 1})
        serialized = json.dumps(clean)
        self.assertNotIn("user@example.com", serialized)
        self.assertNotIn("00000000000", serialized)

    def test_pii_quarantine_preserves_malformed_references_for_validation(self):
        payload = {
            "terms": ["Python", "private@example.com"],
            "jobs": {"https://example.com/job/1": {"m": [99], "p": [], "c": [], "x": [], "q": 50}},
        }

        clean, summary = pf.quarantine_pii_terms(payload)

        self.assertEqual(clean["jobs"]["https://example.com/job/1"]["m"], [99])
        self.assertEqual(summary["terms"], 1)
        self.assertIsNotNone(pf.validate_entry("https://example.com/job/1", clean["jobs"]["https://example.com/job/1"], len(clean["terms"])))

    def test_pipeline_export_applies_pii_quarantine_before_publication(self):
        generated = {
            "schema_version": 1,
            "generated_at": "2026-10-05T00:00:00+00:00",
            "count": 1,
            "terms": ["Python", "person@example.com"],
            "jobs": {
                "https://example.com/job/1": {
                    "m": [0, 1], "p": [], "c": [], "x": [], "q": 95,
                },
            },
        }

        def write_generated_index(_rows, out_path):
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(json.dumps(generated), encoding="utf-8")
            return 1, 0.1

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "docs" / "data" / "fit.json"
            output = io.StringIO()
            with patch.object(pf, "ROOT", root), patch.object(pf, "FIT_JSON", target), patch.object(
                pf.fit_requirements, "export_fit_index", side_effect=write_generated_index
            ), contextlib.redirect_stdout(output):
                pf.export_fit_index([])

            clean = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(clean["terms"], ["Python"])
            self.assertEqual(clean["jobs"]["https://example.com/job/1"]["m"], [0])
            self.assertEqual(clean["count"], 1)
            self.assertIsNone(
                pf.validate_entry(
                    "https://example.com/job/1",
                    clean["jobs"]["https://example.com/job/1"],
                    len(clean["terms"]),
                )
            )
            self.assertNotIn("person@example.com", target.read_text(encoding="utf-8"))
            self.assertNotIn("person@example.com", output.getvalue())
            self.assertIn("valores omitidos", output.getvalue())
            validation_output = io.StringIO()
            with patch.object(vf, "FIT", target), patch.object(
                vf, "TAXONOMY", ROOT / "docs" / "data" / "fit-taxonomy.json"
            ), contextlib.redirect_stdout(validation_output):
                vf.main()
            self.assertIn("sem descrições/PII", validation_output.getvalue())

    def test_quarantine_removes_only_invalid_fit_entry(self):
        valid_url = "https://example.com/job/valid"
        invalid_url = "https://example.com/job/invalid"
        payload = {
            "schema_version": 1,
            "count": 2,
            "terms": ["Python"],
            "jobs": {
                valid_url: {"m": [0], "p": [], "c": [], "x": [], "q": 95, "t": "Analista"},
                invalid_url: {"m": [], "p": [], "c": [], "x": [], "q": 95, "t": "description " * 30},
            },
        }
        with patch.dict(os.environ, {"FIT_MAX_QUARANTINE_RATIO": "0.50"}):
            clean, rejected = pf.quarantine_invalid_entries(payload)
        self.assertEqual(list(clean["jobs"]), [valid_url])
        self.assertEqual(clean["count"], 1)
        self.assertEqual(rejected[0]["url"], invalid_url)
        self.assertIn("metadado t", rejected[0]["reason"])

    def test_quarantine_blocks_degradation_above_configured_ratio(self):
        jobs = {
            f"https://example.com/job/{index}": {
                "m": [], "p": [], "c": [], "x": [], "q": 95,
                "t": "description " * (30 if index == 0 else 0) or "Analista",
            }
            for index in range(10)
        }
        payload = {"schema_version": 1, "count": 10, "terms": [], "jobs": jobs}
        with self.assertRaisesRegex(RuntimeError, "proporção"):
            pf.quarantine_invalid_entries(payload)


if __name__ == "__main__":
    unittest.main()

