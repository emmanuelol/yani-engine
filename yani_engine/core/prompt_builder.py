"""
prompt_builder.py — Prompt Assembly and Memory Slicing.

Extracted from LLMOrchestrator to decouple prompt formatting, markdown
section slicing, and instruction caching from CLI dispatch and routing.

Responsibilities:
  - _get_sliced_memory: targeted section extraction from memory.md to
    minimize token consumption
  - _get_system_instructions: assembles the full system prompt from
    SYSTEM_INSTRUCTIONS.md, protocol files, knowledge index, and memory
    state; caches by (command, task_id, memory_hash)

Dependency injection:
  PromptBuilder(orchestrator) holds a reference to the live
  LLMOrchestrator instance to access local_tools and plugin_root.
  The instance-level cache (_sys_inst_cache) lives here rather than on
  the orchestrator, isolating memory overhead from the router.

Usage:
  LLMOrchestrator.__init__ instantiates self.prompt_builder = PromptBuilder(self).
  Callers invoke orchestrator.prompt_builder._get_system_instructions(...) and
  orchestrator.prompt_builder._get_sliced_memory(...).
"""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yani_engine.core.orchestrator import LLMOrchestrator


class PromptBuilder:
    """Stateless prompt assembly and memory slicing engine.

    Instantiated once per LLMOrchestrator and stored as
    orchestrator.prompt_builder. Holds the sys_inst_cache dict so that
    stale caches do not accumulate on the orchestrator instance across
    parallel sessions.
    """

    def __init__(self, orchestrator: "LLMOrchestrator") -> None:
        self._o = orchestrator
        self._sys_inst_cache: dict[str, str] = {}

    async def _get_sliced_memory(self, sections: list) -> str:
        """Extracts only specified sections from memory.md to minimize token consumption."""
        o = self._o
        content = await o.local_tools[0]("memory.md")
        if not content or content.startswith("Error"):
            return "Memory state unavailable."

        sliced = []
        capture = False
        target_level = 0

        for line in content.splitlines():
            stripped = line.strip()

            # Check if this line starts any of our target sections (## or ###)
            if any(
                stripped.startswith(f"## {s}") or stripped.startswith(f"### {s}")
                for s in sections
            ):
                capture = True
                # Determine the heading level we just matched (2 for ##, 3 for ###)
                target_level = len(stripped) - len(stripped.lstrip("#"))

            # Stop capturing if we hit a new heading of the SAME or HIGHER hierarchical level
            elif capture and stripped.startswith("#"):
                current_level = len(stripped) - len(stripped.lstrip("#"))
                if current_level <= target_level:
                    capture = False

            if capture:
                sliced.append(line)

        return "\n".join(sliced) if sliced else content

    async def _get_system_instructions(self, command: str = None, task_id: str = None) -> str:
        """Assembles the full system prompt, cached by (command, task_id, memory_hash)."""
        o = self._o

        # HYBRID OPTIMIZATION: Strict slicing for execute
        if command == "execute" and task_id:
            memory_content = await self._get_sliced_memory(["Config", "Task Registry", task_id])
        elif command == "iterate":
            # Removed "Task Details" to prevent unbounded token bleed.
            # The LLM must rely on the Task Registry summary or use read_file for specifics.
            memory_content = await self._get_sliced_memory(
                ["Project Goal", "Scope", "Edge Case Coverage", "Task Registry"]
            )
        else:
            memory_content = (
                await o.local_tools[0]("memory.md") or "No memory.md found. Start a new project."
            )

        mem_hash = hashlib.md5(memory_content.encode("utf-8")).hexdigest()
        cache_key = f"{command}_{task_id}_{mem_hash}"
        if cache_key in self._sys_inst_cache:
            return self._sys_inst_cache[cache_key]

        instructions = [
            "# MISSION",
            "You are yani-engine, an Agent Engineering Harness. Your goal is to systematically analyze, improve, and validate agent projects.",
            await o.local_tools[0](os.path.join(o.plugin_root, "SYSTEM_INSTRUCTIONS.md"))
            or "Core rules not found.",
        ]

        # Only inject heavy protocols for planning/iterating commands
        if command in (None, "iterate", "start", "audit"):
            instructions.extend(
                [
                    await o.local_tools[0](os.path.join(o.plugin_root, "lib", "common-preamble.md")) or "",
                    await o.local_tools[0](os.path.join(o.plugin_root, "lib", "compression-policy.md")) or "",
                    "# KNOWLEDGE PROTOCOL",
                    await o.local_tools[0](os.path.join(o.plugin_root, "lib", "knowledge-protocol.md")) or "",
                    "# MEMORY SCHEMA",
                    await o.local_tools[0](os.path.join(o.plugin_root, "lib", "memory-schema.md")) or "",
                ]
            )

        # OP-2 Selective Load: Inject the Knowledge Index as semantic memory
        knowledge_index = await o.local_tools[0]("knowledge/index.md")
        if not knowledge_index or knowledge_index.startswith("Error"):
            knowledge_index = (
                "Knowledge registry not yet initialized. "
                "Use the record_knowledge tool to capture insights."
            )

        instructions.append(f"# DURABLE SEMANTIC MEMORY (Knowledge Vault)\n{knowledge_index}")
        instructions.append(f"# CURRENT STATE (Working Memory)\n{memory_content}")

        if command and command != "execute":
            skill_path = os.path.join(o.plugin_root, "skills", command, "INSTRUCTIONS.md")
            skill_content = await o.local_tools[0](skill_path)
            if skill_content and not skill_content.startswith("Error"):
                instructions.append(f"# COMMAND SPECIFIC INSTRUCTIONS ({command})\n{skill_content}")

        final_instructions = "\n\n".join(instructions)
        self._sys_inst_cache[cache_key] = final_instructions
        return final_instructions
