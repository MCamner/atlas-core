"""v1.3 box one: `atlas-run.v1` into `Run.v2`, and what that must not cost.

The test that matters here is not that an old example can be migrated. Any
function that returns a dict can do that. It is the round trip:

    atlas-run.v1 -> migrate -> Run.v2 -> serialize -> read again
    -> the same observable information

and its negative control:

    a field v1 actually carried must never disappear just because v2
    has no natural place for it

So the round trip is asserted over documents the loop really produces, across
routes and stop reasons, rather than over one fixture chosen to pass. And the
loss check is a set equation over the source document's own keys, which means a
field added to v1 later cannot slip through by being unknown to the migration.

The other half is the rule about defaults. A migration that fills in a plausible
value is worse than one that fails, because a plausible value is indistinguishable
from a measured one. Every assertion below that looks pedantic — `actions` is
`None` and not `[]`, `score_method` is `unknown` and not today's method — is
that rule at one specific place where getting it wrong would be invisible.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from atlas_core import AtlasController, StubModelAdapter
from atlas_core.migrate import (
    NOT_RECORDED_IN_V1,
    SOURCE_SCHEMA,
    TARGET_SCHEMA,
    UnknownSourceSchema,
    approval_is_well_formed,
    migrate_run,
)

from test_schemas import SchemaAssertions, load

ANSWER = (
    "# Svar\n\nEtt svar långt nog att räknas, med tillräckligt innehåll för "
    "substanskravet i den generella routen. " * 4
    + "\n\n## Observed sources\n- `README.md`\n"
    + "\n## Recommendation\nX.\n\n## Next step\nY.\n\n## Confidence\nHög.\n"
)


def real_runs() -> list[dict[str, Any]]:
    """Documents the loop actually produces, not fixtures written to pass.

    Spread across routes, stop reasons and shapes on purpose: a run that passed,
    one that did not, one with a model adapter and one without, one that needs
    approval, and one with more than one iteration.
    """
    return [
        AtlasController(max_iterations=1).run("hej", json_mode=True),
        AtlasController(max_iterations=1).run("granska repo atlas-core", json_mode=True),
        AtlasController(max_iterations=2).run("granska repo atlas-core", json_mode=True),
        AtlasController(max_iterations=1).run("commit till main", json_mode=True),
        AtlasController(max_iterations=1, model_adapter=StubModelAdapter(ANSWER)).run(
            "granska repo atlas-core",
            observations=["README.md:\n# Atlas Core"],
            json_mode=True,
        ),
        AtlasController(max_iterations=1).run("förklara vad CI är", json_mode=True),
    ]


class TestTheRoundTrip(SchemaAssertions):
    def test_every_source_key_is_either_mapped_or_kept(self):
        """The loss check, as a set equation over the source's own keys. Not a
        list this code maintains — a v1 field added later cannot slip through by
        being unknown here."""
        for document in real_runs():
            target, report = migrate_run(document)
            accounted = set(report.mapped) | set(report.unmapped)
            with self.subTest(task=document["task"]):
                self.assertEqual(set(document) - accounted, set())

    def test_every_source_value_survives_a_serialize_and_a_read(self):
        """The round trip itself. Through JSON, because a migration that only
        holds up in memory is one whose result nobody can store."""
        for document in real_runs():
            target, report = migrate_run(document)
            reread = json.loads(json.dumps(target))
            with self.subTest(task=document["task"]):
                for key, value in document.items():
                    if key == "schema":
                        continue
                    if key in report.unmapped:
                        self.assertEqual(reread["migration"]["unmapped"][key], value)
                    elif key == "evaluations":
                        # Carried with identity added, never with anything taken.
                        for before, after in zip(value, reread[key]):
                            self.assertEqual(
                                {k: v for k, v in after.items() if k in before}, before
                            )
                    else:
                        self.assertEqual(reread[key], value)

    def test_the_result_matches_the_v2_schema(self):
        schema = load("atlas-run.v2.json")
        for document in real_runs():
            target, _ = migrate_run(document)
            with self.subTest(task=document["task"]):
                self.assert_matches(schema, target, "atlas-run.v2")

    def test_each_evaluation_matches_the_evaluation_v2_schema(self):
        schema = load("atlas-evaluation.v2.json")
        for document in real_runs():
            target, _ = migrate_run(document)
            for evaluation in target["evaluations"]:
                with self.subTest(task=document["task"]):
                    self.assert_matches(schema, evaluation, "atlas-evaluation.v2")

    def test_a_real_run_migrates_without_parking_anything(self):
        """`is_lossless` is the stronger claim: not merely that nothing was
        dropped, but that nothing had to be kept under another name."""
        for document in real_runs():
            _, report = migrate_run(document)
            with self.subTest(task=document["task"]):
                self.assertTrue(report.is_lossless, f"parked: {sorted(report.unmapped)}")


class TestNothingDisappears(SchemaAssertions):
    """The negative control the round trip cannot provide on its own: a field v2
    has no natural place for."""

    def _v1(self, **overrides: Any) -> dict[str, Any]:
        document = AtlasController(max_iterations=1).run("hej", json_mode=True)
        document.update(overrides)
        return document

    def test_a_field_v2_has_no_place_for_is_kept_with_its_value(self):
        document = self._v1(experimental_counter={"reads": 3})

        target, report = migrate_run(document)

        self.assertIn("experimental_counter", report.unmapped)
        self.assertEqual(
            target["migration"]["unmapped"]["experimental_counter"], {"reads": 3}
        )
        self.assertFalse(report.is_lossless)

    def test_the_value_is_kept_and_not_only_the_name(self):
        """A migration that records only *that* something was dropped has still
        dropped it."""
        document = self._v1(legacy_scores=[0.4, 0.9])

        target, _ = migrate_run(document)

        self.assertEqual(target["migration"]["unmapped"]["legacy_scores"], [0.4, 0.9])

    def test_a_parked_field_does_not_become_a_top_level_v2_field(self):
        """`atlas-run.v2` is `additionalProperties: false`. A migration that put
        an unknown key at the top level would produce a document that fails its
        own schema."""
        document = self._v1(experimental_counter=1)

        target, _ = migrate_run(document)

        self.assertNotIn("experimental_counter", target)

    def test_a_required_field_the_source_lacked_is_recorded_not_filled_in(self):
        document = self._v1()
        del document["max_iterations"]

        target, report = migrate_run(document)

        self.assertIn("max_iterations", report.missing)
        self.assertIn("max_iterations", target["migration"]["missing"])
        self.assertNotIn("max_iterations", target)

    def test_an_incomplete_result_says_so_rather_than_pretending(self):
        """A document missing something v2 requires does not validate against
        v2, and that is the honest outcome — the alternative is a default
        nobody can tell from a measurement. What must not happen is the
        migration reporting success for it."""
        document = self._v1()
        del document["max_iterations"]

        target, report = migrate_run(document)

        self.assertFalse(report.is_complete)
        # Lossless and incomplete at once: nothing was dropped, something was
        # never there. They fail for opposite reasons and are separate answers.
        self.assertTrue(report.is_lossless)
        with self.assertRaises(AssertionError):
            self.assert_matches(load("atlas-run.v2.json"), target, "atlas-run.v2")

    def test_a_whole_source_reports_complete(self):
        _, report = migrate_run(self._v1())

        self.assertTrue(report.is_complete)

    def test_more_evaluations_than_iterations_is_recorded_not_smoothed_over(self):
        """A migration that silently repairs its input produces a document that
        cannot be compared with the one it came from."""
        document = self._v1()
        document["evaluations"] = document["evaluations"] * 3
        document["iteration"] = 1

        _, report = migrate_run(document)

        self.assertTrue(report.inconsistent)


class TestNothingIsInvented(unittest.TestCase):
    def _v1(self) -> dict[str, Any]:
        return AtlasController(max_iterations=1).run("hej", json_mode=True)

    def test_actions_is_null_and_never_an_empty_list(self):
        """The sharp case. `[]` states that the run performed no actions, which
        is a claim and a false one: v1 kept no action log at all."""
        target, report = migrate_run(self._v1())

        self.assertIsNone(target["actions"])
        self.assertNotEqual(target["actions"], [])
        self.assertIn("actions", target["migration"]["not_recorded"])
        self.assertEqual(report.not_recorded, NOT_RECORDED_IN_V1)

    def test_a_missing_score_method_becomes_unknown_and_not_todays_method(self):
        """A document old enough to lack the field is old enough to hold the
        *weighted* score. Writing `criteria_met_share` would assert exactly what
        cannot be known."""
        document = self._v1()
        for evaluation in document["evaluations"]:
            evaluation.pop("score_method", None)

        target, _ = migrate_run(document)

        for evaluation in target["evaluations"]:
            self.assertEqual(evaluation["score_method"], "unknown")

    def test_a_recorded_score_method_is_left_alone(self):
        """The positive control. Without it the rule above could be a function
        that overwrites the field."""
        target, _ = migrate_run(self._v1())

        for evaluation in target["evaluations"]:
            self.assertEqual(evaluation["score_method"], "criteria_met_share")

    def test_absent_criteria_lists_are_not_turned_into_empty_ones(self):
        """An empty list says nothing was met. An absent one says nobody
        recorded it. v2 keeps them optional so the two stay different."""
        document = self._v1()
        for evaluation in document["evaluations"]:
            evaluation.pop("met_criteria", None)
            evaluation.pop("unmet_criteria", None)

        target, _ = migrate_run(document)

        for evaluation in target["evaluations"]:
            self.assertNotIn("met_criteria", evaluation)
            self.assertNotIn("unmet_criteria", evaluation)


class TestIdentityBindsTheObjects(unittest.TestCase):
    def test_an_evaluation_gets_the_run_and_the_iteration_it_belongs_to(self):
        document = AtlasController(max_iterations=2).run(
            "granska repo atlas-core", json_mode=True
        )

        target, _ = migrate_run(document)

        for index, evaluation in enumerate(target["evaluations"]):
            with self.subTest(index=index):
                self.assertEqual(evaluation["run_id"], document["run_id"])
                self.assertEqual(evaluation["iteration"], index + 1)

    def test_the_id_is_stable_and_distinguishes_iterations(self):
        document = AtlasController(max_iterations=2).run(
            "granska repo atlas-core", json_mode=True
        )

        first, _ = migrate_run(document)
        again, _ = migrate_run(document)

        ids = [item["evaluation_id"] for item in first["evaluations"]]
        self.assertEqual(ids, [item["evaluation_id"] for item in again["evaluations"]])
        self.assertEqual(len(set(ids)), len(ids))

    def test_two_runs_do_not_share_evaluation_ids(self):
        one, _ = migrate_run(AtlasController(max_iterations=1).run("hej", json_mode=True))
        two, _ = migrate_run(AtlasController(max_iterations=1).run("hej", json_mode=True))

        self.assertNotEqual(
            one["evaluations"][0]["evaluation_id"],
            two["evaluations"][0]["evaluation_id"],
        )

    def test_the_document_says_which_sub_contract_versions_it_carries(self):
        target, _ = migrate_run(
            AtlasController(max_iterations=1).run("hej", json_mode=True)
        )

        self.assertEqual(target["contracts"]["evaluation"], "atlas-evaluation.v2")
        self.assertEqual(target["contracts"]["observation"], "atlas-observation.v1")


class TestApprovalIsRecordedWithoutBeingGranted(SchemaAssertions):
    def test_a_run_that_needed_a_person_gets_a_record_saying_so(self):
        document = AtlasController(max_iterations=1).run("commit till main", json_mode=True)
        self.assertTrue(document["evaluations"][-1]["requires_user_approval"])

        target, _ = migrate_run(document)

        self.assertTrue(target["approvals"])
        record = target["approvals"][0]
        self.assert_matches(load("atlas-approval.v1.json"), record, "atlas-approval.v1")
        self.assertTrue(record["required"])
        self.assertEqual(record["run_id"], document["run_id"])

    def test_nothing_is_granted_because_nothing_can_grant(self):
        """Defining the contract must not create the permission. Atlas Core is
        read-only, the gateway denies every write capability, and no code reads
        this record to allow anything."""
        target, _ = migrate_run(
            AtlasController(max_iterations=1).run("commit till main", json_mode=True)
        )

        for record in target["approvals"]:
            self.assertIsNone(record["granted"])
            self.assertIsNone(record["granted_by"])
            self.assertIsNone(record["binds_to"])

    def test_the_reason_is_derived_where_it_can_be_and_named_where_it_cannot(self):
        derived, _ = migrate_run(
            AtlasController(max_iterations=1).run("commit till main", json_mode=True)
        )
        self.assertEqual(derived["approvals"][0]["reason"], "task_matches_write_keyword")

        # The flag set from somewhere this migration cannot see. A plausible
        # sentence here would be indistinguishable from a recorded one.
        document = AtlasController(max_iterations=1).run("hej", json_mode=True)
        document["evaluations"][0]["requires_user_approval"] = True
        opaque, _ = migrate_run(document)
        self.assertEqual(opaque["approvals"][0]["reason"], "not_recorded")

    def test_no_approval_needed_is_an_empty_list_and_none_at_all_is_null(self):
        """Different statements. One run was graded and needed nobody; the other
        was never graded, so nothing is known either way."""
        graded, _ = migrate_run(
            AtlasController(max_iterations=1).run("hej", json_mode=True)
        )
        self.assertEqual(graded["approvals"], [])

        ungraded = AtlasController(max_iterations=1).run("hej", json_mode=True)
        ungraded["evaluations"] = None
        target, _ = migrate_run(ungraded)
        self.assertIsNone(target["approvals"])

    def test_a_grant_that_names_nothing_is_not_well_formed(self):
        """The rule the contract exists to carry: an approval that does not name
        its subject approves everything, forever."""
        self.assertFalse(approval_is_well_formed({"granted": True}))
        self.assertFalse(approval_is_well_formed({"granted": True, "binds_to": None}))
        self.assertFalse(
            approval_is_well_formed({"granted": True, "binds_to": {"kind": "diff"}})
        )
        self.assertTrue(
            approval_is_well_formed(
                {"granted": True, "binds_to": {"kind": "diff", "sha256": "a" * 64}}
            )
        )

    def test_not_granting_needs_no_subject(self):
        self.assertTrue(approval_is_well_formed({"granted": None}))
        self.assertTrue(approval_is_well_formed({"granted": False}))


class TestASourceThatCannotBeIdentifiedIsRefused(unittest.TestCase):
    def test_an_unknown_schema_raises(self):
        with self.assertRaises(UnknownSourceSchema):
            migrate_run({"schema": "atlas-run.v0"})

    def test_a_document_with_no_schema_raises(self):
        """Every rule in the migration is relative to a source contract — which
        fields are required, known and impossible. Guessing the source from its
        shape would make all three guesses."""
        with self.assertRaises(UnknownSourceSchema):
            migrate_run({"run_id": "x", "task": "y"})

    def test_migrating_a_v2_document_again_raises(self):
        """It would record a migration that did not happen."""
        target, _ = migrate_run(
            AtlasController(max_iterations=1).run("hej", json_mode=True)
        )

        with self.assertRaises(UnknownSourceSchema):
            migrate_run(target)

    def test_the_names_are_what_the_documents_say(self):
        self.assertEqual(SOURCE_SCHEMA, "atlas-run.v1")
        self.assertEqual(TARGET_SCHEMA, "atlas-run.v2")


if __name__ == "__main__":
    unittest.main()
