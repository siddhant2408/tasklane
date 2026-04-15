from __future__ import annotations
"""
run_lane_agent(spec) — the shared agentic loop.

This is a direct port of the my-agents pattern with three additions:
  1. RunLogger tees every iteration to file + DB + pubsub.
  2. cancel_flag cooperative cancellation (checked each iteration).
  3. MAX_ITERATIONS cap + budget guard.

The three unbreakable message-protocol rules (from my-agents/structure/03_agentic_loop.md):
  1. Always append the full response.content (not just text) as the assistant turn.
  2. All tool results go in ONE user message (two consecutive user messages = 400 error).
  3. tool_use_id in each result must exactly match block.id.
"""

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any

import anthropic

from tasklane.agents.tools import build_tool_definitions, execute_tool
from tasklane.core.enums import LogLevel
from tasklane.core.logger import RunLogger

# Soft token budget per run before we warn the agent to wrap up
_BUDGET_WARN_TOKENS = 150_000
_BUDGET_HARD_TOKENS = 200_000


@dataclass
class AgentSpec:
    """Everything needed to run one lane agent."""
    run_id: int
    ticket_id: int
    lane: str
    system_prompt: str          # ticket description + lane suffix
    first_user_message: str     # "Begin work on this ticket..."
    tools: list[str]            # allowed tool names
    workspace_root: str         # absolute path
    model: str
    max_iterations: int
    cancel_flag: threading.Event = field(default_factory=threading.Event)


def run_lane_agent(spec: AgentSpec) -> str:
    """
    Run the agentic loop for one lane transition.
    Returns the agent's final report string.
    Raises on unrecoverable error (caller handles and marks run status).
    """
    logger = RunLogger(spec.run_id)
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    tool_defs = build_tool_definitions(spec.tools)

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": spec.first_user_message}
    ]

    logger.info(f"Starting | lane={spec.lane} model={spec.model} max_iters={spec.max_iterations}")
    logger.info(f"Workspace: {spec.workspace_root}")
    logger.info(f"Tools: {', '.join(spec.tools)}")

    iteration = 0
    total_input_tokens = 0
    total_output_tokens = 0
    budget_warned = False

    while True:
        # -----------------------------------------------------------------------
        # Cooperative cancel check
        # -----------------------------------------------------------------------
        if spec.cancel_flag.is_set():
            logger.warn("Cancel requested — stopping before iteration.")
            return "(run cancelled)"

        iteration += 1
        if iteration > spec.max_iterations:
            logger.warn(f"MAX_ITERATIONS ({spec.max_iterations}) reached — stopping.")
            raise RuntimeError(f"iteration_exceeded after {spec.max_iterations} iterations")

        logger.info(f"--- Iteration {iteration}/{spec.max_iterations} ---")

        # -----------------------------------------------------------------------
        # API call (with basic retry on transient errors)
        # -----------------------------------------------------------------------
        response = _call_api_with_retry(
            client, spec.model, spec.system_prompt, tool_defs, messages, logger
        )

        # Track tokens
        if response.usage:
            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens
            logger.info(
                f"Tokens: +{response.usage.input_tokens}in / +{response.usage.output_tokens}out "
                f"(total {total_input_tokens}in / {total_output_tokens}out)"
            )

        # Budget warning
        if not budget_warned and total_input_tokens > _BUDGET_WARN_TOKENS:
            budget_warned = True
            logger.warn(f"Token budget warning: {total_input_tokens} input tokens used. Wrapping up soon.")

        if total_input_tokens > _BUDGET_HARD_TOKENS:
            logger.warn("Hard token budget exceeded — injecting wrap-up message.")
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": "Token budget exceeded. Stop all further tool calls and produce your final report now."
            })
            # One more API call to get the final report
            final_response = _call_api_with_retry(
                client, spec.model, spec.system_prompt, tool_defs, messages, logger
            )
            final_text = next(
                (b.text for b in final_response.content if b.type == "text"),
                "(budget exceeded — no final report produced)"
            )
            raise RuntimeError("budget_exceeded")

        logger.info(f"stop_reason={response.stop_reason!r}")

        # -----------------------------------------------------------------------
        # END TURN — extract and return final report
        # -----------------------------------------------------------------------
        if response.stop_reason == "end_turn":
            final = next(
                (b.text for b in response.content if b.type == "text"),
                "(no text response)"
            )
            logger.assistant_text(final)
            logger.info("Agent finished — end_turn.")
            return final

        # -----------------------------------------------------------------------
        # TOOL USE — execute all requested tools, collect results, loop back
        # -----------------------------------------------------------------------
        if response.stop_reason == "tool_use":

            # Rule 1: append the FULL response.content as assistant turn
            messages.append({
                "role": "assistant",
                "content": response.content,
            })

            tool_results = []

            for block in response.content:
                if block.type != "tool_use":
                    continue

                input_preview = json.dumps(block.input)[:200]
                logger.tool_use(block.name, input_preview)

                # Cancel check between tool executions
                if spec.cancel_flag.is_set():
                    logger.warn("Cancel requested mid-tool-batch — stopping.")
                    return "(run cancelled)"

                result = execute_tool(
                    block.name, block.input, spec.workspace_root, spec.tools
                )

                result_preview = result[:500].replace("\n", " ")
                logger.tool_result(block.name, result_preview)

                # Rule 3: tool_use_id must match block.id exactly
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            # Rule 2: all tool results in ONE user message
            messages.append({
                "role": "user",
                "content": tool_results,
            })

            continue  # back to top → send updated history to Claude

        # -----------------------------------------------------------------------
        # Unexpected stop reason
        # -----------------------------------------------------------------------
        logger.warn(f"Unexpected stop_reason: {response.stop_reason!r}")
        raise RuntimeError(f"stopped_{response.stop_reason}")


def _call_api_with_retry(
    client: anthropic.Anthropic,
    model: str,
    system_prompt: str,
    tool_defs: list[dict],
    messages: list[dict],
    logger: RunLogger,
    retries: int = 3,
) -> Any:
    import time

    last_exc = None
    for attempt in range(retries):
        try:
            return client.messages.create(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                tools=tool_defs,
                messages=messages,
            )
        except anthropic.APIStatusError as e:
            if e.status_code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                wait = 2 ** attempt
                logger.warn(f"API error {e.status_code} — retrying in {wait}s (attempt {attempt + 1}/{retries})")
                time.sleep(wait)
                last_exc = e
            else:
                raise
        except Exception as e:
            raise

    raise last_exc  # type: ignore
