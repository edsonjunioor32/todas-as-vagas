import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "jobs-dashboard"))
import fit_requirements as fr


class FitRequirementsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.taxonomy = json.loads((ROOT / "docs" / "data" / "fit-taxonomy.json").read_text(encoding="utf-8"))

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
        rows = [{"url": "https://example.com/job/1", "description": "Requisitos: Experiência com SQL e Linux. Diferenciais: Docker.", "skills": []}]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fit.json"
            count, size_mb = fr.export_fit_index(rows, out, taxonomy_path=ROOT / "docs" / "data" / "fit-taxonomy.json")
            self.assertEqual(count, 1)
            self.assertLess(size_mb, 1)
            text = out.read_text(encoding="utf-8")
            self.assertNotIn("Experiência com SQL e Linux", text)
            self.assertIn("https://example.com/job/1", json.loads(text)["jobs"])


if __name__ == "__main__":
    unittest.main()
