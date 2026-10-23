"""Shared structured-output runtime for CostOpt LangGraph agent nodes."""

import json
from typing import Any

from google import genai
from google.genai import types
from pydantic import ValidationError

from costopt.config import AgentLLMProfile, settings
from costopt.models.domain import AgentNarrative, AgentToolTrace
from costopt.prompts.registry import load_system_prompt
from costopt.observability.logging import get_logger


logger = get_logger(__name__)


class AgentExecution:
    def __init__(
        self,
        narrative: AgentNarrative,
        used_fallback: bool,
        tool_traces: list[AgentToolTrace] | None = None,
    ) -> None:
        self.narrative = narrative
        self.used_fallback = used_fallback
        self.tool_traces = tool_traces or []


class StructuredCostOptAgent:
    """Run one narrow agent against verified inputs, with a deterministic fallback."""

    def __init__(
        self,
        profile: AgentLLMProfile,
        client: Any | None = None,
    ) -> None:
        self.profile = profile
        self._client = client

    def explain(
        self,
        facts: dict[str, Any],
        fallback: AgentNarrative,
        allowed_citation_ids: set[str],
        tool_traces: list[AgentToolTrace] | None = None,
    ) -> AgentExecution:
        if not self.profile.enabled:
            logger.info(
                "Agent narrative using deterministic fallback",
                extra={
                    "event": "agent_llm_skipped",
                    "agent": self.profile.agent,
                    "reason": "disabled_or_mock",
                },
            )
            return AgentExecution(fallback, used_fallback=True, tool_traces=tool_traces)
        if not settings.gemini_api_key or not self.profile.model:
            logger.warning(
                "Agent narrative using deterministic fallback because LLM configuration is incomplete",
                extra={
                    "event": "agent_llm_skipped",
                    "agent": self.profile.agent,
                    "reason": "incomplete_configuration",
                },
            )
            return AgentExecution(fallback, used_fallback=True, tool_traces=tool_traces)

        try:
            narrative = AgentNarrative.model_validate(self._invoke_gemini(facts))
            if any(citation_id not in allowed_citation_ids for citation_id in narrative.citation_ids):
                raise ValueError("Agent returned a citation outside the supplied evidence.")
            logger.info(
                "Agent narrative generation completed",
                extra={"event": "agent_llm_completed", "agent": self.profile.agent},
            )
            return AgentExecution(narrative, used_fallback=False, tool_traces=tool_traces)
        except Exception:
            logger.warning(
                "Agent narrative generation failed; deterministic fallback used",
                exc_info=True,
                extra={"event": "agent_llm_fallback", "agent": self.profile.agent},
            )
            return AgentExecution(fallback, used_fallback=True, tool_traces=tool_traces)

    def _invoke_gemini(self, facts: dict[str, Any]) -> dict[str, Any]:
        client = self._client or genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
        )
        response = client.models.generate_content(
            model=self.profile.model,
            contents=(
                load_system_prompt(self.profile.prompt_key) + "\n\n"
                + "Return JSON only with this exact shape: "
                '{"summary":"...","key_considerations":["..."],'
                '"citation_ids":["..."],"risks":["..."],'
                '"next_actions":["..."]}. '
                "Use only the supplied facts and citation IDs.\n\n" + json.dumps(facts)
            ),
            config=types.GenerateContentConfig(
                temperature=self.profile.temperature,
                max_output_tokens=self.profile.max_tokens,
                response_mime_type="application/json",
                response_schema=AgentNarrative,
            ),
        )
        return _parse_json(response.text)


def _parse_json(content: str) -> dict[str, Any]:
    trimmed = content.strip()
    if trimmed.startswith("```"):
        trimmed = trimmed.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    parsed = json.loads(trimmed)
    if not isinstance(parsed, dict):
        raise ValueError("Agent response was not a JSON object.")
    return parsed
