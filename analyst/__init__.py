"""AI analyst: lets an agent answer questions from the governed marts, read-only.

catalog   - what models and metrics exist, their columns, tests and lineage (from dbt's manifest)
sql_guard - read-only SQL against the warehouse, enforced at connection, session and statement level
tools     - the six tools an agent gets (shared by the MCP server and the Claude API agent)
server    - MCP server, so Claude Code, Claude Desktop or any MCP client can use the tools
agent     - an API agent over the same tools (Claude or Gemini, see llm), with turn and token caps
llm       - provider-agnostic tool-calling loop and model clients
evals/    - 20 questions with answers computed from the marts, and a scorer
"""
