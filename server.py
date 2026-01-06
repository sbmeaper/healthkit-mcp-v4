import time
from typing import Optional
from mcp.server.fastmcp import FastMCP, Context
from semantic_layer import load_config, build_semantic_context, format_context_for_prompt
from query_executor import execute_with_retry
from llm_client import generate_sql

# Initialize MCP server
mcp = FastMCP("healthkit")

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
        "rows": result["rows"][:1000] if result["rows"] else None,  # Limit rows returned
        "row_count": result["row_count"],
        "diagnostics": {
            "sql": result["sql"],
            "retry_count": result["retry_count"],
            "errors": result["errors"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "elapsed_ms": result["elapsed_ms"]
        }
    }


@mcp.tool()
def query_data(question: str, user_input: Optional[str] = None, ctx: Context = None) -> dict:
    """
    Query Apple HealthKit data using natural language.

    Args:
        question: A natural language question about health metrics
        user_input: Raw input from user in client app (for logging)

    Returns:
        Query results with columns, rows, SQL used, and diagnostic metrics

    Includes: steps, distance, heart rate, sleep, workouts, body measurements, nutrition, and other Apple Health metrics.

    Location data: Workouts store GPS coordinates (start_lat, start_lon) for starting location only—city/state/country names are NOT stored. When the user asks about workouts in a named location, translate the place name to a coordinate bounding box before querying. Examples:
    - "Boston" → start_lat BETWEEN 42.2 AND 42.5 AND start_lon BETWEEN -71.3 AND -70.8
    - "Austin" → start_lat BETWEEN 30.1 AND 30.5 AND start_lon BETWEEN -97.9 AND -97.5
    - "New York City" → start_lat BETWEEN 40.5 AND 40.9 AND start_lon BETWEEN -74.3 AND -73.7
    """
    start_time = time.perf_counter()
    client_name = _get_client_name(ctx)

    result = execute_with_retry(
        question,
        data_semantic_context,
        data_tool_config,
        generate_sql,
        log_path=log_path,
        start_time=start_time,
        client_name=client_name,
        user_input=user_input
    )

    return _format_result(result)


@mcp.tool()
def query_logs(question: str, user_input: Optional[str] = None, ctx: Context = None) -> dict:
    """
    Query the server's query logs using natural language.

    Args:
        question: A natural language question about query history and performance
        user_input: Raw input from user in client app (for logging)

    Returns:
        Query results with columns, rows, SQL used, and diagnostic metrics

    The query_log table tracks all NLQ-to-SQL attempts with:
    - request_id: Groups retry attempts for a single question
    - attempt_number: 1 = initial, 2+ = retry
    - timestamp: When the attempt occurred
    - client: MCP client name
    - user_input: Raw input from user in client app
    - nlq: Natural language question passed to tool
    - sql: Generated SQL
    - success: Whether SQL executed without error
    - error_message: Database error if failed
    - row_count: Rows returned if successful
    - execution_time_ms: Query execution time
    - input_tokens, output_tokens: LLM token usage
    - elapsed_ms: Cumulative time since tool was called
    """
    start_time = time.perf_counter()
    client_name = _get_client_name(ctx)

    result = execute_with_retry(
        question,
        log_semantic_context,
        log_tool_config,
        generate_sql,
        log_path=log_path,
        start_time=start_time,
        client_name=client_name,
        user_input=user_input
    )

    return _format_result(result)


if __name__ == "__main__":
    mcp.run()
