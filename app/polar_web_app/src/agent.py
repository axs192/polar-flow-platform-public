"""The agent layer.

`Agent` is a tiny interface so the rest of the app never depends on a specific
provider. `ClaudeAgent` implements it against the Anthropic API. To swap in a
different backend later, write another `Agent` subclass and return it from
`build_agent()` — `app.py` does not change.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from . import context_store
from .config import Settings, settings
from .tools import run_tool, tool_schemas

logger = logging.getLogger(__name__)

# An "event" streamed back to the caller. Kept as a plain dict so it maps
# cleanly onto Server-Sent Events in the web layer.
#   {"type": "text",  "text": "..."}        incremental answer text
#   {"type": "tool",  "name": "...", ...}   the agent invoked a tool
#   {"type": "done"}                         the turn is complete
#   {"type": "error", "message": "..."}      something went wrong
AgentEvent = dict[str, Any]


# Tools whose results are large enough (the full exercise-metrics JSON) that
# marking them cacheable is worth a breakpoint -- repeated turns in the same
# conversation replay this block from cache instead of paying full price.
_CACHEABLE_TOOL_RESULTS = {"get_my_training_data"}


def _with_cache_breakpoint(message: dict[str, Any]) -> dict[str, Any]:
    """Copy of ``message`` with cache_control on its last content block.

    Anthropic's cache walks backward from the last breakpoint, so marking
    the last block of the previously-appended turn lets each new request
    reuse the *entire* prior conversation prefix from cache, not just the
    system prompt (see shared/prompt-caching.md's "Multi-turn conversations"
    guidance). Without this, replayed history is full-price on every turn --
    directly undermining the token-cost goal this whole persistence design
    exists for, since history is exactly what grows unboundedly over a long
    coaching relationship. No-op if content isn't a block list (e.g. a
    plain-string user turn) -- self-heals on the next assistant turn, which
    always has list content.
    """
    content = message.get("content")
    if not isinstance(content, list) or not content:
        return message
    blocks = [*content[:-1], {**content[-1], "cache_control": {"type": "ephemeral"}}]
    return {**message, "content": blocks}


# Usage fields accumulated across every stream iteration in a turn (a turn
# can involve more than one when the model calls tools) -- matches the
# Anthropic SDK's Usage model fields actually present on Opus/Sonnet
# responses (verified against anthropic.types.Usage.model_fields).
_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _accumulate_usage(total: dict[str, int], usage: Any) -> None:
    """Add one response's token usage onto ``total`` in place.

    Fields are read defensively (``getattr(..., 0) or 0``) since the cache
    fields are ``None`` -- not 0 -- when prompt caching isn't in play for
    that particular response.
    """
    for field in _USAGE_FIELDS:
        total[field] += getattr(usage, field, 0) or 0


def _dump_response_block(block: Any) -> dict[str, Any]:
    """Serialize one SDK response content block for storage/replay as input.

    exclude_none: the installed SDK's response blocks carry response-only
    fields (e.g. a text block's `parsed_output`, used for structured outputs,
    unset/None here since this app never requests them) that aren't present
    in the SDK's static type stubs but *are* present at runtime, and aren't
    valid on request input. Re-sending them verbatim as replayed history
    400s with "Extra inputs are not permitted" on the second turn onward --
    confirmed live against the real Anthropic API, not assumed.
    """
    return block.model_dump(mode="json", exclude_none=True)


class Agent(ABC):
    """Minimal streaming chat agent interface."""

    @abstractmethod
    def stream(
        self,
        question: str,
        *,
        history: list[dict[str, Any]] | None = None,
        extra_system: str | None = None,
        base_system: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Yield AgentEvents as the agent answers ``question``.

        ``history`` is prior conversation turns (already in Anthropic message
        shape) to replay before ``question``. ``extra_system`` is appended to
        the base system prompt for this request only (e.g. onboarding
        instructions, or the athlete's stored profile) -- see
        ``shared/prompt-caching.md``'s guidance on keeping the base system
        prompt frozen and putting per-request context after it. ``base_system``
        overrides the base prompt itself (``context_store.get_system_prompt()``
        by default) -- e.g. the training-plan chat's own agent persona, which
        is a different base entirely, not extra context appended to the
        coach's.
        """
        raise NotImplementedError


class ClaudeAgent(Agent):
    """A Claude-backed agent that streams text and runs registered tools."""

    def __init__(self, config: Settings):
        self.config = config
        # Pass the key explicitly when configured; otherwise let the SDK fall
        # back to ANTHROPIC_API_KEY exported in the environment.
        self.client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    def _thinking_param(self) -> dict[str, Any] | None:
        # Adaptive thinking is the supported mode on current Opus models.
        return {"type": "adaptive"} if self.config.enable_thinking else None

    def _tool_result_content(self, tool_name: str, output: Any) -> Any:
        """Plain JSON string, or a cacheable content-block list for large tools."""
        text = json.dumps(output)
        if tool_name not in _CACHEABLE_TOOL_RESULTS:
            return text
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]

    async def stream(
        self,
        question: str,
        *,
        history: list[dict[str, Any]] | None = None,
        extra_system: str | None = None,
        base_system: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        logger.info("Agent turn starting (model=%s)", self.config.model)
        messages: list[dict[str, Any]] = list(history or [])
        if messages:
            messages[-1] = _with_cache_breakpoint(messages[-1])
        messages.append({"role": "user", "content": question})
        # Track only what this turn adds, so the caller can persist it without
        # re-persisting the history it already had.
        new_messages: list[dict[str, Any]] = [messages[-1]]
        total_usage: dict[str, int] = dict.fromkeys(_USAGE_FIELDS, 0)

        system_text = base_system if base_system is not None else context_store.get_system_prompt()
        if extra_system:
            system_text = f"{system_text}\n\n{extra_system}"

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            "tools": tool_schemas(),
        }
        thinking = self._thinking_param()
        if thinking is not None:
            kwargs["thinking"] = thinking

        try:
            # Manual agentic loop: stream a turn, run any tools the model asked
            # for, feed the results back, and repeat until it stops calling tools.
            while True:
                async with self.client.messages.stream(messages=messages, **kwargs) as stream:
                    async for text in stream.text_stream:
                        yield {"type": "text", "text": text}
                    final = await stream.get_final_message()

                _accumulate_usage(total_usage, final.usage)

                assistant_turn = {
                    "role": "assistant",
                    "content": [_dump_response_block(block) for block in final.content],
                }
                messages.append(assistant_turn)
                new_messages.append(assistant_turn)

                if final.stop_reason != "tool_use":
                    break

                tool_results: list[dict[str, Any]] = []
                for block in final.content:
                    if block.type != "tool_use":
                        continue
                    logger.info("Agent calling tool %s input=%s", block.name, block.input)
                    yield {"type": "tool", "name": block.name, "input": block.input}
                    output = run_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": self._tool_result_content(block.name, output),
                        }
                    )
                tool_turn = {"role": "user", "content": tool_results}
                messages.append(tool_turn)
                new_messages.append(tool_turn)

            logger.info("Agent turn complete")
            yield {"type": "done", "new_messages": new_messages, "usage": total_usage}
        except anthropic.APIError as exc:  # surface a clean message to the UI
            logger.exception("Anthropic API error during agent turn")
            yield {"type": "error", "message": f"Anthropic API error: {exc}"}
        except Exception as exc:  # noqa: BLE001 - last-resort guard for the stream
            logger.exception("Unexpected error during agent turn")
            yield {"type": "error", "message": str(exc)}


def build_agent() -> Agent:
    """Construct the configured agent. Single place to swap implementations."""
    return ClaudeAgent(settings)
