"""Prompt construction primitives for agent turns."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from remora.core.events.types import Event
from remora.core.model.config import BundleConfig, Config
from remora.core.model.node import Node
from remora.core.model.types import EventType, serialize_enum


@dataclass
class CompanionData:
    """Raw companion memory data from agent workspace."""

    reflections: list[dict[str, Any]] = field(default_factory=list)
    chat_index: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class TurnConfig:
    """Configuration for a single agent turn."""

    system_prompt: str
    model: str
    max_turns: int


class PromptBuilder:
    """Build system and user prompts from bundle config and templates."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._default_templates = dict(config.behavior.prompt_templates)

    def build_turn_config(
        self,
        bundle_config: BundleConfig,
        trigger_event: Event | None,
    ) -> TurnConfig:
        if self._is_reflection_turn(bundle_config, trigger_event):
            return self._build_reflection(bundle_config)

        system_prompt = bundle_config.system_prompt
        prompt_extension = bundle_config.system_prompt_extension
        if prompt_extension:
            system_prompt = f"{system_prompt}\n\n{prompt_extension}"

        mode = self.turn_mode(trigger_event)
        mode_prompt = bundle_config.prompts.get(mode, "")
        if mode_prompt:
            system_prompt = f"{system_prompt}\n\n{mode_prompt}"

        model_name = bundle_config.model or self._config.behavior.model_default
        max_turns = bundle_config.max_turns or self._config.behavior.max_turns
        return TurnConfig(system_prompt=system_prompt, model=model_name, max_turns=max_turns)

    def build_user_prompt(
        self,
        node: Node,
        trigger_event: Event | None,
        *,
        bundle_config: BundleConfig | None = None,
        companion_context: str = "",
    ) -> str:
        """Build the user prompt from template interpolation."""
        variables = self._build_template_vars(node, trigger_event, companion_context)

        bundle_template = ""
        if bundle_config is not None:
            bundle_template = bundle_config.prompt_templates.get("user", "")

        template = bundle_template or self._default_templates.get("user", "")
        return self._interpolate(template, variables)

    @staticmethod
    def turn_mode(event: Event | None) -> str:
        from_agent = getattr(event, "from_agent", None) if event is not None else None
        return "chat" if from_agent == "user" else "reactive"

    def _build_reflection(self, bundle_config: BundleConfig) -> TurnConfig:
        self_reflect = bundle_config.self_reflect
        if self_reflect is None:
            return TurnConfig(
                system_prompt="",
                model=self._config.behavior.model_default,
                max_turns=1,
            )

        reflection_prompt = (
            self_reflect.prompt
            or bundle_config.prompt_templates.get("reflection", "")
            or self._default_templates.get("reflection", "")
        )
        model_name = (
            self_reflect.model or bundle_config.model or self._config.behavior.model_default
        )
        max_turns = self_reflect.max_turns
        return TurnConfig(
            system_prompt=reflection_prompt,
            model=model_name,
            max_turns=max_turns,
        )

    @staticmethod
    def _interpolate(template: str, variables: dict[str, str]) -> str:
        """Interpolate template vars using single-pass regex replacement."""

        def replacer(match: re.Match[str]) -> str:
            key = match.group(1)
            return variables.get(key, match.group(0))

        return re.sub(r"\{(\w+)\}", replacer, template)

    def _build_template_vars(
        self,
        node: Node,
        trigger_event: Event | None,
        companion_context: str,
    ) -> dict[str, str]:
        return {
            "node_name": node.name,
            "node_full_name": node.full_name,
            "node_type": serialize_enum(node.node_type),
            "file_path": node.file_path,
            "source": node.text or "",
            "role": node.role or "",
            "event_type": trigger_event.event_type if trigger_event is not None else "manual",
            "event_content": _event_content(trigger_event) if trigger_event is not None else "",
            "turn_mode": self.turn_mode(trigger_event),
            "companion_context": companion_context,
        }

    @staticmethod
    def _is_reflection_turn(
        bundle_config: BundleConfig,
        trigger_event: Event | None,
    ) -> bool:
        self_reflect = bundle_config.self_reflect
        return (
            self_reflect is not None
            and self_reflect.enabled
            and trigger_event is not None
            and trigger_event.event_type == EventType.AGENT_COMPLETE
            and "primary" in getattr(trigger_event, "tags", ())
        )

    @staticmethod
    def format_companion_context(data: CompanionData) -> str:
        """Format raw companion data into a markdown context block."""
        parts: list[str] = []

        if data.reflections:
            lines = []
            for entry in data.reflections[-5:]:
                if not isinstance(entry, dict):
                    continue
                insight = entry.get("insight", "")
                if isinstance(insight, str) and insight.strip():
                    lines.append(f"- {insight.strip()}")
            if lines:
                parts.append("## Prior Reflections")
                parts.extend(lines)

        if data.chat_index:
            lines = []
            for entry in data.chat_index[-5:]:
                if not isinstance(entry, dict):
                    continue
                summary = entry.get("summary", "")
                if not isinstance(summary, str) or not summary.strip():
                    continue
                raw_tags = entry.get("tags", [])
                tags_source = raw_tags if isinstance(raw_tags, (list, tuple)) else []
                tags = [str(tag).strip() for tag in tags_source if str(tag).strip()]
                tag_suffix = f" [{', '.join(tags)}]" if tags else ""
                lines.append(f"- {summary.strip()}{tag_suffix}")
            if lines:
                parts.append("## Recent Activity")
                parts.extend(lines)

        if data.links:
            lines = []
            for entry in data.links[-10:]:
                if not isinstance(entry, dict):
                    continue
                target = entry.get("target", "")
                if not isinstance(target, str) or not target.strip():
                    continue
                relationship = entry.get("relationship", "related")
                rel_text = (
                    relationship.strip()
                    if isinstance(relationship, str) and relationship.strip()
                    else "related"
                )
                lines.append(f"- {rel_text}: {target.strip()}")
            if lines:
                parts.append("## Known Relationships")
                parts.extend(lines)

        if not parts:
            return ""
        return "\n## Companion Memory\n" + "\n".join(parts)


def _event_content(event: Event) -> str:
    content = getattr(event, "content", None)
    if content is None:
        return ""
    return str(content)


__all__ = ["CompanionData", "PromptBuilder", "TurnConfig"]
