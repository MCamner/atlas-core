"""P1.2 box one: a real provider behind the `ModelAdapter` that already exists.

Everything in this repository so far has been graded against a scripted or
deterministic producer. That was the right order — a gate you cannot trust is
not worth pointing at a model — but it means nothing here has yet talked to
one.

## The rule that shapes this module

> Saknad nyckel får inte bryta deterministic fallback.

A missing key must not break the deterministic fallback, and the controller
already refuses to fall back *at call time*: a provider that raises is
`tool_error`, on purpose, because answering with the rule-based executor and
labelling it a model result would report an answer nobody asked for. Those two
rules only fit together in one place — **configuration time**.

`build_model_adapter()` therefore returns `None` when nothing is configured.
The caller passes that straight to `AtlasController`, which runs its
deterministic path because it has no adapter, exactly as it does today. Nothing
is caught, nothing is swallowed, and a run that *was* configured still fails
loudly when the provider does.

## Two shapes, configured separately

`ollama` talks to a local daemon and needs no key. `openai_compatible` posts to
a chat-completions endpoint and needs one. They differ only in how a request is
built and where the text sits in the reply, so they are two `ProviderSpec`
values rather than two classes.

## Bounds and failures (box two, request side)

The prompt is bounded in characters, not tokens: counting tokens needs a
tokenizer per provider, which is a dependency this package does not have and a
number that would be wrong for every provider it was not built for. `RunBudget`
keeps the token side, against counts a provider reports about its own work.

Nothing is dropped quietly. When the bound bites, the prompt says so in the
text the producer reads and the adapter counts it on the result — the two
readers need different things, and "found nothing" means less when the producer
was shown less. The instruction itself is never cut, so a bound that cannot
hold it is refused rather than exceeded.

Failures are named through the exception type, which the controller already
writes into `metadata.failure.error`. None of them retry: a retry here would
spend wall-clock the `RunBudget` cannot see, and the loop already owns whether
another attempt is worth it.

## What this module deliberately does not do

- It does not validate structured output against a schema, or tell a provider
  what shape to produce. That is the rest of box two.
- It does not mark its results non-deterministic. That is box three.
- It does not offer the model any tool. The controller passes a gateway when it
  has one; this adapter ignores it, which is the honest state until box four
  declares a capability list.

## Secrets

The key is read from the environment, held on the config, and never leaves it.
It is not in `ModelResult.metadata`, not in the run document, and not in the
failure record the controller writes — `redaction` masks the document on the
way out, and this module gives it nothing to mask.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from atlas_core.state import AtlasEvaluation, AtlasPlan, AtlasRoute

from .model import ModelResult

#: Providers this module knows how to speak to.
PROVIDERS: tuple[str, ...] = ("ollama", "openai_compatible")

#: Where each provider's configuration is read from, when a caller states
#: nothing. Named per provider so two can be configured side by side without
#: one silently picking up the other's endpoint.
ENV_PROVIDER = "ATLAS_MODEL_PROVIDER"
ENV_MODEL = "ATLAS_MODEL"
ENV_ENDPOINT = "ATLAS_MODEL_ENDPOINT"
ENV_API_KEY = "ATLAS_MODEL_API_KEY"
ENV_TIMEOUT = "ATLAS_MODEL_TIMEOUT"

DEFAULT_TIMEOUT = 60.0

#: How much of a run may be put in front of a producer, in characters.
#:
#: Characters, not tokens, and the difference is the point: counting tokens
#: needs a tokenizer per provider, which is a dependency this package does not
#: have and a number that would be wrong for every provider it was not built
#: for. A character bound is crude, is the same for everyone, and can be
#: checked. `RunBudget` keeps the token side, against the counts a provider
#: reports about its own work.
DEFAULT_MAX_PROMPT_CHARS = 24_000
#: Per observation, so one enormous source cannot crowd out every other one.
DEFAULT_MAX_OBSERVATION_CHARS = 4_000

#: Local by default. A daemon that is not running fails the run; it does not
#: quietly become a deterministic answer.
DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"


class ProviderError(RuntimeError):
    """A request to a provider that did not produce usable text.

    Subclassed per kind rather than carrying a code, because the controller
    already records `type(exc).__name__` in `metadata.failure.error`. A caller
    reading a run document can therefore tell a rate limit from an unreachable
    daemon without this module changing the controller or the run schema.

    None of them retry. A retry inside the adapter would spend wall-clock time
    the `RunBudget` cannot see and cannot charge, and the loop already owns the
    decision about whether another attempt is worth it — see `RETRY_CLASSES`.
    What this layer owes is a name for what happened.
    """


class ProviderRateLimited(ProviderError):
    """The provider refused this request because too many were sent.

    `retry_after` is the provider's own hint in seconds when it gave one, and
    `None` when it did not — not a default, for the reason every other absent
    value in this repository is `unknown` rather than plausible.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderTimeout(ProviderError):
    """The call passed the configured timeout without a reply."""


class ProviderUnreachable(ProviderError):
    """The endpoint could not be reached at all."""


class ProviderRefused(ProviderError):
    """The provider answered with a status that is not success."""


class ProviderBadResponse(ProviderError):
    """The provider answered, and the answer is not one this adapter can read.

    A body that is not JSON, or JSON with no text where this provider's shape
    says text lives. Distinct from `ProviderRefused` because the request was
    accepted: something is wrong with the contract, not with the call.
    """


class NotConfigured(Exception):
    """Raised by `model_adapter_or_raise`, never by `build_model_adapter`.

    Two entry points because there are two honest answers to "no configuration
    present". A caller that wants the deterministic fallback wants `None`; a
    caller that asked for a live run and got none wants to hear about it.
    """


class Transport(Protocol):
    """One HTTP POST, so tests need no network and no monkeypatching."""

    def post(
        self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ProviderSpec:
    """How to build a request for one provider and read its reply."""

    name: str
    #: Whether a key is required. Ollama is local and needs none; a hosted
    #: endpoint does, and this is what makes "missing key" a configuration
    #: state rather than a request failure.
    needs_key: bool
    default_endpoint: str | None
    build: Callable[["ProviderConfig", str], dict[str, Any]]
    read_text: Callable[[dict[str, Any]], str]
    read_tokens: Callable[[dict[str, Any]], int | None]


def _ollama_request(config: ProviderConfig, prompt: str) -> dict[str, Any]:
    return {"model": config.model, "prompt": prompt, "stream": False}


def _ollama_text(reply: dict[str, Any]) -> str:
    return str(reply.get("response", ""))


def _ollama_tokens(reply: dict[str, Any]) -> int | None:
    counted = [
        reply.get("prompt_eval_count"),
        reply.get("eval_count"),
    ]
    numbers = [value for value in counted if isinstance(value, int)]
    return sum(numbers) if numbers else None


def _openai_request(config: ProviderConfig, prompt: str) -> dict[str, Any]:
    return {
        "model": config.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }


def _openai_text(reply: dict[str, Any]) -> str:
    choices = reply.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    return str(message.get("content", ""))


def _openai_tokens(reply: dict[str, Any]) -> int | None:
    usage = reply.get("usage")
    if isinstance(usage, dict) and isinstance(usage.get("total_tokens"), int):
        return int(usage["total_tokens"])
    return None


SPECS: dict[str, ProviderSpec] = {
    "ollama": ProviderSpec(
        name="ollama",
        needs_key=False,
        default_endpoint=DEFAULT_OLLAMA_ENDPOINT,
        build=_ollama_request,
        read_text=_ollama_text,
        read_tokens=_ollama_tokens,
    ),
    "openai_compatible": ProviderSpec(
        name="openai_compatible",
        needs_key=True,
        default_endpoint=None,
        build=_openai_request,
        read_text=_openai_text,
        read_tokens=_openai_tokens,
    ),
}


@dataclass(frozen=True)
class PromptLimits:
    """What a producer may be shown, and what happens when there is more.

    Nothing is dropped quietly. When the bound bites, the prompt says so in the
    text the producer reads *and* the adapter records it on the result, because
    the two readers are different: a model that knows it was shown part of a
    source can say so, and a person reading the run document needs to know that
    "found nothing" was said about less than the run holds.

    That is the same rule `Observation.read_in_full` follows one layer down. A
    partial view is not a defect; a partial view presented as a whole one is.
    """

    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS
    max_observation_chars: int = DEFAULT_MAX_OBSERVATION_CHARS

    def __post_init__(self) -> None:
        if self.max_prompt_chars < 1 or self.max_observation_chars < 1:
            raise ValueError("prompt limits must be positive")
        if self.max_observation_chars > self.max_prompt_chars:
            raise ValueError(
                "a single observation may not be allowed more than the whole "
                f"prompt: {self.max_observation_chars} > {self.max_prompt_chars}"
            )


@dataclass(frozen=True)
class BoundedPrompt:
    """The text a producer is shown, and what it did not get to see."""

    text: str
    #: Observations whose text was cut, by path-ish label and by how much.
    truncated_observations: int = 0
    #: Observations left out entirely because the prompt bound was reached.
    omitted_observations: int = 0

    def is_complete(self) -> bool:
        return not self.truncated_observations and not self.omitted_observations

    def describe(self) -> dict[str, str]:
        """What goes on the result, so the run document carries it too."""
        return {
            "prompt_chars": str(len(self.text)),
            "prompt_complete": "true" if self.is_complete() else "false",
            "observations_truncated": str(self.truncated_observations),
            "observations_omitted": str(self.omitted_observations),
        }


@dataclass(frozen=True)
class ProviderConfig:
    """What it takes to reach one provider.

    `api_key` is the only secret here and it stays here: it is used to build a
    header and is never copied into a result, a log line or the run document.
    `describe()` is what anything else may see, and the field is kept out of
    the dataclass `repr` — a value that is careful everywhere it is *passed*
    still escapes through the traceback of an unrelated failure.
    """

    provider: str
    model: str
    endpoint: str
    #: `repr=False`, because a dataclass repr is not a place a secret survives
    #: being careful elsewhere. It is what a traceback prints, what a debugger
    #: shows and what lands in a log line written by code that never thought
    #: about this field — none of which pass through `describe()`.
    api_key: str | None = field(default=None, repr=False)
    timeout: float = DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        if self.provider not in SPECS:
            raise ValueError(
                f"provider must be one of {PROVIDERS}, got {self.provider!r}"
            )
        if not self.model.strip():
            raise ValueError("a provider config names a model")
        if not self.endpoint.strip():
            raise ValueError("a provider config names an endpoint")
        if self.timeout <= 0:
            raise ValueError(
                f"timeout must be positive, got {self.timeout}; a call with no "
                "bound hangs the loop past the deadline the run promised"
            )
        if SPECS[self.provider].needs_key and not (self.api_key or "").strip():
            raise ValueError(
                f"{self.provider} requires an API key. Build the config through "
                "build_model_adapter(), which returns None when none is set, so "
                "a run without a key falls back deterministically instead of "
                "failing here."
            )

    @property
    def spec(self) -> ProviderSpec:
        return SPECS[self.provider]

    def describe(self) -> dict[str, str]:
        """Everything about this configuration that is safe to record."""
        return {"provider": self.provider, "model": self.model}


class UrllibTransport:
    """The default transport. Standard library, because this package has no
    runtime dependencies and a provider is not a reason to acquire one."""

    def post(
        self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        return json.loads(body)


class LiveModelAdapter:
    """A real provider behind the contract the controller already calls.

    Raises on every failure. The controller turns that into `tool_error` and
    stops, which is the behaviour this repository chose before any provider
    existed: a run that asked for a model and did not get one must not report a
    deterministic answer as though a model had written it.
    """

    def __init__(
        self,
        config: ProviderConfig,
        transport: Transport | None = None,
        limits: PromptLimits | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or UrllibTransport()
        self.limits = limits or PromptLimits()

    def execute(
        self,
        *,
        task: str,
        route: AtlasRoute,
        plan: AtlasPlan,
        observations: list[str],
        feedback: AtlasEvaluation | None = None,
        **_ignored: Any,
    ) -> ModelResult:
        # `**_ignored` on purpose: the controller passes `budget` and `tools`
        # when it has them. This adapter offers the model no tool, which is the
        # honest state until P1.2 box four declares a capability list — and
        # silently accepting a gateway it does not use is better than crashing
        # on a keyword the contract allows.
        prompt = build_prompt(
            task, route, plan, observations, feedback, self.limits
        )
        headers: dict[str, str] = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        try:
            reply = self.transport.post(
                self.config.endpoint,
                self.config.spec.build(self.config, prompt.text),
                headers,
                self.config.timeout,
            )
        except urllib.error.HTTPError as exc:
            # Status only, never the body. A provider can echo a request header
            # back in an error payload, and the controller writes this message
            # into the run document.
            if exc.code == 429:
                raise ProviderRateLimited(
                    f"{self.config.provider} rate limited this request",
                    _retry_after(exc),
                ) from None
            raise ProviderRefused(
                f"{self.config.provider} returned HTTP {exc.code}"
            ) from None
        except urllib.error.URLError as exc:
            # A timeout arrives wrapped in URLError from urlopen, so the reason
            # is what distinguishes it — not the exception type.
            if isinstance(exc.reason, TimeoutError):
                raise ProviderTimeout(
                    f"{self.config.provider} did not answer within "
                    f"{self.config.timeout:g}s"
                ) from None
            raise ProviderUnreachable(
                f"{self.config.provider} could not be reached: {exc.reason}"
            ) from None
        except TimeoutError:
            raise ProviderTimeout(
                f"{self.config.provider} did not answer within "
                f"{self.config.timeout:g}s"
            ) from None
        except json.JSONDecodeError:
            raise ProviderBadResponse(
                f"{self.config.provider} returned a body that is not JSON"
            ) from None

        if not isinstance(reply, dict):
            raise ProviderBadResponse(
                f"{self.config.provider} returned {type(reply).__name__}, not an "
                "object this adapter can read"
            )

        text = self.config.spec.read_text(reply)
        if not text.strip():
            # The controller refuses empty output anyway; saying which provider
            # produced nothing, and that the call itself succeeded, is more use
            # than a generic contract error.
            raise ProviderBadResponse(
                f"{self.config.provider} answered with no text for model "
                f"{self.config.model}"
            )

        # What the producer was shown, alongside what it said. A run whose
        # answer is "nothing found" is a different statement depending on
        # whether the producer saw every source the run holds.
        metadata = prompt.describe()
        tokens = self.config.spec.read_tokens(reply)
        if tokens is not None:
            # The name the budget reads. Without it a live run is unmetered
            # while a scripted one is not.
            metadata["usage_tokens"] = str(tokens)

        return ModelResult(
            output=text,
            provider=self.config.provider,
            model=self.config.model,
            metadata=metadata,
        )


def _retry_after(error: urllib.error.HTTPError) -> float | None:
    """The provider's own hint, or `None` when it gave none.

    Not a default. An invented number here would be indistinguishable from one
    the provider actually sent, which is the distinction every other absent
    value in this repository keeps.
    """
    raw = ""
    headers = getattr(error, "headers", None)
    if headers is not None:
        raw = str(headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        # The header also allows an HTTP date. Reading that is not worth a
        # dependency, and a wrong number is worse than no number.
        return None


_OBSERVED_HEADING = "Observed sources:"
#: Below this, a truncated source is a stub with a notice attached, which is
#: noise a producer has to reason around rather than evidence it can use.
_MIN_USEFUL_OBSERVATION = 200


def _cut_notice(full: int, kept: int) -> str:
    return (
        f"\n[... {full - kept} of {full} characters of this source are not "
        "shown; anything said about it is about the part above]"
    )


def _omission_notice(count: int) -> str:
    return (
        f"{count} further observed source(s) did not fit in this prompt and "
        "are not shown. Any conclusion here is about what is above."
    )


def build_prompt(
    task: str,
    route: AtlasRoute,
    plan: AtlasPlan,
    observations: list[str],
    feedback: AtlasEvaluation | None = None,
    limits: PromptLimits | None = None,
) -> BoundedPrompt:
    """Assemble what the producer is told, from what the run already carries.

    Plain text, and everything in it comes from the run document rather than
    from this module's opinions. The feedback section is what makes a second
    pass a replan rather than a rerun, and it is the structured `next_action`
    that goes in — not the prose beside it — because that is the channel the
    rest of this repository treats as the instruction.

    **Bounded, and never silently.** The task, the route, the question and the
    feedback are always included: they are what the run is, they are small, and
    a producer shown a truncated instruction would be answering a different
    question. Observations are what can grow without limit, so they are what
    gives way — truncated per source first, then dropped whole — and every cut
    is stated in the prompt and counted on the result.

    Order matters when the bound bites. Observations are kept in the order the
    run holds them, which is the order the host returned them, and what is
    shown is always a *prefix* of that order: the first source that cannot be
    shown ends the selection, and the rest are counted as omitted. A skipped
    source in the middle would be an arbitrary subset described by a notice
    that names no source at all.
    """
    limits = limits or PromptLimits()
    head = [
        f"Task: {task}",
        f"Route: {route.name}",
        f"Steps: {', '.join(plan.steps)}",
    ]
    if plan.review is not None:
        head.append(f"Question: {plan.review.question}")
        if plan.review.patterns:
            head.append(
                f"Sources the question needs: {', '.join(plan.review.patterns)}"
            )

    tail: list[str] = []
    if feedback is not None:
        if feedback.unmet_criteria:
            tail.append("Unmet criteria: " + ", ".join(feedback.unmet_criteria))
        if feedback.next_action is not None:
            tail.append(
                "Next action: "
                + feedback.next_action.kind
                + " — "
                + json.dumps(feedback.next_action.details, ensure_ascii=False)
            )

    # Reserved up front, at its longest — the count can be at most every
    # observation. Adding it afterwards is how an earlier version exceeded the
    # bound it had just been given.
    reserve = len(_omission_notice(len(observations))) + 2 if observations else 0
    fixed = len("\n\n".join(head + tail)) + len(_OBSERVED_HEADING) + 4 + reserve
    if fixed > limits.max_prompt_chars:
        # The instruction is never cut: a producer shown a truncated task is
        # answering a different question. So a bound that cannot hold the task,
        # the question and the feedback is a bound nobody can honour, and
        # saying so beats quietly exceeding it.
        raise ValueError(
            f"max_prompt_chars={limits.max_prompt_chars} cannot hold this run's "
            f"instruction, which needs {fixed} characters before any source is "
            "shown"
        )
    room = limits.max_prompt_chars - fixed
    kept: list[str] = []
    truncated = 0
    omitted = 0
    for index, observation in enumerate(observations):
        if room <= 0:
            omitted = len(observations) - index
            break
        allowed = min(limits.max_observation_chars, room)
        if len(observation) > allowed:
            # The notice costs characters too, and reserving them afterwards is
            # how the first version overshot its own bound. Reserved against the
            # longest the notice can be — the digit count grows as less is
            # kept — so the total is under the limit rather than near it.
            reserved = len(_cut_notice(len(observation), 0))
            usable = allowed - reserved
            # Only worth keeping if a usable amount survives. A stub with a
            # notice attached is noise a producer has to reason around.
            #
            # This ends the selection rather than skipping to the next source.
            # Skipping would leave a shorter later source shown while an earlier
            # one was not, and the omission notice names no source — it means
            # something only if what is shown is the first N in run order.
            if usable < _MIN_USEFUL_OBSERVATION:
                omitted = len(observations) - index
                break
            text = observation[:usable] + _cut_notice(len(observation), usable)
            truncated += 1
        else:
            text = observation
        kept.append(text)
        room -= len(text) + 2

    body = list(head)
    if kept:
        body.append(_OBSERVED_HEADING + "\n" + "\n\n".join(kept))
    if omitted:
        # In the prompt, not only on the result: the producer is the one whose
        # "I found nothing" would otherwise read as a statement about the repo.
        body.append(_omission_notice(omitted))
    body.extend(tail)
    return BoundedPrompt(
        text="\n\n".join(body),
        truncated_observations=truncated,
        omitted_observations=omitted,
    )


def build_model_adapter(
    env: dict[str, str] | None = None,
    *,
    transport: Transport | None = None,
    limits: PromptLimits | None = None,
) -> LiveModelAdapter | None:
    """The configured adapter, or `None` when nothing is configured.

    `None` is not an error and not a fallback performed here: it is the absence
    of an adapter, which is what `AtlasController` has always taken to mean
    "use the deterministic executor". That is how "a missing key must not break
    the deterministic fallback" and "a provider that fails is `tool_error`"
    hold at the same time — the first is a configuration state, the second is a
    request outcome, and they never meet.

    Returns `None` when no provider is named, when a named provider has no
    model, or when one that needs a key has none. It raises only for a
    configuration that is *stated and wrong*: an unknown provider name, a
    non-numeric timeout. Saying nothing about those would leave a caller who
    made a typo silently running the deterministic path.
    """
    values = dict(os.environ if env is None else env)
    provider = (values.get(ENV_PROVIDER) or "").strip()
    if not provider:
        return None
    if provider not in SPECS:
        raise ValueError(
            f"{ENV_PROVIDER} must be one of {PROVIDERS}, got {provider!r}"
        )
    spec = SPECS[provider]

    model = (values.get(ENV_MODEL) or "").strip()
    if not model:
        return None

    endpoint = (values.get(ENV_ENDPOINT) or "").strip() or (spec.default_endpoint or "")
    if not endpoint:
        return None

    api_key = (values.get(ENV_API_KEY) or "").strip() or None
    if spec.needs_key and not api_key:
        return None

    raw_timeout = (values.get(ENV_TIMEOUT) or "").strip()
    if raw_timeout:
        try:
            timeout = float(raw_timeout)
        except ValueError:
            raise ValueError(
                f"{ENV_TIMEOUT} must be a number of seconds, got {raw_timeout!r}"
            ) from None
    else:
        timeout = DEFAULT_TIMEOUT

    return LiveModelAdapter(
        ProviderConfig(
            provider=provider,
            model=model,
            endpoint=endpoint,
            api_key=api_key,
            timeout=timeout,
        ),
        transport=transport,
        limits=limits,
    )


def model_adapter_or_raise(
    env: dict[str, str] | None = None,
    *,
    transport: Transport | None = None,
    limits: PromptLimits | None = None,
) -> LiveModelAdapter:
    """For a caller that asked for a live run and wants to hear about it.

    Same configuration, different answer to the same absence. `build_model_adapter`
    exists for the loop, which has a deterministic path to take; this exists for
    a command that has nothing else to do.
    """
    adapter = build_model_adapter(env, transport=transport, limits=limits)
    if adapter is None:
        raise NotConfigured(
            f"no live provider configured. Set {ENV_PROVIDER} to one of "
            f"{PROVIDERS}, {ENV_MODEL}, and for a hosted provider {ENV_API_KEY}."
        )
    return adapter


__all__ = [
    "BoundedPrompt",
    "DEFAULT_MAX_OBSERVATION_CHARS",
    "DEFAULT_MAX_PROMPT_CHARS",
    "DEFAULT_OLLAMA_ENDPOINT",
    "DEFAULT_TIMEOUT",
    "ENV_API_KEY",
    "ENV_ENDPOINT",
    "ENV_MODEL",
    "ENV_PROVIDER",
    "ENV_TIMEOUT",
    "PROVIDERS",
    "LiveModelAdapter",
    "NotConfigured",
    "PromptLimits",
    "ProviderBadResponse",
    "ProviderConfig",
    "ProviderError",
    "ProviderRateLimited",
    "ProviderRefused",
    "ProviderSpec",
    "ProviderTimeout",
    "ProviderUnreachable",
    "SPECS",
    "Transport",
    "UrllibTransport",
    "build_model_adapter",
    "build_prompt",
    "model_adapter_or_raise",
]
