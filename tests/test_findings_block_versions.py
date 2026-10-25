"""`atlas-findings-block.v1` keeps the `v1.0.0` shape; the relation claim is v2.

#128 added `command_targets_differ` to `typed_claim.kind` inside v1. The
contract allows only optional additive properties within a schema identifier,
and `kind` is required inside `typed_claim`, so a consumer validating against
the `v1.0.0` copy rejects such a finding. The relation therefore travels in its
own fence, `atlas-findings.v2`, which a v1 reader does not match.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any
import unittest

from atlas_core.adapters.output_contract import _FINDING_ITEM
from atlas_core.claim_check import ClaimKind
from atlas_core.evidence import FINDINGS_FENCE, FINDINGS_FENCE_V2, structured_findings


SCHEMAS = Path(__file__).parents[1] / "schemas"
LITERAL_KINDS = ["source_contains_literal", "source_lacks_literal"]


def load(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def relation_finding() -> dict[str, Any]:
    return {
        "claim": 'command "ruff" targets differ',
        "scope": "release-check.sh <-> .github/workflows/tests.yml",
        "severity_rationale": "Deterministic relation.",
        "evidence": [
            {
                "source_id": "a" * 16,
                "content_sha256": "a" * 64,
                "line_start": 1,
                "line_end": 1,
                "quoted": "ruff check src tests",
            }
        ],
        "typed_claim": {
            "kind": "command_targets_differ",
            "source_id": "a" * 16,
            "text": "ruff",
            "other_source_id": "b" * 16,
            "source_targets": ["src", "tests"],
            "other_targets": ["src"],
        },
    }


def block(fence: str, findings: list[dict[str, Any]]) -> str:
    return "# Report\n\n```" + fence + "\n" + json.dumps(findings) + "\n```\n"


class TestTheSchemas(unittest.TestCase):
    def test_v1_typed_claim_is_the_v1_0_0_shape(self) -> None:
        typed = load("atlas-findings-block.v1.json")["items"]["properties"]["typed_claim"]

        self.assertEqual(typed["properties"]["kind"]["enum"], LITERAL_KINDS)
        self.assertEqual(sorted(typed["properties"]), ["kind", "source_id", "text"])

    def test_v2_adds_only_the_relation(self) -> None:
        v1 = load("atlas-findings-block.v1.json")
        v2 = load("atlas-findings-block.v2.json")
        typed = v2["items"]["properties"]["typed_claim"]

        self.assertEqual(v2["$id"], "atlas-findings-block.v2.json")
        self.assertEqual(
            typed["properties"]["kind"]["enum"],
            LITERAL_KINDS + ["command_targets_differ"],
        )
        self.assertEqual(
            sorted(set(typed["properties"]) - {"kind", "source_id", "text"}),
            ["other_source_id", "other_targets", "source_targets"],
        )
        self.assertEqual(
            {k: v for k, v in v1["items"]["properties"].items() if k != "typed_claim"},
            {k: v for k, v in v2["items"]["properties"].items() if k != "typed_claim"},
        )
        self.assertEqual(v1["items"]["required"], v2["items"]["required"])

    def test_the_model_is_offered_only_the_literal_kinds(self) -> None:
        """The relation is produced by deterministic code, never by a model."""
        typed = _FINDING_ITEM["properties"]["typed_claim"]

        self.assertEqual(typed["properties"]["kind"]["enum"], LITERAL_KINDS)
        self.assertNotIn("other_source_id", typed["properties"])


class TestTheFences(unittest.TestCase):
    def test_a_v1_block_refuses_the_relation(self) -> None:
        parsed = structured_findings(block(FINDINGS_FENCE, [relation_finding()]))

        self.assertTrue(parsed.present)
        self.assertIn(FINDINGS_FENCE_V2, parsed.malformed or "")

    def test_a_v2_block_carries_the_relation(self) -> None:
        parsed = structured_findings(block(FINDINGS_FENCE_V2, [relation_finding()]))

        self.assertIsNone(parsed.malformed)
        self.assertEqual(len(parsed.entries), 1)
        typed = parsed.entries[0][1]
        assert typed is not None
        self.assertIs(typed.kind, ClaimKind.COMMAND_TARGETS_DIFFER)

    def test_a_v1_reader_does_not_match_a_v2_block(self) -> None:
        """The pattern `atlas_core/evidence.py` used at `v1.0.0`."""
        v1_reader = re.compile(
            r"^```" + "atlas-findings" + r"\s*\n(.*?)\n^```", re.DOTALL | re.MULTILINE
        )

        self.assertIsNone(v1_reader.search(block(FINDINGS_FENCE_V2, [relation_finding()])))
        self.assertIsNotNone(v1_reader.search(block(FINDINGS_FENCE, [])))


if __name__ == "__main__":
    unittest.main()
