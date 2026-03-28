"""
Phase 22: Custom Skills Foundation - Adapter

Wraps a CustomSkill DB record as a BaseSkill instance so that
tenant-created skills integrate seamlessly with the existing
SkillManager registry, tool definitions, and prompt injection pipeline.
"""
import logging
from typing import Dict, Optional, Any

from agent.skills.base import BaseSkill, InboundMessage, SkillResult

logger = logging.getLogger(__name__)


class CustomSkillAdapter(BaseSkill):
    """Adapter that wraps a CustomSkill DB record as a BaseSkill instance."""

    skill_type = "custom"
    skill_name = "Custom Skill"
    skill_description = "Tenant-created custom skill"
    execution_mode = "tool"

    def __init__(self, skill_record=None):
        super().__init__()
        self._record = skill_record
        if skill_record:
            self.skill_type = f"custom:{skill_record.slug}"
            self.skill_name = skill_record.name
            self.skill_description = skill_record.description or ""
            self.execution_mode = skill_record.execution_mode

    async def can_handle(self, message: InboundMessage) -> bool:
        if not self._record:
            return False
        if self._record.trigger_mode == 'always_on':
            return True
        if self._record.trigger_mode == 'keyword' and self._record.trigger_keywords:
            msg_lower = message.body.lower() if message.body else ""
            return any(kw.lower() in msg_lower for kw in self._record.trigger_keywords)
        return False  # llm_decided -- handled via tool call

    async def process(self, message: InboundMessage, config: Dict) -> SkillResult:
        return await self.execute_tool({}, message, config)

    def get_mcp_tool_definition(self) -> Optional[Dict]:
        if not self._record or self._record.execution_mode == 'passive':
            return None
        tool_def = {
            "name": f"custom_{self._record.slug}",
            "description": self._record.description or self._record.name,
        }
        if self._record.input_schema:
            tool_def["inputSchema"] = self._record.input_schema
        else:
            tool_def["inputSchema"] = {"type": "object", "properties": {}}
        return tool_def

    async def execute_tool(self, arguments: Dict, message: InboundMessage = None, config: Dict = None) -> SkillResult:
        if not self._record:
            return SkillResult(success=False, output="No skill record attached", metadata={})

        if self._record.skill_type_variant == 'instruction':
            return self._execute_instruction(arguments)
        elif self._record.skill_type_variant == 'script':
            return SkillResult(success=False, output="Script execution not yet implemented", metadata={})
        else:
            return SkillResult(success=False, output=f"Unknown skill type: {self._record.skill_type_variant}", metadata={})

    def _execute_instruction(self, arguments: Dict) -> SkillResult:
        output = self._record.instructions_md or ""
        if arguments:
            # Simple template substitution
            for key, value in arguments.items():
                output = output.replace(f"{{{{{key}}}}}", str(value))
        return SkillResult(
            success=True,
            output=output,
            metadata={"skill_type": "instruction", "skill_name": self._record.name},
        )

    def get_instructions_for_prompt(self) -> Optional[str]:
        if self._record and self._record.instructions_md:
            return f"\n\n## Custom Skill: {self._record.name}\n{self._record.instructions_md}"
        return None
