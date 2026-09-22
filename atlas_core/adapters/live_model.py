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

## What this module deliberately does not do

- It does not bound the prompt, validate structured output, or handle rate
  limits and unknown responses beyond failing. That is P1.2 box two.
- It does not mark its results non-deterministic. That is box three.
- It does not offer the model any tool. The controller passes a gateway when it
  has one; this adapter ignores it, which is the honest state until box four
  declares a capability list.

A timeout is here, and is not scope creep: an HTTP call with no timeout hangs
the loop past the wall-clock bound the run promised to honour.

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

#: Local by default. A daemon that is not running fails the run; it does not
#: quietly become a deterministic answer.
DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"


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
class ProviderConfig:
    """What it takes to reach one provider.

    `api_key` is the only secret here and it stays here: it is used to build a
    header and is never copied into a result, a log line or the run document.
    `describe()` is what anything else may see.
    """

    provider: str
    model: str
    endpoint: str
    api_key: str | None = None
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
        self, config: ProviderConfig, transport: Transport | None = None
    ) -> None:
        self.config = config
        self.transport = transport or UrllibTransport()

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
        prompt = build_prompt(task, route, plan, observations, feedback)
        headers: dict[str, str] = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        try:
            reply = self.transport.post(
                self.config.endpoint,
                self.config.spec.build(self.config, prompt),
                headers,
                self.config.timeout,
            )
        except urllib.error.HTTPError as exc:
            # Status only. A provider body can echo a request header back, and
            # the controller writes this message into the run document.
            raise RuntimeError(
                f"{self.config.provider} returned HTTP {exc.code}"
            ) from None
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"{self.config.provider} could not be reached: {exc.reason}"
            ) from None
        except json.JSONDecodeError:
            raise RuntimeError(
                f"{self.config.provider} returned a body that is not JSON"
            ) from None

        text = self.config.spec.read_text(reply)
        if not text.strip():
            # The controller refuses empty output anyway; saying which provider
            # produced nothing is more use than a generic contract error.
            raise RuntimeError(
                f"{self.config.provider} returned no text for model "
                f"{self.config.model}"
            )

        metadata = {}
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


def build_prompt(
    task: str,
    route: AtlasRoute,
    plan: AtlasPlan,
    observations: list[str],
    feedback: AtlasEvaluation | None = None,
) -> str:
    """Assemble what the producer is told, from what the run already carries.

    Plain text, and everything in it comes from the run document rather than
    from this module's opinions. The feedback section is what makes a second
    pass a replan rather than a rerun, and it is the structured `next_action`
    that goes in — not the prose beside it — because that is the channel the
    rest of this repository treats as the instruction.

    Not bounded. P1.2 box two owns prompt and context limits; until then a
    caller with a large evidence base should set `RunLimits`.
    """
    parts = [
        f"Task: {task}",
        f"Route: {route.name}",
        f"Steps: {', '.join(plan.steps)}",
    ]
    if plan.review is not None:
        parts.append(f"Question: {plan.review.question}")
        if plan.review.patterns:
            parts.append(f"Sources the question needs: {', '.join(plan.review.patterns)}")
    if observations:
        parts.append("Observed sources:\n" + "\n\n".join(observations))
    if feedback is not None:
        if feedback.unmet_criteria:
            parts.append("Unmet criteria: " + ", ".join(feedback.unmet_criteria))
        if feedback.next_action is not None:
            parts.append(
                "Next action: "
                + feedback.next_action.kind
                + " — "
                + json.dumps(feedback.next_action.details, ensure_ascii=False)
            )
    return "\n\n".join(parts)


def build_model_adapter(
    env: dict[str, str] | None = None,
    *,
    transport: Transport | None = None,
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
    )


def model_adapter_or_raise(
    env: dict[str, str] | None = None,
    *,
    transport: Transport | None = None,
) -> LiveModelAdapter:
    """For a caller that asked for a live run and wants to hear about it.

    Same configuration, different answer to the same absence. `build_model_adapter`
    exists for the loop, which has a deterministic path to take; this exists for
    a command that has nothing else to do.
    """
    adapter = build_model_adapter(env, transport=transport)
    if adapter is None:
        raise NotConfigured(
            f"no live provider configured. Set {ENV_PROVIDER} to one of "
            f"{PROVIDERS}, {ENV_MODEL}, and for a hosted provider {ENV_API_KEY}."
        )
    return adapter


__all__ = [
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
    "ProviderConfig",
    "ProviderSpec",
    "SPECS",
    "Transport",
    "UrllibTransport",
    "build_model_adapter",
    "build_prompt",
    "model_adapter_or_raise",
]
