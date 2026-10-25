"""What a provider is asked to return, and what is done when it does not.

Two halves that are easy to confuse. The **schema** is a request: it goes on
the wire in the field each provider reads (`format` for Ollama, `response_format`
for an OpenAI-compatible endpoint), and asking is not the same as getting. The
**envelope reader** is the local check, which runs on every reply regardless of
whether the schema was sent, honoured, or silently ignored by an endpoint that
merely resembles one that supports it.

**A reply of the wrong shape is not a failed request.** It is a producer that
wrote the wrong thing, and this repository already has a place for that:
`structured_findings` reports a `malformed_findings` gap, the evaluator turns
that into `repair_findings_block`, and the next pass is a restatement — the
producer has everything it needs. Raising here would turn a producer error into
a machine error, spend the run's stop reason on `tool_error`, and lose the one
kind of failure a second pass can actually fix.

The division of labour is deliberate. This module checks the **envelope** —
that the reply is an object with prose and a list of findings — and nothing
about the findings themselves. `atlas_core.evidence` is the authority on what a
finding must look like, it already refuses a producer's self-declared verdict,
and a second validator beside it could only drift.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..evidence import FINDINGS_FENCE, structured_findings

#: Bumped when the envelope changes shape. Recorded on every live result, so a
#: run document says which contract the producer was asked to meet rather than
#: leaving a reader to infer it from the date.
OUTPUT_SCHEMA_VERSION = "atlas-model-output.v1"

#: The machine half, mirroring `schemas/atlas-findings-block.v1.json`. Held in
#: code because `schemas/` is repository documentation and is not packaged, and
#: bound to the file by a test rather than by a runtime read — the file is the
#: contract, and drift between the two is a test failure, not a crash in the
#: field.
#:
#: The descriptions are not decoration. They are the only channel that tells a
#: producer why `typed_claim` and `claim_check` differ, and a provider given the
#: schema is given them too.
_FINDING_ITEM: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["claim", "scope", "severity_rationale", "evidence"],
    "properties": {
        "claim": {
            "type": "string",
            "minLength": 1,
            "description": (
                "The finding, as one sentence. With a typed_claim it must be "
                "exactly the sentence that claim derives, so the reader is not "
                "told more than what was tested."
            ),
        },
        "scope": {"type": "string", "minLength": 1},
        "severity": {
            "type": "string",
            "enum": ["P0", "P1", "P2", "unknown"],
            "description": (
                "What you assess before anything is checked. It survives as "
                "stated only on a verified verdict; otherwise it is recorded "
                "beside the finding as unknown."
            ),
        },
        "severity_rationale": {"type": "string", "minLength": 1},
        "evidence": {
            "type": "array",
            "minItems": 1,
            "description": (
                "What this finding claims about the sources it read. Checked "
                "against the run's observations, not copied from them."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "source_id",
                    "content_sha256",
                    "line_start",
                    "line_end",
                    "quoted",
                ],
                "properties": {
                    "source_id": {"type": "string"},
                    "content_sha256": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                    "line_start": {"type": "integer", "minimum": 1},
                    "line_end": {"type": "integer", "minimum": 1},
                    "quoted": {"type": "string", "minLength": 1},
                },
            },
        },
        "typed_claim": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "source_id", "text"],
            "description": (
                "The only route to a verdict of verified or contradicted, "
                "because settling it settles the claim rather than a separately "
                "chosen test of it. Mutually exclusive with claim_check."
            ),
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["source_contains_literal", "source_lacks_literal"],
                },
                "source_id": {
                    "type": "string",
                    "description": (
                        "A source this finding cites and the run actually read."
                    ),
                },
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Literal text. Not a regular expression.",
                },
            },
        },
        "claim_check": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "source_id", "text"],
            "description": (
                "A free-standing test of a free-text finding. Settling it "
                "settles the test, not the claim, so it can never reach a "
                "verdict. Mutually exclusive with typed_claim."
            ),
            "properties": {
                "kind": {"type": "string", "enum": ["absent", "present"]},
                "source_id": {"type": "string"},
                "text": {"type": "string", "minLength": 1},
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
        "reproducible_command": {"type": "string"},
    },
}


def output_schema() -> dict[str, Any]:
    """The whole reply, as JSON Schema — prose and findings in one object.

    A schema over the reply means the reply is JSON, which the prose half is
    not. So the prose is a string field inside it and this module puts it back
    together as the markdown the rest of the loop reads. The alternative — no
    schema, and an instruction in the prompt asking for a fenced block — is the
    thing that only *looks* like a contract.

    `findings` is required and may be empty. An explicit empty list says the
    producer asserted nothing; an absent one says it forgot, and those are
    different states to a reader of the run document.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["report", "findings"],
        "properties": {
            "report": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "The answer in markdown, with the sections the route asked "
                    "for. Every finding stated here must also appear in "
                    "findings; a bullet with no matching entry is a finding "
                    "nobody can check."
                ),
            },
            "findings": {
                "type": "array",
                "description": (
                    "Empty when you assert nothing. Do not omit it."
                ),
                "items": _FINDING_ITEM,
            },
        },
    }


#: Every field the envelope allows. The schema says `additionalProperties:
#: false`, so a reply carrying anything else did not match the schema that was
#: sent — and the field worth naming is `verdict`, which is a producer
#: declaring its own success.
ENVELOPE_FIELDS = ("report", "findings")


@dataclass(frozen=True)
class ReadEnvelope:
    """What the local check made of a reply.

    `text` is always the output the run will grade — either rebuilt from a
    conforming envelope, or the provider's own text passed through untouched.
    Passing it through is what makes a shape failure repairable: the evaluator
    reads it, finds no usable findings block, and asks for one.

    **Two questions, and they have different answers.** `envelope_conformed`
    decides which `text` the caller gets: the envelope held, so the reply could
    be rebuilt. `conformed` is the narrower claim that the *whole* reply matched
    the schema that was sent, which is false as soon as anything did — an
    unknown top-level field, or an entry `structured_findings` cannot use. A
    reply with a bad entry is still rebuilt, because the evaluator is the one
    that reports it, and is still not conformity.
    """

    text: str
    #: The wrapper held: an object, with both required fields, of the right
    #: types, and nothing else.
    envelope_conformed: bool
    #: Why the reply did not match the schema, in a form a person reading the
    #: run document can act on. `None` exactly when it did.
    reason: str | None = None

    @property
    def conformed(self) -> bool:
        """Whether the reply matched the schema, as far as a local check can
        tell. Not the same as the envelope holding, and this is the one that
        reaches `metadata.output_conformed`."""
        return self.reason is None


def read_envelope(text: str) -> ReadEnvelope:
    """Rebuild the run's output from a reply, conforming or not.

    Never raises and never drops anything. A provider that ignored the schema
    and answered in markdown — including markdown that already carries its own
    `atlas-findings` fence — passes through unchanged, which is the same reply
    this adapter would have produced before a schema was ever sent.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ReadEnvelope(text, False, "reply is not JSON")

    if not isinstance(payload, dict):
        return ReadEnvelope(
            text, False, f"reply is a JSON {type(payload).__name__}, not an object"
        )

    unknown = sorted(set(payload) - set(ENVELOPE_FIELDS))
    if unknown:
        # `additionalProperties: false` was in the schema that was sent, so this
        # reply did not match it. Rejecting the envelope rather than dropping
        # the field is the point: the producer put it there, and silently
        # discarding a `verdict` it wrote would hide the very habit this
        # repository refuses everywhere else.
        return ReadEnvelope(
            text,
            False,
            "reply carries fields the schema does not allow: " + ", ".join(unknown),
        )

    report = payload.get("report")
    findings = payload.get("findings")
    if not isinstance(report, str) or not report.strip():
        return ReadEnvelope(text, False, "reply has no report text")
    if not isinstance(findings, list):
        missing = "findings is missing" if findings is None else "findings is not a list"
        return ReadEnvelope(text, False, f"reply {missing}")

    rendered = render_output(report, findings)
    # Judged by the module that owns the question, on the text it will itself
    # read. Restating the finding rules here would be a second authority that
    # could only drift from the first — and the entries still reach the
    # evaluator, because `rendered` is what the caller gets either way.
    parsed = structured_findings(rendered)
    if parsed.malformed is not None:
        return ReadEnvelope(rendered, True, f"findings are not usable: {parsed.malformed}")

    return ReadEnvelope(rendered, True)


def render_output(report: str, findings: list[Any]) -> str:
    """Prose plus the fenced block the evaluator reads, in that order.

    The findings are re-serialised rather than echoed as received: this module
    does not judge them, and `structured_findings` reads the fence, so what is
    written here is what that reader will parse.
    """
    block = json.dumps(findings, ensure_ascii=False, indent=2)
    return f"{report.rstrip()}\n\n```{FINDINGS_FENCE}\n{block}\n```"
