import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_core.cli import main
from atlas_core.router import list_routes
from atlas_core.skill_generator import generate_chatgpt_skill


class TestSkillGenerator(unittest.TestCase):
    def test_generates_skill_package_from_current_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = generate_chatgpt_skill(tmp)
            skill = (package / "SKILL.md").read_text(encoding="utf-8")
            routes = (package / "references" / "routes.md").read_text(encoding="utf-8")

        self.assertEqual(package.name, "atlas-core-loop")
        self.assertIn("name: atlas-core-loop", skill)
        self.assertIn("atlas run", skill)
        self.assertIn("explicit approval", skill)
        self.assertIn("Execute the selected route", skill)
        for route_name, spec in list_routes().items():
            with self.subTest(route=route_name):
                self.assertIn(f"`{route_name}`", routes)
                self.assertIn(spec["risk_level"], routes)
                self.assertIn(" -> ".join(spec["steps"]), routes)

    def test_refuses_to_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            generate_chatgpt_skill(tmp)
            with self.assertRaises(FileExistsError):
                generate_chatgpt_skill(tmp)

            package = generate_chatgpt_skill(tmp, force=True)

        self.assertEqual(package.name, "atlas-core-loop")

    def test_cli_generates_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("builtins.print") as output:
                result = main(["generate-skill", tmp])

            package = Path(tmp) / "atlas-core-loop"
            self.assertEqual(result, 0)
            self.assertTrue((package / "SKILL.md").is_file())
            output.assert_called_once_with(str(package))

    def test_checked_in_skill_matches_generator(self):
        checked_in = Path(__file__).parents[1] / "integrations" / "chatgpt-skill"
        with tempfile.TemporaryDirectory() as tmp:
            generated = generate_chatgpt_skill(tmp)
            for relative_path in (Path("SKILL.md"), Path("references/routes.md")):
                with self.subTest(path=relative_path):
                    self.assertEqual(
                        (checked_in / relative_path).read_text(encoding="utf-8"),
                        (generated / relative_path).read_text(encoding="utf-8"),
                    )


if __name__ == "__main__":
    unittest.main()
