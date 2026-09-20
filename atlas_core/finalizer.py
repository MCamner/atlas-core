from __future__ import annotations
from typing import Any, Literal, overload

from .state import AtlasRunState


@overload
def finalize(state: AtlasRunState, json_mode: Literal[False] = ...) -> str: ...


@overload
def finalize(state: AtlasRunState, json_mode: Literal[True]) -> dict[str, Any]: ...


@overload
def finalize(state: AtlasRunState, json_mode: bool) -> str | dict[str, Any]: ...


def finalize(state: AtlasRunState, json_mode: bool = False) -> str | dict[str, Any]:
    run = state.to_dict()
    return run if json_mode else render_run_text(run)


#: How a claim is labelled in the ledger. Fixed width so the column lines up
#: and the category is the first thing the eye lands on.
FACT = "FACT      "
REFUTED = "REFUTED   "
HYPOTHESIS = "HYPOTHESIS"

#: Bounded so one long claim cannot push the ledger off a terminal. The full
#: text is in the run document.
MAX_LEDGER_CLAIM = 100


def render_run_text(run: dict[str, Any]) -> str:
    """Render an `atlas-run.v1` document as the text a human reads.

    The text trailer is a rendering of the run document, not a second source of
    truth. Anything a caller needs to branch on is in the document; parsing this
    prose to find it is what the API contract tells adapters not to do.

    The trailer carries a **claim ledger** because the body cannot be trusted
    to separate what was established from what was guessed. A producer writes
    its findings as bullets, and a verified claim and a hypothesis look
    identical there:

        - README.md lines 1-5 contain "pip install"
        - README.md är förmodligen svår att följa för nybörjare.

    Nothing in that text tells a reader which one was settled against a source.
    The ledger is derived from the run document, where the two *are* separate,
    and it says so per claim. Recommendations are listed apart from both: they
    are advice, and advice is not a finding about the repository however well
    supported the findings beside it were.
    """
    outputs = run.get("outputs") or []
    evaluations = run.get("evaluations") or []
    route = run.get("route") or {}
    latest_output = outputs[-1] if outputs else "No output."
    latest_eval = evaluations[-1] if evaluations else None
    meta = [
        f"Atlas route: {route.get('name') or 'unknown'}",
        f"Iterations: {run.get('iteration', 0)}/{run.get('max_iterations', 0)}",
        f"Stop reason: {run.get('stop_reason') or 'unknown'}",
    ]
    if latest_eval:
        meta.append(f"Quality score: {latest_eval['quality_score']}")
        meta.append(f"Status: {'passed' if latest_eval['passed'] else 'provisional'}")
        if latest_eval.get("evidence_gaps"):
            meta.append("Evidence gaps: " + ", ".join(latest_eval["evidence_gaps"]))
        if latest_eval["requires_user_approval"]:
            meta.append("Write approval required before any mutation.")
    ledger = _claim_ledger(run)
    if run.get("stop_reason") == "failed":
        failure = (run.get("metadata") or {}).get("failure") or {}
        meta.append(
            f"Failure: {failure.get('stage', 'unknown')} raised "
            f"{failure.get('error', 'an error')}."
        )
    return latest_output.rstrip() + "\n\n---\n" + "\n".join(meta + ledger) + "\n"


def _claim_ledger(run: dict[str, Any]) -> list[str]:
    """Say, per claim, which of the three kinds it is.

    Empty for a run that made no claims, rather than a heading over nothing.
    """
    evaluations = run.get("evaluations") or []
    if not evaluations:
        return []
    latest = evaluations[-1]

    rows: list[str] = []
    labelled: set[str] = set()
    for record in latest.get("citation_checks") or []:
        claim = str(record.get("claim", ""))
        labelled.add(claim)
        verdict = record.get("verdict")
        if verdict == "verified":
            label = FACT
        elif verdict == "contradicted":
            label = REFUTED
        else:
            # Sound citations and a settled condition both land here. Neither
            # establishes the claim, and the ledger must not imply they did.
            label = HYPOTHESIS
        rows.append(f"  {label}  {_clip(claim)}")

    # Claims the checker never saw: prose findings with no machine-readable
    # citation. They are the ones most at risk of reading as established, so
    # leaving them out of the ledger would defeat its purpose.
    for claim in latest.get("unverified_claims") or []:
        if str(claim) not in labelled:
            rows.append(f"  {HYPOTHESIS}  {_clip(str(claim))}")

    if not rows:
        return []

    return [
        "",
        "Claim ledger (from the run document, not from the text above):",
        *rows,
        "  FACT is settled against observed lines. REFUTED means the source says",
        "  otherwise. HYPOTHESIS was not established, whatever the text implies.",
        "  Recommendations are advice, not findings, and are not listed here.",
    ]


def _clip(claim: str) -> str:
    claim = " ".join(claim.split())
    if len(claim) <= MAX_LEDGER_CLAIM:
        return claim
    return claim[: MAX_LEDGER_CLAIM - 1] + "…"
