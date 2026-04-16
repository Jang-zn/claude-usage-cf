"""Unit tests for the 13-category task classifier.

Covers every TaskCategory at least once, plus edge cases.
"""

import pytest
from claude_usage.classifier import TaskCategory, classify_turn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ct(tools, bash, msg, **kw):
    return classify_turn(tools, bash, msg, **kw)


# ---------------------------------------------------------------------------
# Phase-1 dominant: tool-pattern wins
# ---------------------------------------------------------------------------

class TestToolPatternClassification:
    def test_git_via_bash_command(self):
        assert ct(["Bash"], ["git commit -m 'fix'"], "") == TaskCategory.GIT

    def test_git_pull(self):
        assert ct(["Bash"], ["git pull origin main"], "") == TaskCategory.GIT

    def test_testing_via_pytest(self):
        assert ct(["Bash"], ["pytest tests/"], "") == TaskCategory.TESTING

    def test_testing_via_npm_test(self):
        assert ct(["Bash"], ["npm test"], "") == TaskCategory.TESTING

    def test_build_deploy_docker(self):
        assert ct(["Bash"], ["docker build -t myapp ."], "") == TaskCategory.BUILD_DEPLOY

    def test_build_deploy_npm_run_build(self):
        assert ct(["Bash"], ["npm run build"], "") == TaskCategory.BUILD_DEPLOY

    def test_exploration_read_only(self):
        assert ct(["Read", "Grep"], [], "how does auth work") == TaskCategory.EXPLORATION

    def test_exploration_glob(self):
        assert ct(["Glob"], [], "find all config files") == TaskCategory.EXPLORATION

    def test_planning_todowrite(self):
        assert ct(["TodoWrite"], [], "plan the migration") == TaskCategory.PLANNING

    def test_delegation_agent(self):
        assert ct(["Agent"], [], "run the sub-task") == TaskCategory.DELEGATION

    def test_delegation_task(self):
        assert ct(["Task"], [], "") == TaskCategory.DELEGATION

    def test_general_skill_tool(self):
        assert ct(["Skill"], [], "run the commit skill") == TaskCategory.GENERAL


# ---------------------------------------------------------------------------
# Phase-2: keyword refinement on top of Phase-1
# ---------------------------------------------------------------------------

class TestKeywordRefinement:
    def test_coding_with_debug_keyword_yields_debugging(self):
        assert ct(["Edit"], [], "fix the login crash") == TaskCategory.DEBUGGING

    def test_coding_with_error_keyword_yields_debugging(self):
        assert ct(["Write"], [], "there is an error in auth.py") == TaskCategory.DEBUGGING

    def test_coding_with_feature_keyword_yields_feature(self):
        assert ct(["Edit"], [], "implement user profile page") == TaskCategory.FEATURE

    def test_coding_with_add_keyword_yields_feature(self):
        assert ct(["Write"], [], "add dark mode support") == TaskCategory.FEATURE

    def test_coding_with_refactor_keyword(self):
        assert ct(["Edit"], [], "refactor the database layer") == TaskCategory.REFACTORING

    def test_coding_with_clean_up_keyword(self):
        assert ct(["Edit"], [], "clean up the auth module") == TaskCategory.REFACTORING

    def test_pure_coding_no_keyword(self):
        """Edit tool used but no matching keyword → stays Coding."""
        assert ct(["Edit"], [], "update the header component") == TaskCategory.CODING


# ---------------------------------------------------------------------------
# Conversation-only classification (no tools)
# ---------------------------------------------------------------------------

class TestConversationClassification:
    def test_conversation_short_ack(self):
        assert ct([], [], "yes that works, thanks") == TaskCategory.CONVERSATION

    def test_conversation_empty_message(self):
        assert ct([], [], "") == TaskCategory.CONVERSATION

    def test_brainstorming_idea_keyword(self):
        assert ct([], [], "what if we redesign the caching strategy") == TaskCategory.BRAINSTORMING

    def test_brainstorming_brainstorm_keyword(self):
        assert ct([], [], "let's brainstorm approaches for the API") == TaskCategory.BRAINSTORMING

    def test_exploration_research_keyword(self):
        assert ct([], [], "explain how JWT tokens work") == TaskCategory.EXPLORATION

    def test_conversation_feature_keyword_no_tools(self):
        assert ct([], [], "add a signup button") == TaskCategory.FEATURE

    def test_conversation_debug_keyword_no_tools(self):
        assert ct([], [], "the login is broken") == TaskCategory.DEBUGGING

    def test_conversation_file_extension(self):
        assert ct([], [], "look at config.yaml") == TaskCategory.CODING

    def test_conversation_url(self):
        assert ct([], [], "check https://example.com/api") == TaskCategory.EXPLORATION


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_edit_plus_bash_test_prefers_debugging_over_testing(self):
        """Edit tool present → Coding path; debug keyword wins over test command."""
        result = ct(["Edit", "Bash"], ["pytest tests/"], "fix the failing test")
        # Edit forces Coding path; 'fix' + 'failing' → Debugging
        assert result == TaskCategory.DEBUGGING

    def test_bash_only_no_command_match_falls_to_coding(self):
        """Bash tool with non-matching command and edit tool absent → Coding."""
        result = ct(["Bash"], ["echo hello"], "update output")
        assert result == TaskCategory.CODING

    def test_mcp_tool_without_edits_is_exploration(self):
        assert ct(["mcp__some_server__tool"], [], "look up docs") == TaskCategory.EXPLORATION

    def test_websearch_is_exploration(self):
        assert ct(["WebSearch"], [], "find libraries for ML") == TaskCategory.EXPLORATION

    def test_todowrite_only_is_planning(self):
        assert ct(["TodoWrite"], [], "") == TaskCategory.PLANNING

    def test_plan_mode_flag_overrides_edit(self):
        """has_plan_mode flag should yield Planning even with Edit present."""
        result = ct(["Edit", "TodoWrite"], [], "plan the refactor", has_plan_mode=True)
        assert result == TaskCategory.PLANNING

    def test_agent_spawn_flag_overrides_everything(self):
        result = ct(["Edit", "Bash"], ["pytest"], "run agents", has_agent_spawn=True)
        assert result == TaskCategory.DELEGATION
