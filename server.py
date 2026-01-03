from mcp.server.fastmcp import FastMCP, Context
from semantic_layer import load_config, build_semantic_context, format_context_for_prompt
from query_executor import execute_with_retry
from llm_client import generate_sql

# Initialize MCP server
# TODO: Change server name for your domain
mcp = FastMCP("nlq-sql")

# Load config
config = load_config()

# Get log path (used by both tools for logging)
log_path = config["log_query"]["database"]["db_path"]

# Build semantic context for data_query tool at startup
data_tool_config = config["data_query"]
data_semantic_context_data = build_semantic_context(data_tool_config)
data_semantic_context = format_context_for_prompt(data_semantic_context_data, data_tool_config)

# Build semantic context for log_query tool at startup
log_tool_config = config["log_query"]
log_semantic_context_data = build_semantic_context(log_tool_config)
log_semantic_context = format_context_for_prompt(log_semantic_context_data, log_tool_config)


def _get_client_name(ctx: Context) -> str:
    """Extract client name from MCP context."""
    try:
        return ctx.session.client_params.clientInfo.name
    except (AttributeError, TypeError):
        return "unknown"


def _format_result(result: dict) -> dict:
    """Format query result for MCP response."""
    return {
        "success": result["success"],
        "columns": result["columns"],
        "rows": result["rows"][:100] if result["rows"] else None,  # Limit rows returned
        "row_count": result["row_count"],
        "diagnostics": {
            "sql": result["sql"],
            "retry_count": result["retry_count"],
            "errors": result["errors"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"]
        }
    }


@mcp.tool()
def query_data(question: str, ctx: Context) -> dict:
    """
    Query data using natural language.

    Args:
        question: A natural language question about your data

    Returns:
        Query results with columns, rows, SQL used, and diagnostic metrics

    # TODO: Update this docstring to describe your specific data domain
    # The docstring is shown to the MCP client (e.g., Claude) and helps it
    # understand when and how to use this tool.
    """
    client_name = _get_client_name(ctx)

    result = execute_with_retry(
        question,
        data_semantic_context,
        data_tool_config,
        generate_sql,
        log_path=log_path,
        client_name=client_name
    )

    return _format_result(result)


@mcp.tool()
def query_logs(question: str, ctx: Context) -> dict:
    """
    Query the server's query logs using natural language.

    Args:
        question: A natural language question about query history and performance

    Returns:
        Query results with columns, rows, SQL used, and diagnostic metrics

    The query_log table tracks all NLQ-to-SQL attempts with:
    - request_id: Groups retry attempts for a single question
    - attempt_number: 1 = initial, 2+ = retry
    - timestamp: When the attempt occurred
    - client: MCP client name
    - nlq: Original natural language question
    - sql: Generated SQL
    - success: Whether SQL executed without error
    - error_message: Database error if failed
    - row_count: Rows returned if successful
    - execution_time_ms: Query execution time
    - input_tokens, output_tokens: LLM token usage
    """
    client_name = _get_client_name(ctx)

    result = execute_with_retry(
        question,
        log_semantic_context,
        log_tool_config,
        generate_sql,
        log_path=log_path,
        client_name=client_name
    )

    return _format_result(result)


if __name__ == "__main__":
    mcp.run()
