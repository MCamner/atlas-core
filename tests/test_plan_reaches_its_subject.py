"""P1.1: the two places a narrowed question used to be lost on the way.

Both were found by running the loop against a real repository at a pinned
commit — `docs/pinned-repo-review.md` — and neither was visible to the fixture
benchmark or to any test, because the fixture's task string was chosen once and
always reached `repo_review`.

1. **The router and the plan used two independent keyword lists.** `granska
   CI-workflow och release-gate` selected `general`: no plan, no patterns, no
   reading, no evidence criteria. `build_review_plan` on the same string
   returned topic `ci`. The topic was computed and thrown away.
2. **The `ci` topic named only configuration files.** A question about whether
   CI runs what a local gate runs could only ever read the CI half, because
   `release-check.sh` matched none of its patterns.
"""

from __future__ import annotations

import subprocess
import unittest
from fnmatch import fnmatch
from pathlib import Path

from atlas_core import AtlasController
from atlas_core.planner import build_plan
from atlas_core.review_plan import TOPICS, build_review_plan, detect_topic
from atlas_core.router import select_route

CI_TASK = "granska CI-workflow och release-gate"


class TestATaskThatNarrowsReachesAPlan(unittest.TestCase):
    def test_the_case_the_pinned_run_fell_into(self):
        """Verbatim the string that read nothing."""
        route = select_route(CI_TASK)
        topic = detect_topic(CI_TASK)

        self.assertEqual(route.name, "repo_review")
        self.assertIsNotNone(topic)
        assert topic is not None
        self.assertEqual(topic.code, "ci")

    def test_the_weaker_signal_is_reported_as_weaker(self):
        """No keyword matched, and the confidence must not say one did."""
        weak = select_route(CI_TASK)
        keyworded = select_route("granska repo atlas-core")

        self.assertLess(weak.confidence, keyworded.confidence)
        self.assertIn("ci", weak.reason)

    def test_a_route_that_matched_keeps_what_it_matched_on(self):
        """The negative control, and the reason this only fires on no match.

        "Varför fastnar testerna" is a root cause question whose words happen
        to include `test`. Taking it for a repo review because the topic
        vocabulary recognised that word would be the same mistake pointing the
        other way.
        """
        self.assertEqual(select_route("granska varför testerna fastnar").name, "root_cause")
        self.assertEqual(select_route("förklara vad CI är").name, "learning")
        self.assertEqual(select_route("jämför två alternativ för release").name, "decision_tradeoff")

    def test_a_task_with_no_topic_is_still_general(self):
        self.assertEqual(select_route("hej").name, "general")
        self.assertEqual(select_route("gör något bra med det här").name, "general")

    def test_asking_to_examine_is_required_not_merely_naming_a_topic(self):
        """A topic word alone is not a request to look at anything."""
        self.assertEqual(select_route("CI-workflow och release-gate").name, "general")


class TestADiscardedTopicIsSaidOutLoud(unittest.TestCase):
    """The other half of the fix: the vocabularies can still disagree."""

    def test_a_route_with_no_review_contract_records_the_question_it_declined(self):
        route = select_route("granska varför testerna fastnar")
        plan = build_plan("granska varför testerna fastnar", route)

        self.assertIsNone(plan.review)
        self.assertIsNotNone(plan.unused_topic)
        assert plan.unused_topic is not None
        self.assertEqual(plan.unused_topic["topic"], "tests")
        self.assertEqual(
            plan.unused_topic["reason"], "route_has_no_review_contract"
        )

    def test_a_review_route_without_a_snapshot_says_which_reason(self):
        plan = build_plan(CI_TASK, select_route(CI_TASK))

        self.assertIsNone(plan.review)
        assert plan.unused_topic is not None
        self.assertEqual(plan.unused_topic["reason"], "no_snapshot")

    def test_a_task_that_narrows_to_nothing_reports_nothing(self):
        """Negative control: silence must mean "no question", not "lost one"."""
        plan = build_plan("hej", select_route("hej"))

        self.assertIsNone(plan.unused_topic)

    def test_it_reaches_the_run_document(self):
        run = AtlasController(max_iterations=1).run(
            "granska varför testerna fastnar", json_mode=True
        )

        self.assertEqual(run["plan"]["unused_topic"]["topic"], "tests")
        self.assertIsNone(run["plan"]["review"])


class TestATopicCanNameSourcesThatAreNotConfiguration(unittest.TestCase):
    def test_the_ci_topic_reaches_a_shell_gate(self):
        plan = build_review_plan(CI_TASK, "snap-1")

        self.assertTrue(
            any(fnmatch("release-check.sh", p) for p in plan.patterns),
            f"a local gate is not a config file; patterns were {plan.patterns}",
        )

    def test_every_topic_still_fits_inside_the_bound(self):
        from atlas_core.review_plan import MAX_PATTERNS

        for topic in TOPICS:
            with self.subTest(topic.code):
                self.assertLessEqual(len(topic.patterns), MAX_PATTERNS)


class TestAgainstThePinnedRepository(unittest.TestCase):
    """The completion criterion names this repository and this question.

    Skipped when the checkout is not present: the test asserts something about
    a specific commit of a specific repository, and a skip says so rather than
    quietly passing. `scripts/pinned_repo_review.py` prints how to make one.
    """

    COMMIT = "e5c4064733c4fced62b71f47e7b16e9335168532"
    CANDIDATES = (
        Path("/tmp/mq-image-analyze"),
        Path(__file__).resolve().parent.parent.parent / "mq-image-analyze",
    )

    def _checkout(self) -> Path:
        for path in self.CANDIDATES:
            if (path / ".git").is_dir():
                head = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=path, capture_output=True, text=True,
                ).stdout.strip()
                if head == self.COMMIT:
                    return path
        self.skipTest(f"no checkout of mq-image-analyze at {self.COMMIT[:8]}")

    def test_the_local_gate_is_now_reachable_through_the_plan(self):
        root = self._checkout()
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.split()
        plan = build_review_plan(CI_TASK, "snap-1")

        resolved = {p for p in tracked for q in plan.patterns if fnmatch(p, q)}

        self.assertIn("release-check.sh", resolved)
        self.assertIn(".github/workflows/gate-parity.yml", resolved)


if __name__ == "__main__":
    unittest.main()
