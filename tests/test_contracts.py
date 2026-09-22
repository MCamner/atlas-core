"""v1.3 box one: the versioned contracts, and the table that says who owns what.

Two things are asserted here and neither is about behaviour.

**The schema files and the Python view of them must not drift.** This is the
rule P1.2 arrived at the hard way, applied to the whole contract set rather than
to one schema: a description in a file that no test reads is a description that
stops being true without anything failing. So the ownership table must cover
every property each schema declares, the required-field lists this package holds
in code must match the files, and a successor version must actually be one.

**A producer must not own a field that decides its own success.** That rule has
been enforced case by case since P0.2 — in `evidence.py`, in `finding.py`, in
the findings-block schema. `FIELD_OWNERS` writes it down once, and this suite is
what makes writing it down worth more than a comment.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from atlas_core.contracts import (
    CONTRACTS,
    Contract,
    OWNERS,
    RUN_V2_CONTRACTS,
    owner_of,
    predecessor_of,
)
from atlas_core.migrate import V1_REQUIRED

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"


def load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


class TestEveryContractHasAFileThatMatchesIt(unittest.TestCase):
    def test_the_schema_file_exists_and_declares_its_own_id(self):
        for contract_id, contract in CONTRACTS.items():
            with self.subTest(contract=contract_id):
                path = SCHEMA_DIR / contract.schema_file
                self.assertTrue(path.is_file(), f"{contract.schema_file} is missing")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["$id"],
                                 contract.schema_file)

    def test_the_file_name_follows_from_the_contract_name_and_version(self):
        """So `Run.v2` cannot quietly be defined by `atlas-run.v1.json`."""
        for contract_id, contract in CONTRACTS.items():
            with self.subTest(contract=contract_id):
                self.assertEqual(contract.schema_file, contract.schema_id)

    def test_the_document_declares_the_version_it_is(self):
        """Every one of these carries a `schema` const, so a document taken out
        of context still says which contract it answers to."""
        for contract_id, contract in CONTRACTS.items():
            with self.subTest(contract=contract_id):
                schema = load(contract.schema_file)
                const = schema["properties"]["schema"]["const"]
                self.assertEqual(const, contract.schema_file.removesuffix(".json"))


class TestOwnershipIsDeclaredForEveryField(unittest.TestCase):
    def test_no_property_is_left_without_an_owner(self):
        """A field nobody claimed is a hole. Failing here is the point: adding a
        property to a schema and forgetting to say who writes it should not
        default to permissive."""
        for contract_id, contract in CONTRACTS.items():
            schema = load(contract.schema_file)
            for name in schema.get("properties", {}):
                with self.subTest(contract=contract_id, property=name):
                    self.assertIn(name, contract.owners)

    def test_no_owner_is_declared_for_a_property_that_does_not_exist(self):
        """The other direction. A stale entry would describe a field that is
        gone, which reads as coverage and is not."""
        for contract_id, contract in CONTRACTS.items():
            declared = set(load(contract.schema_file).get("properties", {}))
            with self.subTest(contract=contract_id):
                self.assertEqual(set(contract.owners) - declared, set())

    def test_every_owner_is_from_the_vocabulary(self):
        for contract_id, contract in CONTRACTS.items():
            for name, owner in contract.owners.items():
                with self.subTest(contract=contract_id, property=name):
                    self.assertIn(owner, OWNERS)

    def test_an_unowned_field_raises_rather_than_answering(self):
        with self.assertRaises(KeyError):
            owner_of("Finding.v1", "no_such_field")


class TestAProducerCannotOwnItsOwnVerdict(unittest.TestCase):
    """The rule the whole evidence model rests on, stated against the table."""

    def test_the_fields_that_decide_a_finding_belong_to_the_checker(self):
        for name in ("verdict", "verification_method", "severity"):
            with self.subTest(field=name):
                self.assertEqual(owner_of("Finding.v1", name), "checker")

    def test_identity_is_derived_and_not_supplied(self):
        """A producer that could choose `finding_id` could make two findings one,
        or one two."""
        self.assertEqual(owner_of("Finding.v1", "finding_id"), "derived")
        self.assertEqual(owner_of("Evaluation.v2", "evaluation_id"), "derived")
        self.assertEqual(owner_of("Observation.v1", "source_id"), "derived")

    def test_what_a_producer_may_send_never_names_an_assigned_field(self):
        """Against the block a producer actually fills in, not against prose.
        `test_claim_check.py` asserts this from the other end; here it is tied to
        the ownership table, so the two cannot drift apart."""
        block = load("atlas-findings-block.v1.json")
        producer_keys = set(block["items"]["properties"])

        for name in ("verdict", "verification_method", "finding_id"):
            with self.subTest(field=name):
                self.assertEqual(owner_of("Finding.v1", name), "checker" if name != "finding_id" else "derived")
                self.assertNotIn(name, producer_keys)

    def test_every_block_field_that_reaches_a_finding_is_the_producers(self):
        """Two of the block's fields do not appear on `Finding.v1` at all:
        `typed_claim` and `claim_check` are inputs to the check, consumed into
        `citation_checks` on the evaluation rather than stored beside the
        finding. Naming them here keeps that a stated fact rather than a gap."""
        block = load("atlas-findings-block.v1.json")
        consumed_by_the_check = {"typed_claim", "claim_check"}
        finding_fields = set(CONTRACTS["Finding.v1"].owners)

        for name in set(block["items"]["properties"]) - consumed_by_the_check:
            with self.subTest(field=name):
                if name == "severity":
                    # The pointed exception. What a producer declares is kept as
                    # `declared_severity`; `severity` is what survived the check,
                    # and survives as declared only on a verified verdict.
                    self.assertEqual(owner_of("Finding.v1", "declared_severity"), "producer")
                    self.assertEqual(owner_of("Finding.v1", "severity"), "checker")
                    continue
                self.assertIn(name, finding_fields)
                self.assertEqual(owner_of("Finding.v1", name), "producer")

        for name in consumed_by_the_check:
            with self.subTest(field=name):
                self.assertNotIn(name, finding_fields)

    def test_the_grading_of_an_answer_is_never_the_producers(self):
        evaluation = CONTRACTS["Evaluation.v2"]
        self.assertNotIn("producer", set(evaluation.owners.values()))

    def test_approval_is_never_the_producers_and_a_grant_is_only_a_hosts(self):
        """A producer that could set `required` to false would be waiving the
        requirement to ask; one that could set `granted` would be answering."""
        self.assertEqual(owner_of("Approval.v1", "required"), "core")
        for name in ("granted", "granted_by", "granted_at", "binds_to"):
            with self.subTest(field=name):
                self.assertEqual(owner_of("Approval.v1", name), "host")

    def test_an_action_log_is_the_cores_alone(self):
        """An action log a producer could write would be a log of what it said
        it did."""
        action = CONTRACTS["Action.v1"]
        self.assertEqual(set(action.owners.values()) - {"core", "derived"}, set())


class TestASuccessorIsActuallyOne(unittest.TestCase):
    """The compatibility rule, made mechanical. A version bump is allowed to add
    requirements; it is not allowed to lose a field and say nothing."""

    def _successors(self) -> list[tuple[str, str, Contract]]:
        """Each successor with the predecessor id already narrowed to `str`, so
        the assertions below read as assertions rather than as None-handling."""
        return [
            (contract_id, contract.succeeds, contract)
            for contract_id, contract in CONTRACTS.items()
            if contract.succeeds is not None
        ]

    def test_there_is_at_least_one_successor_to_check(self):
        self.assertTrue(self._successors())

    def test_every_field_the_predecessor_had_is_still_there(self):
        for contract_id, succeeds, contract in self._successors():
            older = load(_predecessor_file(succeeds))
            newer = load(contract.schema_file)
            lost = set(older.get("properties", {})) - set(newer.get("properties", {}))
            with self.subTest(contract=contract_id):
                self.assertEqual(
                    lost - set(contract.dropped),
                    set(),
                    "a field vanished without being declared dropped",
                )

    def test_every_field_the_predecessor_required_is_still_required(self):
        """Adding a requirement is allowed across a version. Dropping one
        silently is what turns a consumer's working code into wrong code."""
        for contract_id, succeeds, contract in self._successors():
            older = load(_predecessor_file(succeeds))
            newer = load(contract.schema_file)
            relaxed = set(older.get("required", [])) - set(newer.get("required", []))
            with self.subTest(contract=contract_id):
                self.assertEqual(relaxed - set(contract.dropped), set())

    def test_a_dropped_field_carries_a_reason(self):
        for contract_id, contract in CONTRACTS.items():
            for name, reason in contract.dropped.items():
                with self.subTest(contract=contract_id, field=name):
                    self.assertTrue(reason.strip())

    def test_predecessor_of_reports_what_the_table_says(self):
        self.assertEqual(predecessor_of("Run.v2"), "Run.v1")
        self.assertEqual(predecessor_of("Evaluation.v2"), "Evaluation.v1")
        self.assertIsNone(predecessor_of("Action.v1"))


def _predecessor_file(contract_id: str) -> str:
    name, version = contract_id.rsplit(".v", 1)
    return f"atlas-{name.lower()}.v{version}.json"


class TestTheCodeAndTheFilesAgreeOnWhatV1Required(unittest.TestCase):
    """`atlas_core.migrate` holds v1's required list in code, because `schemas/`
    is documentation and is not packaged — a runtime read would work in the
    repository and fail in an installed wheel. That makes drift possible, so it
    is a test failure here rather than a migration that misses a field."""

    def test_the_required_list_matches_the_file(self):
        filed = load("atlas-run.v1.json")["required"]

        self.assertEqual(sorted(V1_REQUIRED), sorted(filed))


class TestTheRunDeclaresWhichSubContractsItCarries(unittest.TestCase):
    def test_each_named_version_has_a_schema_file(self):
        for role, schema_id in RUN_V2_CONTRACTS.items():
            with self.subTest(role=role):
                self.assertTrue((SCHEMA_DIR / f"{schema_id}.json").is_file())

    def test_the_versions_it_names_are_the_ones_this_package_defines(self):
        """So the document cannot advertise a version the code does not hold."""
        defined = {contract.schema_file.removesuffix(".json")
                   for contract in CONTRACTS.values()}
        for role in ("observation", "finding", "evaluation", "action", "approval"):
            with self.subTest(role=role):
                self.assertIn(RUN_V2_CONTRACTS[role], defined)


if __name__ == "__main__":
    unittest.main()
