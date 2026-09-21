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

import dataclasses
import json
import os
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
from atlas_core.observation import UNKNOWN, Observation
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

    def test_no_code_path_constructs_a_contradicted_verdict_either(self):
        """`contradicted` belongs to the semantic layer, not to this one.

        Disproving a claim needs someone to read the source and disagree with
        it. A deterministic checker that hands out refutations for broken
        pointers would be making exactly the category error this phase removes,
        in the opposite direction.
        """
        import re
        from pathlib import Path as _Path

        source = (_Path(__file__).parents[1] / "atlas_core" / "finding.py").read_text(
            encoding="utf-8"
        )
        constructions = [
            line.strip()
            for line in source.splitlines()
            if re.search(r'(verdict\s*=\s*"contradicted"|return\s+"contradicted")', line)
        ]

        self.assertEqual(constructions, [])

    def test_a_broken_citation_is_distinguishable_without_abusing_the_verdict(self):
        """Consumers still need to tell the two failures apart."""
        broken = self._check(self._finding(evidence=[self._ref(content_sha256="f" * 64)]))
        unchecked = self._check(self._finding())

        self.assertEqual(broken.verdict, unchecked.verdict)
        self.assertFalse(broken.citations_are_sound())
        self.assertTrue(unchecked.citations_are_sound())
        self.assertIn("unusable", broken.reason)
        self.assertIn("semantic", unchecked.reason)

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


class TestBrokenCitationsAreNotRefutations(_Run):
    """Box four: each of these must fail — and fail as the right kind.

    An unusable citation says the *pointer* is broken, not that the claim is
    false. A correct finding can cite its source badly. So none of these earn
    `contradicted`: that word is reserved for a claim the semantic layer has
    actually disproved, and spending it here would let a typo read as a
    refutation.

    The discrimination consumers need lives in `citations_are_sound()` and in
    the per-citation statuses, not in the verdict.
    """

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

    def test_an_unknown_source_id_is_not_sound(self):
        result = self._check(self._finding(evidence=[self._ref(source_id="0" * 16)]))

        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertEqual(result.statuses[0][1], EvidenceStatus.UNKNOWN_SOURCE)
        self.assertFalse(result.citations_are_sound())

    def test_a_wrong_digest_is_not_sound(self):
        result = self._check(self._finding(evidence=[self._ref(content_sha256="b" * 64)]))

        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertEqual(result.statuses[0][1], EvidenceStatus.DIGEST_MISMATCH)
        self.assertFalse(result.citations_are_sound())

    def test_a_wrong_line_range_is_not_sound(self):
        """The quote is real; the lines it claims are not where it sits."""
        result = self._check(
            self._finding(evidence=[self._ref(line_start=4, line_end=5)])
        )

        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertEqual(result.statuses[0][1], EvidenceStatus.QUOTE_MISMATCH)
        self.assertFalse(result.citations_are_sound())

    def test_a_cherry_picked_excerpt_is_not_sound(self):
        """Text lifted from the file but not contiguous at the claimed range."""
        result = self._check(
            self._finding(evidence=[self._ref(quoted="# Demo repo\nRad fem.")])
        )

        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertEqual(result.statuses[0][1], EvidenceStatus.QUOTE_MISMATCH)
        self.assertFalse(result.citations_are_sound())

    def test_a_range_beyond_the_file_is_not_sound(self):
        result = self._check(
            self._finding(evidence=[self._ref(line_start=90, line_end=99)])
        )

        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertFalse(result.citations_are_sound())

    def test_empty_evidence_is_insufficient_never_verified(self):
        result = self._check(self._finding(evidence=[]))

        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertEqual(result.statuses, [])
        self.assertIn("no evidence", result.reason)

    def test_a_stale_source_is_not_sound(self):
        """The source moved after it was read. It no longer backs anything."""
        finding = self._finding()
        (self.root / "README.md").write_text(README + "ändrad\n", encoding="utf-8")

        result = self._check(finding)

        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertEqual(result.statuses[0][1], EvidenceStatus.STALE_SOURCE)
        self.assertFalse(result.citations_are_sound())

    def test_a_deleted_source_is_not_sound(self):
        finding = self._finding()
        (self.root / "README.md").unlink()

        result = self._check(finding)
        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertFalse(result.citations_are_sound())

    def test_one_bad_reference_contradicts_the_whole_finding(self):
        """A finding is only as sound as its weakest citation."""
        result = self._check(
            self._finding(evidence=[self._ref(), self._ref(content_sha256="c" * 64)])
        )

        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertFalse(result.citations_are_sound())
        self.assertIn(EvidenceStatus.INTACT, [s for _, s in result.statuses])


class TestUnsupportedSourceTypes(_Run):
    """A source this checker cannot verify must not be checked as a local file."""

    def test_a_non_local_source_is_not_read_off_the_local_disk(self):
        """A github_file or ci source may share a path with a local file.

        Reading it locally would confirm the wrong artifact. Until an adapter
        can establish that source's provenance, the honest answer is that this
        checker cannot say.
        """
        for source_type in ("github_file", "ci", "memory"):
            with self.subTest(source_type=source_type):
                # Built, not replaced: source_id is derived from the type, and
                # Observation refuses a mismatch — the guard from P0.1a.
                foreign = Observation.create(
                    source_type=source_type,
                    path=self.observation.path,
                    collected_at=self.observation.collected_at,
                    content_sha256=self.observation.content_sha256,
                    excerpt=self.observation.excerpt,
                    line_start=self.observation.line_start,
                    line_end=self.observation.line_end,
                    snapshot_id=self.observation.snapshot_id,
                )
                result = check_finding(
                    self._finding(
                        evidence=[self._ref(source_id=foreign.source_id)]
                    ),
                    [foreign],
                    self.root,
                )

                self.assertEqual(result.verdict, "insufficient_evidence")
                self.assertEqual(
                    result.statuses[0][1], EvidenceStatus.UNSUPPORTED_SOURCE_TYPE
                )
                self.assertFalse(result.citations_are_sound())

    def test_local_files_remain_checkable(self):
        self.assertTrue(self._check(self._finding()).citations_are_sound())


class TestTheReadIsSingleAndContained(_Run):
    """Review point 2: one verified read, checked at the read itself.

    The checker used to call `verify_observation` — which reads — and then open
    the file again for the quote. Two reads leave a window in which the file
    can change between them, so the digest would describe content the quote was
    never compared against.
    """

    def _count_reads(self, finding):
        """Count opens, not `read_text`.

        The read goes through `integrity.read_within`, which opens a descriptor
        with `O_NOFOLLOW` instead of calling `Path.read_text`. Counting the old
        call would count zero and pass for the wrong reason.
        """
        original = os.open
        reads: list[str] = []

        def counting(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if str(path).endswith("README.md"):
                reads.append(str(path))
            return original(path, *args, **kwargs)

        os.open = counting  # type: ignore[assignment]
        try:
            result = check_finding(finding, self.observations, self.root)
        finally:
            os.open = original  # type: ignore[assignment]
        return result, reads

    def test_a_citation_is_checked_with_exactly_one_read(self):
        result, reads = self._count_reads(self._finding())

        self.assertEqual(len(reads), 1, f"expected one read, got {len(reads)}")
        self.assertTrue(result.citations_are_sound())

    def test_the_same_bytes_back_both_the_digest_and_the_quote(self):
        """Freshness and the quote are decided from one read, not two."""
        result = self._check(self._finding())

        self.assertEqual(result.statuses[0][1], EvidenceStatus.INTACT)

    def test_an_observation_cannot_record_a_path_that_escapes_the_snapshot(self):
        """The escape is refused at the record, which is earlier than the read.

        `Observation.path` used to be a plain string that accepted `../` and
        absolute forms, and every reader had to defend itself against one. It
        is now refused at construction, so the record cannot exist. The read
        still refuses too — see the symlink case below, where a legal name
        becomes an escape after it was recorded.
        """
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "hemlig.md").write_text("hemligt\n", encoding="utf-8")

        with self.assertRaises(ValueError):
            Observation.create(
                source_type="local_file",
                path=f"../{outside.name}/hemlig.md",
                collected_at=self.observation.collected_at,
                content_sha256=self.observation.content_sha256,
                excerpt="hemligt",
                line_start=1,
                line_end=1,
                snapshot_id=self.observation.snapshot_id,
            )

    def test_an_absolute_observation_path_is_refused(self):
        with self.assertRaises(ValueError):
            Observation.create(
                source_type="local_file",
                path="/etc/passwd",
                collected_at=self.observation.collected_at,
                content_sha256=self.observation.content_sha256,
                excerpt="root",
                line_start=1,
                line_end=1,
                snapshot_id=self.observation.snapshot_id,
            )

    @unittest.skipUnless(os.name != "nt", "symlinks unavailable")
    def test_a_symlinked_observation_path_pointing_outside_is_refused(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "hemlig.md").write_text("hemligt\n", encoding="utf-8")
        (self.root / "alias.md").symlink_to(outside / "hemlig.md")

        linked = Observation.create(
            source_type="local_file",
            path="alias.md",
            collected_at=self.observation.collected_at,
            content_sha256=self.observation.content_sha256,
            excerpt="hemligt",
            line_start=1,
            line_end=1,
            snapshot_id=self.observation.snapshot_id,
        )
        result = check_finding(
            self._finding(
                evidence=[
                    # Within the observation's own line range, so the path
                    # check is what this test exercises — the range check is a
                    # pure comparison and runs first, before any read.
                    self._ref(
                        source_id=linked.source_id,
                        line_start=1,
                        line_end=1,
                        quoted="hemligt",
                    )
                ]
            ),
            [linked],
            self.root,
        )

        self.assertEqual(result.statuses[0][1], EvidenceStatus.PATH_REFUSED)

    def test_a_source_changed_before_the_read_is_stale_not_intact(self):
        """The single read still has to confirm freshness itself."""
        finding = self._finding()
        (self.root / "README.md").write_text(README + "ändrad\n", encoding="utf-8")

        result = self._check(finding)

        self.assertEqual(result.statuses[0][1], EvidenceStatus.STALE_SOURCE)


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

    def test_a_finding_with_unusable_citations_records_why(self):
        finding = self._finding(evidence=[self._ref(content_sha256="d" * 64)])

        recorded = self._check(finding).apply_to(finding)

        self.assertEqual(recorded.verdict, "insufficient_evidence")
        self.assertIn("unusable", recorded.limitations[-1])


if __name__ == "__main__":
    unittest.main()


class TestTheObservationMustStillMatchItself(_Run):
    """Review point 2a: the digest is not the only thing that can have drifted.

    Folding the freshness check and the quote check into one read dropped the
    excerpt check `verify_observation` had been doing. An unchanged file then
    made an observation `intact` even when the excerpt it exported had never
    been what sits at the lines it names — so a manifest could show a reader
    one thing while the checker approved another.
    """

    def _with_excerpt(self, excerpt: str) -> Observation:
        return dataclasses.replace(self.observation, excerpt=excerpt)

    def test_an_excerpt_that_is_not_at_its_line_range_is_refused(self):
        lying = self._with_excerpt("# Demo repo\n\nHELT PÅHITTAT")

        result = check_finding(self._finding(), [lying], self.root)

        self.assertEqual(result.statuses[0][1], EvidenceStatus.EXCERPT_MISMATCH)
        self.assertFalse(result.citations_are_sound())

    def test_the_file_being_unchanged_does_not_rescue_a_lying_excerpt(self):
        """The digest still matches. That is the whole point of the case."""
        lying = self._with_excerpt("något helt annat")

        result = check_finding(self._finding(), [lying], self.root)

        self.assertEqual(lying.content_sha256, self.observation.content_sha256)
        self.assertNotEqual(result.statuses[0][1], EvidenceStatus.STALE_SOURCE)
        self.assertEqual(result.statuses[0][1], EvidenceStatus.EXCERPT_MISMATCH)

    def test_an_honest_excerpt_is_still_intact(self):
        """Negative control: the check must not refuse everything."""
        result = self._check(self._finding())

        self.assertEqual(result.statuses[0][1], EvidenceStatus.INTACT)


class TestACitationMayOnlyCiteWhatWasObserved(_Run):
    """Review point 2b: an accurate quote of lines nobody read is not evidence.

    An excerpt is bounded. A finding can quote a later part of the file
    perfectly — matching text, matching digest — while no observation covers
    those lines. That is a citation standing in for an observation that was
    never made, which is the substitution this phase exists to remove.
    """

    def setUp(self):
        super().setUp()
        # Three lines observed out of five. Lines four and five are real text
        # in the file that this run never recorded.
        self.bounded = collect_observation(self.snapshot, "README.md", max_lines=3)
        self.observations = [self.bounded]

    def _cite(self, line_start: int, line_end: int, quoted: str):
        ref = self._ref(
            source_id=self.bounded.source_id,
            line_start=line_start,
            line_end=line_end,
            quoted=quoted,
        )
        return check_finding(self._finding(evidence=[ref]), self.observations, self.root)

    def test_a_correct_quote_beyond_the_excerpt_is_refused(self):
        self.assertEqual((self.bounded.line_start, self.bounded.line_end), (1, 3))

        result = self._cite(4, 5, "Rad fyra.\nRad fem.")

        self.assertEqual(result.statuses[0][1], EvidenceStatus.QUOTE_OUTSIDE_EXCERPT)
        self.assertFalse(result.citations_are_sound())

    def test_the_refusal_is_not_a_quote_mismatch(self):
        """The text is genuinely there. What is missing is the observation."""
        actual = "\n".join(README.splitlines()[3:5])

        result = self._cite(4, 5, actual)

        self.assertEqual(actual, "Rad fyra.\nRad fem.")
        self.assertNotEqual(result.statuses[0][1], EvidenceStatus.QUOTE_MISMATCH)
        self.assertEqual(result.statuses[0][1], EvidenceStatus.QUOTE_OUTSIDE_EXCERPT)

    def test_a_range_that_straddles_the_end_of_the_excerpt_is_refused(self):
        result = self._cite(3, 4, "Ett litet repo.\nRad fyra.")

        self.assertEqual(result.statuses[0][1], EvidenceStatus.QUOTE_OUTSIDE_EXCERPT)

    def test_the_excerpt_boundary_itself_is_still_citable(self):
        """Negative control: the rule is `outside`, not `not at the start`."""
        result = self._cite(1, 3, "# Demo repo\n\nEtt litet repo.")

        self.assertEqual(result.statuses[0][1], EvidenceStatus.INTACT)

    def test_a_wrong_quote_inside_the_excerpt_is_still_a_quote_mismatch(self):
        """The new check must not swallow the one it sits in front of."""
        result = self._cite(1, 3, "# Demo repo\n\nfel text")

        self.assertEqual(result.statuses[0][1], EvidenceStatus.QUOTE_MISMATCH)
