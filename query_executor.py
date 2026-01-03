import duckdb
import uuid
import time
from pathlib import Path
from typing import Optional, Callable
from query_logger import log_attempt

# Connection cache keyed by (db_path or parquet_path, table_name)
_connections: dict[tuple, duckdb.DuckDBPyConnection] = {}


def get_connection(tool_config: dict) -> duckdb.DuckDBPyConnection:
    """
    Get or create a persistent DuckDB connection for a tool.

    Args:
        tool_config: A tool-specific config section (e.g., config["data_query"])

    Supports two modes:
    - db_path: Connect directly to a DuckDB database file
    - parquet_path: Create in-memory connection with a view to the parquet file
    """
    global _connections

    db_config = tool_config["database"]
    table_name = db_config.get("table_name", "data")

    # Check for DuckDB database file first
    db_path = db_config.get("db_path", "")
    if db_path:
        db_path = str(Path(db_path).expanduser())
        cache_key = ("db", db_path, table_name)

        if cache_key not in _connections:
            _connections[cache_key] = duckdb.connect(db_path, read_only=True)

        return _connections[cache_key]

    # Fall back to parquet file with view
    parquet_path = db_config.get("parquet_path", "")
    if parquet_path:
        parquet_path = str(Path(parquet_path).expanduser())
        cache_key = ("parquet", parquet_path, table_name)

        if cache_key not in _connections:
            con = duckdb.connect()
            # Create a view so LLM can reference table name instead of full path
            con.execute(f"""
                CREATE OR REPLACE VIEW {table_name} AS 
                SELECT * FROM '{parquet_path}'
            """)
            _connections[cache_key] = con

        return _connections[cache_key]

    raise ValueError("Tool config must specify either 'db_path' or 'parquet_path' in database section")


def sanitize_sql(sql: str) -> str:
    """Fix common LLM SQL generation errors before execution."""
    sql = sql.strip()

    # Fix: LLM sometimes generates "SELECT WITH cte AS ..." instead of "WITH cte AS ..."
    if sql.upper().startswith('SELECT WITH'):
        sql = sql[7:]  # Remove "SELECT "

    return sql


def execute_query(sql: str, tool_config: dict) -> dict:
    """
    Execute SQL against the data view and return results with metadata.

    Args:
        sql: SQL query to execute
        tool_config: A tool-specific config section (e.g., config["data_query"])
    """

    con = get_connection(tool_config)

    # Sanitize SQL before execution
    sql = sanitize_sql(sql)

    start_time = time.perf_counter()
    try:
        result = con.execute(sql).fetchall()
        columns = [desc[0] for desc in con.description]
        execution_time_ms = int((time.perf_counter() - start_time) * 1000)

        return {
            "success": True,
            "columns": columns,
            "rows": result,
            "row_count": len(result),
            "error": None,
            "execution_time_ms": execution_time_ms
        }
    except Exception as e:
        execution_time_ms = int((time.perf_counter() - start_time) * 1000)
        return {
            "success": False,
            "columns": None,
            "rows": None,
            "row_count": 0,
            "error": str(e),
            "execution_time_ms": execution_time_ms
        }
    # Note: no finally/close - we keep the connection alive


def execute_with_retry(
        question: str,
        semantic_context: str,
        tool_config: dict,
        generate_sql_fn: Callable,
        log_path: str,
        client_name: str = "unknown"
) -> dict:
    """
    Execute a query with LLM-assisted retry on failure.

    Args:
        question: Natural language question
        semantic_context: Formatted semantic context for the LLM
        tool_config: A tool-specific config section (e.g., config["data_query"])
        generate_sql_fn: Function to generate SQL from question
        log_path: Path to the query log database
        client_name: Name of the MCP client
    """

    request_id = str(uuid.uuid4())
    max_retries = tool_config["database"]["max_retries"]
    errors = []
    total_input_tokens = 0
    total_output_tokens = 0

    previous_sql = None
    previous_error = None

    for attempt in range(max_retries + 1):
        # Generate SQL (with error context on retry)
        llm_result = generate_sql_fn(
            question,
            semantic_context,
            tool_config,
            previous_sql=previous_sql,
            previous_error=previous_error
        )
        sql = llm_result["sql"]
        attempt_input_tokens = llm_result["input_tokens"]
        attempt_output_tokens = llm_result["output_tokens"]

        total_input_tokens += attempt_input_tokens
        total_output_tokens += attempt_output_tokens

        # Execute the query
        query_result = execute_query(sql, tool_config)

        # Log this attempt with per-attempt token counts
        log_attempt(
            log_path=log_path,
            request_id=request_id,
            attempt_number=attempt + 1,
            client=client_name,
            nlq=question,
            sql=sql,
            success=query_result["success"],
            error_message=query_result["error"],
            row_count=query_result["row_count"] if query_result["success"] else None,
            execution_time_ms=query_result["execution_time_ms"],
            input_tokens=attempt_input_tokens,
            output_tokens=attempt_output_tokens
        )

        if query_result["success"]:
            return {
                "success": True,
                "columns": query_result["columns"],
                "rows": query_result["rows"],
                "row_count": query_result["row_count"],
                "sql": sql,
                "retry_count": attempt,
                "errors": errors,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens
            }

        # Query failed - save for retry context
        errors.append({"sql": sql, "error": query_result["error"]})
        previous_sql = sql
        previous_error = query_result["error"]

    # All retries exhausted
    return {
        "success": False,
        "columns": None,
        "rows": None,
        "row_count": 0,
        "sql": sql,
        "retry_count": max_retries,
        "errors": errors,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens
    }


if __name__ == "__main__":
    from semantic_layer import load_config, build_semantic_context, format_context_for_prompt
    from llm_client import generate_sql

    config = load_config()
    tool_config = config["data_query"]
    log_path = config["log_query"]["database"]["db_path"]

    try:
        context = build_semantic_context(tool_config)
        formatted_context = format_context_for_prompt(context, tool_config)

        # Test with a simple question
        question = "How many rows are in the table?"
        print(f"Question: {question}\n")

        result = execute_with_retry(
            question,
            formatted_context,
            tool_config,
            generate_sql,
            log_path=log_path,
            client_name="test_harness"
        )

        if result["success"]:
            print(f"Columns: {result['columns']}")
            print(f"Rows: {result['rows']}")
            print(f"SQL: {result['sql']}")
            print(f"Retries: {result['retry_count']}")
            print(f"Total tokens: {result['input_tokens']} in, {result['output_tokens']} out")
        else:
            print(f"Query failed after {result['retry_count']} retries")
            print(f"Errors: {result['errors']}")
    except Exception as e:
        print(f"Test failed (expected if no data configured): {e}")
