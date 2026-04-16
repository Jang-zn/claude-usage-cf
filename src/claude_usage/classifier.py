"""Deterministic 2-phase task classifier.

Ported from CodeBurn src/classifier.ts — no LLM calls, pure pattern matching.
Phase 1: tool-name patterns → coarse category
Phase 2: user-message keyword refinement → precise category
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# Category Enum
# ---------------------------------------------------------------------------

class TaskCategory(Enum):
    CODING       = "Coding"
    DEBUGGING    = "Debugging"
    FEATURE      = "Feature"
    REFACTORING  = "Refactoring"
    TESTING      = "Testing"
    GIT          = "Git"
    BUILD_DEPLOY = "Build/Deploy"
    EXPLORATION  = "Exploration"
    PLANNING     = "Planning"
    DELEGATION   = "Delegation"
    BRAINSTORMING = "Brainstorming"
    CONVERSATION = "Conversation"
    GENERAL      = "General"


# ---------------------------------------------------------------------------
# Regex patterns (mirrors CodeBurn constants)
# ---------------------------------------------------------------------------

_TEST_PATTERNS    = re.compile(
    r"\b(test|pytest|vitest|jest|mocha|spec|coverage|npm\s+test|npx\s+vitest|npx\s+jest)\b", re.I)
_GIT_PATTERNS     = re.compile(
    r"\bgit\s+(push|pull|commit|merge|rebase|checkout|branch|stash|log|diff|status|add|reset|cherry-pick|tag)\b", re.I)
_BUILD_PATTERNS   = re.compile(
    r"\b(npm\s+run\s+build|npm\s+publish|pip\s+install|docker|deploy|make\s+build"
    r"|npm\s+run\s+dev|npm\s+start|pm2|systemctl|brew|cargo\s+build)\b", re.I)
_INSTALL_PATTERNS = re.compile(
    r"\b(npm\s+install|pip\s+install|brew\s+install|apt\s+install|cargo\s+add)\b", re.I)

_DEBUG_KEYWORDS     = re.compile(
    r"\b(fix|bug|error|broken|failing|crash|issue|debug|traceback|exception"
    r"|stack\s*trace|not\s+working|wrong|unexpected|status\s+code|404|500|401|403)\b", re.I)
_FEATURE_KEYWORDS   = re.compile(
    r"\b(add|create|implement|new|build|feature|introduce|set\s*up|scaffold"
    r"|generate|make\s+(?:a|me|the)|write\s+(?:a|me|the))\b", re.I)
_REFACTOR_KEYWORDS  = re.compile(
    r"\b(refactor|clean\s*up|rename|reorganize|simplify|extract|restructure|move|migrate|split)\b", re.I)
_BRAINSTORM_KEYWORDS = re.compile(
    r"\b(brainstorm|idea|what\s+if|explore|think\s+about|approach|strategy|design"
    r"|consider|how\s+should|what\s+would|opinion|suggest|recommend)\b", re.I)
_RESEARCH_KEYWORDS  = re.compile(
    r"\b(research|investigate|look\s+into|find\s+out|check|search|analyze|review"
    r"|understand|explain|how\s+does|what\s+is|show\s+me|list|compare)\b", re.I)
_FILE_PATTERNS      = re.compile(
    r"\.(py|js|ts|tsx|jsx|json|yaml|yml|toml|sql|sh|go|rs|java|rb|php|css|html|md|csv|xml)\b", re.I)
_SCRIPT_PATTERNS    = re.compile(
    r"\b(run\s+\S+\.\w+|execute|scrip?t|curl|api\s+\S+|endpoint"
    r"|request\s+url|fetch\s+\S+|query|database|db\s+\S+)\b", re.I)
_URL_PATTERN        = re.compile(r"https?://\S+", re.I)


# ---------------------------------------------------------------------------
# Tool sets (mirrors CodeBurn constants)
# ---------------------------------------------------------------------------

_EDIT_TOOLS   = frozenset({"Edit", "Write", "FileEditTool", "FileWriteTool",
                            "NotebookEdit", "cursor:edit", "MultiEdit"})
_READ_TOOLS   = frozenset({"Read", "Grep", "Glob", "FileReadTool", "GrepTool", "GlobTool"})
_BASH_TOOLS   = frozenset({"Bash", "BashTool", "PowerShellTool"})
_TASK_TOOLS   = frozenset({"TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
                            "TaskOutput", "TaskStop", "TodoWrite"})
_SEARCH_TOOLS = frozenset({"WebSearch", "WebFetch", "ToolSearch"})

# Agent-spawn tool names (Claude Code Delegation)
_AGENT_TOOLS  = frozenset({"Agent", "Task", "Subagent"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _has_edit(tools: list[str]) -> bool:
    return any(t in _EDIT_TOOLS for t in tools)

def _has_read(tools: list[str]) -> bool:
    return any(t in _READ_TOOLS for t in tools)

def _has_bash(tools: list[str]) -> bool:
    return any(t in _BASH_TOOLS for t in tools)

def _has_task(tools: list[str]) -> bool:
    return any(t in _TASK_TOOLS for t in tools)

def _has_search(tools: list[str]) -> bool:
    return any(t in _SEARCH_TOOLS for t in tools)

def _has_mcp(tools: list[str]) -> bool:
    return any(t.startswith("mcp__") for t in tools)

def _has_agent(tools: list[str]) -> bool:
    return any(t in _AGENT_TOOLS for t in tools)

def _has_skill(tools: list[str]) -> bool:
    return "Skill" in tools


# ---------------------------------------------------------------------------
# Phase 1 — tool-pattern classification
# ---------------------------------------------------------------------------

def _classify_by_tools(
    tools: list[str],
    bash_commands: list[str],
    *,
    has_plan_mode: bool = False,
    has_agent_spawn: bool = False,
) -> TaskCategory | None:
    """Return a coarse category from tool usage, or None if undetermined."""
    if not tools:
        return None

    if has_plan_mode:
        return TaskCategory.PLANNING
    if has_agent_spawn or _has_agent(tools):
        return TaskCategory.DELEGATION

    has_edits  = _has_edit(tools)
    has_reads  = _has_read(tools)
    has_bash   = _has_bash(tools)
    has_tasks  = _has_task(tools)
    has_search = _has_search(tools)
    has_mcp    = _has_mcp(tools)

    # Bash-only path: classify by command content
    if has_bash and not has_edits:
        combined = " ".join(bash_commands)
        if _TEST_PATTERNS.search(combined):
            return TaskCategory.TESTING
        if _GIT_PATTERNS.search(combined):
            return TaskCategory.GIT
        if _BUILD_PATTERNS.search(combined):
            return TaskCategory.BUILD_DEPLOY
        if _INSTALL_PATTERNS.search(combined):
            return TaskCategory.BUILD_DEPLOY

    if has_edits:
        return TaskCategory.CODING

    if has_bash and has_reads:
        return TaskCategory.EXPLORATION
    if has_bash:
        return TaskCategory.CODING

    if has_search or has_mcp:
        return TaskCategory.EXPLORATION
    if has_reads and not has_edits:
        return TaskCategory.EXPLORATION
    if has_tasks and not has_edits:
        return TaskCategory.PLANNING
    if _has_skill(tools):
        return TaskCategory.GENERAL

    return None


# ---------------------------------------------------------------------------
# Phase 2 — keyword refinement
# ---------------------------------------------------------------------------

def _refine_by_keywords(category: TaskCategory, user_message: str) -> TaskCategory:
    """Refine a coarse category using user-message keywords."""
    if category == TaskCategory.CODING:
        if _DEBUG_KEYWORDS.search(user_message):
            return TaskCategory.DEBUGGING
        if _REFACTOR_KEYWORDS.search(user_message):
            return TaskCategory.REFACTORING
        if _FEATURE_KEYWORDS.search(user_message):
            return TaskCategory.FEATURE
        return TaskCategory.CODING

    if category == TaskCategory.EXPLORATION:
        if _RESEARCH_KEYWORDS.search(user_message):
            return TaskCategory.EXPLORATION
        if _DEBUG_KEYWORDS.search(user_message):
            return TaskCategory.DEBUGGING
        return TaskCategory.EXPLORATION

    return category


# ---------------------------------------------------------------------------
# Conversation-only classification (no tools used)
# ---------------------------------------------------------------------------

def _classify_conversation(user_message: str) -> TaskCategory:
    """Classify a turn that used no tools at all."""
    if _BRAINSTORM_KEYWORDS.search(user_message):
        return TaskCategory.BRAINSTORMING
    if _RESEARCH_KEYWORDS.search(user_message):
        return TaskCategory.EXPLORATION
    if _DEBUG_KEYWORDS.search(user_message):
        return TaskCategory.DEBUGGING
    if _FEATURE_KEYWORDS.search(user_message):
        return TaskCategory.FEATURE
    if _FILE_PATTERNS.search(user_message):
        return TaskCategory.CODING
    if _SCRIPT_PATTERNS.search(user_message):
        return TaskCategory.CODING
    if _URL_PATTERN.search(user_message):
        return TaskCategory.EXPLORATION
    return TaskCategory.CONVERSATION


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_turn(
    tools: list[str],
    bash_commands: list[str],
    first_user_message: str,
    *,
    has_plan_mode: bool = False,
    has_agent_spawn: bool = False,
) -> TaskCategory:
    """Classify a conversation turn into one of 13 TaskCategories.

    Args:
        tools:              All tool names used by the assistant in this turn.
        bash_commands:      Raw bash command strings executed during the turn.
        first_user_message: The first (or only) user message text in the turn.
        has_plan_mode:      True if the turn contained a TodoWrite / plan-mode call
                            that signals explicit planning (optional, default False).
        has_agent_spawn:    True if an agent/sub-agent was spawned (optional).

    Returns:
        TaskCategory enum member.
    """
    if not tools:
        return _classify_conversation(first_user_message)

    coarse = _classify_by_tools(
        tools,
        bash_commands,
        has_plan_mode=has_plan_mode,
        has_agent_spawn=has_agent_spawn,
    )
    if coarse is not None:
        return _refine_by_keywords(coarse, first_user_message)

    return _classify_conversation(first_user_message)
