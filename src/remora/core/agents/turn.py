"""Turn execution pipeline for actor-triggered agent turns."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiosqlite
from structured_agents import Message

from remora.core.agents.kernel import create_kernel, extract_response_text, run_kernel
from remora.core.agents.outbox import Outbox, OutboxObserver
from remora.core.agents.prompt import PromptBuilder
from remora.core.agents.trigger import Trigger, TriggerPolicy
from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentStartEvent,
    TurnDigestedEvent,
)
from remora.core.events.store import EventStore
from remora.core.model.config import BundleConfig, Config
from remora.core.model.errors import (
    IncompatibleBundleError,
    ModelError,
    ToolError,
    WorkspaceError,
)
from remora.core.model.node import Node
from remora.core.model.types import EventType, NodeStatus
from remora.core.services.broker import HumanInputBroker
from remora.core.services.metrics import Metrics
from remora.core.services.rate_limit import SlidingWindowRateLimiter
from remora.core.services.search import SearchServiceProtocol
from remora.core.storage.graph import NodeStore
from remora.core.storage.workspace import AgentWorkspace, CairnWorkspaceService
from remora.core.tools.context import EXTERNALS_VERSION, TurnContext
from remora.core.tools.grail import GrailTool, discover_tools
from remora.core.utils import mask_secret

logger = logging.getLogger(__name__)


def _turn_logger(node_id: str, correlation_id: str, turn_number: int) -> logging.LoggerAdapter:
    """Create a logger adapter with per-turn context fields."""
    return logging.LoggerAdapter(
        logger,
        {
            "node_id": node_id,
            "correlation_id": correlation_id,
            "turn": turn_number,
        },
    )


class AgentTurnExecutor:
    """Execute a single agent turn including workspace, tools, and kernel calls."""

    def __init__(
        self,
        *,
        node_store: NodeStore,
        event_store: EventStore,
        workspace_service: CairnWorkspaceService,
        config: Config,
        semaphore: asyncio.Semaphore,
        metrics: Metrics | None,
        history: list[Message],
        prompt_builder: PromptBuilder,
        trigger_policy: TriggerPolicy,
        search_service: SearchServiceProtocol | None,
        send_message_limiter: SlidingWindowRateLimiter | None = None,
        broker: HumanInputBroker | None = None,
        max_model_retries: int = 1,
    ) -> None:
        self._node_store = node_store
        self._event_store = event_store
        self._workspace_service = workspace_service
        self._config = config
        self._semaphore = semaphore
        self._metrics = metrics
        self._history = history
        self._prompt_builder = prompt_builder
        self._trigger_policy = trigger_policy
        self._search_service = search_service
        self._send_message_limiter = send_message_limiter
        self._broker = broker
        self._max_model_retries = max(0, int(max_model_retries))

    async def execute_turn(self, trigger: Trigger, outbox: Outbox) -> None:
        """Execute one agent turn."""
        node_id = trigger.node_id
        depth_key = trigger.correlation_id
        turn_number = max(1, self._trigger_policy.depths.get(depth_key, 1))
        turn_log = _turn_logger(node_id, trigger.correlation_id, turn_number)

        async with self._semaphore:
            try:
                start_result = await self._start_agent_turn(node_id, trigger, outbox, turn_log)
                if start_result is None:
                    return
                node, workspace, bundle_config = start_result

                turn_config = self._prompt_builder.build_turn_config(bundle_config, trigger.event)
                system_prompt = turn_config.system_prompt
                model_name = turn_config.model
                max_turns = turn_config.max_turns
                is_reflection_turn = (
                    trigger.event is not None
                    and trigger.event.event_type == EventType.AGENT_COMPLETE
                    and "primary" in getattr(trigger.event, "tags", ())
                )
                companion_context = ""
                if not is_reflection_turn:
                    companion_data = await workspace.get_companion_data()
                    companion_context = self._prompt_builder.format_companion_context(
                        companion_data
                    )
                    if companion_context:
                        system_prompt = f"{system_prompt}\n{companion_context}"

                _, tools = await self._prepare_turn_context(
                    node_id,
                    workspace,
                    trigger,
                    outbox,
                )

                turn_log.debug(
                    "Agent turn start node=%s corr=%s model=%s tools=%d max_turns=%d trigger=%s",
                    node_id,
                    trigger.correlation_id,
                    model_name,
                    len(tools),
                    max_turns,
                    trigger.event.event_type if trigger.event is not None else "manual",
                )

                messages = [
                    Message(role="system", content=system_prompt),
                    Message(
                        role="user",
                        content=self._prompt_builder.build_user_prompt(
                            node,
                            trigger.event,
                            bundle_config=bundle_config,
                            companion_context=companion_context,
                        ),
                    ),
                ]
                user_message = (
                    messages[1].content
                    if len(messages) > 1 and messages[1].content is not None
                    else ""
                )
                self._history.extend(messages)

                result = await self._run_kernel(
                    node_id,
                    trigger,
                    system_prompt,
                    messages,
                    model_name,
                    tools,
                    max_turns,
                    outbox,
                    turn_log,
                )

                response_text = extract_response_text(result)
                self._history.append(Message(role="assistant", content=response_text))
                turn_tags = ("reflection",) if is_reflection_turn else ("primary",)
                await self._complete_agent_turn(
                    node_id,
                    response_text,
                    workspace,
                    outbox,
                    trigger,
                    turn_log,
                    turn_tags=turn_tags,
                    user_message=user_message,
                )
                if self._metrics is not None:
                    self._metrics.agent_turns_total += 1
            # Error boundary: a single turn failure must not crash the actor loop.
            except (ModelError, ToolError, WorkspaceError, IncompatibleBundleError) as exc:
                turn_log.exception("Agent turn failed")
                if self._metrics is not None:
                    self._metrics.agent_turns_failed += 1
                await self._node_store.transition_status(node_id, NodeStatus.ERROR)
                error_text = str(exc)
                error_reason = error_text.splitlines()[0][:200] if error_text else ""
                await outbox.emit(
                    AgentErrorEvent(
                        agent_id=node_id,
                        error=error_text,
                        error_class=type(exc).__name__,
                        error_reason=error_reason,
                        correlation_id=trigger.correlation_id,
                    )
                )
            finally:
                await self._reset_agent_state(node_id, depth_key, turn_log)

    async def _start_agent_turn(
        self,
        node_id: str,
        trigger: Trigger,
        outbox: Outbox,
        turn_log: logging.LoggerAdapter,
    ) -> tuple[Node, AgentWorkspace, BundleConfig] | None:
        node = await self._node_store.get_node(node_id)
        if node is None:
            turn_log.warning("Trigger for unknown node")
            return None

        if not await self._node_store.transition_status(node_id, NodeStatus.RUNNING):
            turn_log.warning("Failed to transition node into running state")
            return None

        await outbox.emit(
            AgentStartEvent(
                agent_id=node_id,
                node_name=node.name,
                correlation_id=trigger.correlation_id,
            )
        )

        workspace = await self._workspace_service.get_agent_workspace(node_id)
        bundle_config = await self._workspace_service.read_bundle_config(node_id)

        if (
            bundle_config.externals_version is not None
            and bundle_config.externals_version > EXTERNALS_VERSION
        ):
            raise IncompatibleBundleError(
                bundle_config.externals_version,
                EXTERNALS_VERSION,
            )

        return node, workspace, bundle_config

    async def _prepare_turn_context(
        self, node_id: str, workspace: AgentWorkspace, trigger: Trigger, outbox: Outbox
    ) -> tuple[TurnContext, list[GrailTool]]:
        context = TurnContext(
            node_id=node_id,
            workspace=workspace,
            correlation_id=trigger.correlation_id,
            node_store=self._node_store,
            event_store=self._event_store,
            outbox=outbox,
            human_input_timeout_s=self._config.runtime.human_input_timeout_s,
            search_content_max_matches=self._config.runtime.search_content_max_matches,
            broadcast_max_targets=self._config.runtime.broadcast_max_targets,
            send_message_limiter=self._send_message_limiter,
            search_service=self._search_service,
            broker=self._broker,
        )
        capabilities = context.to_capabilities_dict()
        tools = await discover_tools(workspace, capabilities)
        return context, tools

    async def _run_kernel(
        self,
        node_id: str,
        trigger: Trigger,
        system_prompt: str,
        messages: list[Message],
        model_name: str,
        tools: list[GrailTool],
        max_turns: int,
        outbox: Outbox,
        turn_log: logging.LoggerAdapter,
    ) -> Any:
        max_retries = self._max_model_retries
        last_exc: Exception | None = None
        tool_schemas = [tool.schema for tool in tools]

        for attempt in range(max_retries + 1):
            try:
                kernel = create_kernel(
                    model_name=model_name,
                    base_url=self._config.infra.model_base_url,
                    api_key=self._config.infra.model_api_key,
                    timeout=self._config.infra.timeout_s,
                    tools=tools,
                    observer=OutboxObserver(outbox=outbox, agent_id=node_id),
                )
            except OSError as exc:
                raise ModelError(f"Model call failed: {exc}") from exc
            try:
                if attempt == 0:
                    turn_log.debug(
                        (
                            "Model request node=%s corr=%s base_url=%s api_key=%s model=%s "
                            "tools=%s system=%s user=%s"
                        ),
                        node_id,
                        trigger.correlation_id,
                        self._config.infra.model_base_url,
                        mask_secret(self._config.infra.model_api_key),
                        model_name,
                        [schema.name for schema in tool_schemas],
                        system_prompt,
                        messages[1].content or "",
                    )
                else:
                    turn_log.warning(
                        "Retrying model request node=%s attempt=%d/%d",
                        node_id,
                        attempt + 1,
                        max_retries + 1,
                    )
                return await run_kernel(kernel, messages, tool_schemas, max_turns=max_turns)
            # Error boundary: kernel/model failures are retried and surfaced as turn errors.
            except (ModelError, OSError, TimeoutError) as exc:
                last_exc = exc
                if attempt < max_retries:
                    backoff = 2.0**attempt
                    turn_log.warning(
                        "Model request failed node=%s attempt=%d, retrying in %.1fs: %s",
                        node_id,
                        attempt + 1,
                        backoff,
                        exc,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise
            finally:
                await kernel.close()

        raise RuntimeError(str(last_exc) if last_exc is not None else "kernel run failed")

    async def _complete_agent_turn(
        self,
        node_id: str,
        response_text: str,
        workspace: AgentWorkspace,
        outbox: Outbox,
        trigger: Trigger,
        turn_log: logging.LoggerAdapter,
        *,
        turn_tags: tuple[str, ...] = ("primary",),
        user_message: str = "",
    ) -> None:
        turn_log.debug(
            "Agent turn complete node=%s corr=%s response=%s",
            node_id,
            trigger.correlation_id,
            response_text,
        )
        await outbox.emit(
            AgentCompleteEvent(
                agent_id=node_id,
                result_summary=response_text[:200],
                full_response=response_text,
                user_message=user_message,
                correlation_id=trigger.correlation_id,
                tags=turn_tags,
            )
        )
        if "reflection" in turn_tags:
            await self._emit_turn_digested(
                node_id,
                response_text,
                workspace,
                outbox,
                trigger,
                turn_log,
            )

    async def _emit_turn_digested(
        self,
        node_id: str,
        response_text: str,
        workspace: AgentWorkspace,
        outbox: Outbox,
        trigger: Trigger,
        turn_log: logging.LoggerAdapter,
    ) -> None:
        digest_summary = (response_text or "").strip()[:500]
        if not digest_summary:
            digest_summary = "Reflection turn completed."
        has_reflection = False
        has_links = False
        digest_tags: tuple[str, ...] = ()

        try:
            companion_data = await workspace.get_companion_data()
            has_reflection = bool(companion_data.reflections)
            has_links = bool(companion_data.links)

            for entry in reversed(companion_data.chat_index):
                if not isinstance(entry, dict):
                    continue
                summary = entry.get("summary")
                if isinstance(summary, str) and summary.strip():
                    digest_summary = summary.strip()[:500]
                raw_tags = entry.get("tags")
                if isinstance(raw_tags, (list, tuple)):
                    digest_tags = tuple(
                        str(tag).strip()
                        for tag in raw_tags
                        if str(tag).strip()
                    )
                break
        # Error boundary: digest emission should not break completed reflection turns.
        except Exception:
            turn_log.debug("Failed to build turn digest payload", exc_info=True)

        await outbox.emit(
            TurnDigestedEvent(
                agent_id=node_id,
                digest_summary=digest_summary,
                has_reflection=has_reflection,
                has_links=has_links,
                correlation_id=trigger.correlation_id,
                tags=digest_tags,
            )
        )

    async def _reset_agent_state(
        self, node_id: str, depth_key: str | None, turn_log: logging.LoggerAdapter
    ) -> None:
        try:
            current_node = await self._node_store.get_node(node_id)
            if current_node is not None and current_node.status == NodeStatus.RUNNING:
                await self._node_store.transition_status(node_id, NodeStatus.IDLE)
        # Error boundary: status reset is best-effort cleanup during finally path.
        except (OSError, aiosqlite.Error):
            turn_log.exception("Failed to reset node status")
        self._trigger_policy.release_depth(depth_key)


__all__ = ["AgentTurnExecutor"]
