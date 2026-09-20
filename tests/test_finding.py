"""P0.2a: `Finding.v1` and deterministic verification.

ROADMAP.md P0.2, box one and the deterministic half of box two. The rule the
whole module is built around:

    Om semantisk verifiering inte kan göras: `insufficient_evidence`,
    aldrig `verified` på enbart filnamn.

So this layer is built to be **incapable** of returning `verified`. It can
establish that a finding's evidence pointer is sound — the source was read in
this run, the digest matches, the quoted text really sits at the lines claimed
— and that is not the same as the source supporting the claim. A sound pointer
gets `insufficient_evidence`, and `test_deterministic_checking_can_never_return_verified`
is the structural guarantee rather than a convention anyone has to remember.

What it *can* do is rule out, and box four lists the cases that must:

- a false finding citing a genuinely-read README
- the wrong SHA
- the wrong line range
- a cherry-picked excerpt
- empty sources
- a missing result

Semantic verification — deciding whether an intact source actually supports the
claim — is P0.2b and is not here.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from atlas_core.finding import (
    EvidenceRef,
    EvidenceStatus,
    Finding,
    check_finding,
)
from atlas_core.observation import UNKNOWN
from atlas_core.snapshot import collect_observation, take_snapshot

ROOT = Path(__file__).parents[1]

README = "# Demo repo\n\nEtt litet repo.\nRad fyra.\nRad fem.\n"


class _Run(unittest.TestCase):
    """One snapshot, one observed README — the evidence base for a run."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        self.snapshot = take_snapshot(self.root)
        self.observation = collect_observation(self.snapshot, "README.md")
        self.observations = [self.observation]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ref(self, **overrides: object) -> EvidenceRef:
        fields: dict[str, object] = {
            "source_id": self.observation.source_id,
            "content_sha256": self.observation.content_sha256,
            "line_start": 1,
            "line_end": 3,
            "quoted": "# Demo repo\n\nEtt litet repo.",
        }
        fields.update(overrides)
        return EvidenceRef(**fields)  # type: ignore[arg-type]

    def _finding(self, **overrides: object) -> Finding:
        fields: dict[str, object] = {
            "claim": "README saknar installationssteg.",
            "scope": "README.md",
            "severity": "P1",
            "severity_rationale": "Blockerar en ny användare från att komma igång.",
            "evidence": [self._ref()],
        }
        fields.update(overrides)
        return Finding.create(**fields)  # type: ignore[arg-type]

    def _check(self, finding: Finding):
        return check_finding(finding, self.observations, self.root)


class TestVerifiedIsUnreachable(_Run):
    """The structural guarantee. Everything else is detail."""

    def test_deterministic_checking_can_never_return_verified(self):
        """Not "does not happen to" — cannot.

        Intact evidence proves the pointer is sound, not that the source says
        what the claim says. Granting `verified` here is exactly the
        citation-for-verification substitution P0.2 exists to remove.
        """
        result = self._check(self._finding())

        self.assertEqual(
            [status for _, status in result.statuses], [EvidenceStatus.INTACT]
        )
        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertNotEqual(result.verdict, "verified")

    def test_the_reason_says_what_is_missing(self):
        result = self._check(self._finding())

        self.assertIn("semantic", result.reason)

    def test_a_self_asserted_verdict_is_overruled_not_trusted(self):
        """ROADMAP P0.2: "modellens eget självomdöme får inte ensamt ge PASS."

        A producer that writes `verdict="verified"` onto its own finding has
        asserted, not established. Checking it downgrades the claim rather than
        accepting it, so the field is a record of what a checker found and not
        a place to declare success.
        """
        self_asserted = Finding(
            finding_id="0" * 16,
            claim="README saknar installationssteg.",
            scope="README.md",
            severity="P1",
            severity_rationale="Blockerar onboarding.",
            evidence=[self._ref()],
            verification_method="semantic",
            verdict="verified",
        )

        result = self._check(self_asserted)

        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertEqual(result.apply_to(self_asserted).verdict, "insufficient_evidence")

    def test_no_code_path_constructs_a_verified_verdict(self):
        """The guarantee is structural, so assert it structurally.

        `"verified"` may appear in the type alias and in the comparison inside
        is_supported(). If it ever appears as a constructed value, this layer
        has gained the power the phase exists to deny it.
        """
        import re
        from pathlib import Path as _Path

        source = (_Path(__file__).parents[1] / "atlas_core" / "finding.py").read_text(
            encoding="utf-8"
        )
        constructions = [
            line.strip()
            for line in source.splitlines()
            if re.search(r'(verdict\s*=\s*"verified"|return\s+"verified")', line)
        ]

        self.assertEqual(constructions, [])

    def test_a_finding_starts_unverified(self):
        self.assertEqual(self._finding().verdict, "insufficient_evidence")
        self.assertEqual(self._finding().verification_method, "none")


class TestRulingOut(_Run):
    """Box four: each of these must fail, none may pass."""

    def test_a_false_claim_citing_a_genuinely_read_readme(self):
        """The headline case. Real source, intact pointer, nonsense claim.

        Deterministic checking cannot catch this, and must not pretend to. It
        reports `insufficient_evidence`, never `verified` — the claim is left
        unsupported rather than blessed.
        """
        result = self._check(
            self._finding(claim="README.md bevisar att projektet har 100% testtäckning.")
        )

        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertFalse(result.is_supported())

    def test_an_unknown_source_id_is_contradicted(self):
        result = self._check(self._finding(evidence=[self._ref(source_id="0" * 16)]))

        self.assertEqual(result.verdict, "contradicted")
        self.assertEqual(result.statuses[0][1], EvidenceStatus.UNKNOWN_SOURCE)

    def test_a_wrong_digest_is_contradicted(self):
        result = self._check(self._finding(evidence=[self._ref(content_sha256="b" * 64)]))

        self.assertEqual(result.verdict, "contradicted")
        self.assertEqual(result.statuses[0][1], EvidenceStatus.DIGEST_MISMATCH)

    def test_a_wrong_line_range_is_contradicted(self):
        """The quote is real; the lines it claims are not where it sits."""
        result = self._check(
            self._finding(evidence=[self._ref(line_start=4, line_end=5)])
        )

        self.assertEqual(result.verdict, "contradicted")
        self.assertEqual(result.statuses[0][1], EvidenceStatus.QUOTE_MISMATCH)

    def test_a_cherry_picked_excerpt_is_contradicted(self):
        """Text lifted from the file but not contiguous at the claimed range."""
        result = self._check(
            self._finding(evidence=[self._ref(quoted="# Demo repo\nRad fem.")])
        )

        self.assertEqual(result.verdict, "contradicted")
        self.assertEqual(result.statuses[0][1], EvidenceStatus.QUOTE_MISMATCH)

    def test_a_range_beyond_the_file_is_contradicted(self):
        result = self._check(
            self._finding(evidence=[self._ref(line_start=90, line_end=99)])
        )

        self.assertEqual(result.verdict, "contradicted")

    def test_empty_evidence_is_insufficient_never_verified(self):
        result = self._check(self._finding(evidence=[]))

        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertEqual(result.statuses, [])
        self.assertIn("no evidence", result.reason)

    def test_a_stale_source_is_contradicted(self):
        """The source moved after it was read. It no longer backs anything."""
        finding = self._finding()
        (self.root / "README.md").write_text(README + "ändrad\n", encoding="utf-8")

        result = self._check(finding)

        self.assertEqual(result.verdict, "contradicted")
        self.assertEqual(result.statuses[0][1], EvidenceStatus.STALE_SOURCE)

    def test_a_deleted_source_is_contradicted(self):
        finding = self._finding()
        (self.root / "README.md").unlink()

        self.assertEqual(self._check(finding).verdict, "contradicted")

    def test_one_bad_reference_contradicts_the_whole_finding(self):
        """A finding is only as sound as its weakest citation."""
        result = self._check(
            self._finding(evidence=[self._ref(), self._ref(content_sha256="c" * 64)])
        )

        self.assertEqual(result.verdict, "contradicted")
        self.assertIn(EvidenceStatus.INTACT, [s for _, s in result.statuses])


class TestFindingShape(_Run):
    def test_severity_requires_a_rationale(self):
        with self.assertRaises(ValueError):
            self._finding(severity_rationale="")

    def test_severity_is_closed(self):
        with self.assertRaises(ValueError):
            self._finding(severity="catastrophic")

        for good in ("P0", "P1", "P2", UNKNOWN):
            with self.subTest(severity=good):
                self.assertEqual(self._finding(severity=good).severity, good)

    def test_a_claim_cannot_be_blank(self):
        with self.assertRaises(ValueError):
            self._finding(claim="   ")

    def test_finding_ids_are_unique_per_finding(self):
        self.assertNotEqual(self._finding().finding_id, self._finding(claim="Annat.").finding_id)

    def test_the_reproducible_command_defaults_to_unknown_not_blank(self):
        self.assertEqual(self._finding().reproducible_command, UNKNOWN)

    def test_limitations_are_carried_not_dropped(self):
        finding = self._finding(limitations=["Endast README lästes."])

        self.assertEqual(finding.limitations, ["Endast README lästes."])

    def test_an_evidence_ref_rejects_a_malformed_digest(self):
        with self.assertRaises(ValueError):
            self._ref(content_sha256="inte en digest")

    def test_an_evidence_ref_rejects_a_backwards_range(self):
        with self.assertRaises(ValueError):
            self._ref(line_start=5, line_end=2)


class TestSchema(_Run):
    def setUp(self):
        super().setUp()
        self.schema = json.loads(
            (ROOT / "schemas" / "atlas-finding.v1.json").read_text(encoding="utf-8")
        )

    def test_every_field_is_declared(self):
        self.assertEqual(set(self._finding().to_dict()), set(self.schema["properties"]))

    def test_the_document_is_closed(self):
        self.assertIs(self.schema["additionalProperties"], False)

    def test_the_verdict_enum_matches_the_roadmap(self):
        self.assertEqual(
            sorted(self.schema["properties"]["verdict"]["enum"]),
            ["contradicted", "insufficient_evidence", "verified"],
        )

    def test_the_document_is_json_serialisable(self):
        json.loads(json.dumps(self._finding().to_dict(), ensure_ascii=False))


class TestRecordingAVerdict(_Run):
    """A verdict is attached by a checker, never asserted by the finding itself."""

    def test_the_check_result_can_be_recorded_on_the_finding(self):
        finding = self._finding()
        result = self._check(finding)

        recorded = result.apply_to(finding)

        self.assertEqual(recorded.verdict, "insufficient_evidence")
        self.assertEqual(recorded.verification_method, "deterministic_evidence_check")
        self.assertEqual(recorded.finding_id, finding.finding_id)

    def test_recording_never_upgrades_to_verified(self):
        result = self._check(self._finding())

        self.assertNotEqual(result.apply_to(self._finding()).verdict, "verified")

    def test_a_contradicted_finding_records_why(self):
        finding = self._finding(evidence=[self._ref(content_sha256="d" * 64)])

        recorded = self._check(finding).apply_to(finding)

        self.assertEqual(recorded.verdict, "contradicted")
        self.assertTrue(recorded.limitations)


if __name__ == "__main__":
    unittest.main()
