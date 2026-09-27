import unittest
from atlas_core.router import select_route

class TestRouter(unittest.TestCase):
    def test_repo_review_route(self):
        route = select_route("granska repo och hitta P0 P1 P2 förbättringar")
        self.assertEqual(route.name, "repo_review")

    def test_architecture_route(self):
        route = select_route("bygg målarkitektur för säker AI-assistent med Zero Trust")
        self.assertEqual(route.name, "architecture_decision")

    def test_root_cause_route(self):
        route = select_route("hitta grundorsaken till varför releaseflödet fastnar")
        self.assertEqual(route.name, "root_cause")

    def test_named_atlas_ci_review_uses_repo_review_topic(self):
        route = select_route(
            "Granska CI-konfigurationen i atlas-core och avgör om workflowet "
            "för manuell körning använder samma testkommando som test-gaten"
        )
        self.assertEqual(route.name, "repo_review")
        self.assertIn("ämnet 'ci'", route.reason)

    def test_prompt_improvement_still_requires_prompt_signal(self):
        route = select_route("förbättra Atlas system prompt för tydligare routing")
        self.assertEqual(route.name, "prompt_improvement")

if __name__ == "__main__":
    unittest.main()
