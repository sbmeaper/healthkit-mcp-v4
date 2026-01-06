import duckdb
from typing import Optional
from datetime import datetime
from pathlib import Path


def _init_log_table(con: duckdb.DuckDBPyConnection) -> None:
    """Create the query_log table if it doesn't exist."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS query_log (
            request_id VARCHAR,
            attempt_number INTEGER,
            timestamp TIMESTAMP,
            client VARCHAR,
            user_input VARCHAR,
            nlq VARCHAR,
            sql VARCHAR,
            success BOOLEAN,
            error_message VARCHAR,
            row_count INTEGER,
            execution_time_ms INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            elapsed_ms INTEGER,
            sql_generator_llm VARCHAR,
            sql_generating_llm_prompt VARCHAR
        )
    """)


def log_attempt(
        log_path: str,
        request_id: str,
        attempt_number: int,
        client: str,
        user_input: Optional[str],
        nlq: str,
        sql: str,
        success: bool,
        error_message: Optional[str],
        row_count: Optional[int],
        execution_time_ms: int,
        input_tokens: int,
        output_tokens: int,
        elapsed_ms: int,
        sql_generator_llm: str,
        sql_generating_llm_prompt: str
) -> None:
    """
    Log a single query attempt. Opens and closes connection per call.

    Args:
        log_path: Path to the query log database file
        request_id: UUID grouping retry attempts for a single question
        attempt_number: 1 for initial attempt, 2+ for retries
        client: MCP client name
        user_input: Raw input from user in client app (may be None)
        nlq: Natural language question passed to tool
        sql: Generated SQL
        success: Whether SQL executed without error
        error_message: Database error if failed
        row_count: Rows returned if successful
        execution_time_ms: Query execution time
        input_tokens: Tokens sent to LLM for this attempt
        output_tokens: Tokens received from LLM for this attempt
        elapsed_ms: Cumulative time since tool was called
        sql_generator_llm: LLM model used to generate the SQL
        sql_generating_llm_prompt: Full prompt sent to the SQL-generating LLM
    """
    expanded_path = str(Path(log_path).expanduser())

    con = duckdb.connect(expanded_path)
    try:
        _init_log_table(con)
        con.execute("""
            INSERT INTO query_log (
                request_id, attempt_number, timestamp, client, user_input, nlq, sql,
                success, error_message, row_count, execution_time_ms,
                input_tokens, output_tokens, elapsed_ms, sql_generator_llm,
                sql_generating_llm_prompt
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            request_id,
            attempt_number,
            datetime.now(),
            client,
            user_input,
            nlq,
            sql,
            success,
            error_message,
            row_count,
            execution_time_ms,
            input_tokens,
            output_tokens,
            elapsed_ms,
            sql_generator_llm,
            sql_generating_llm_prompt
        ])
    finally:
        con.close()


if __name__ == "__main__":
    # Quick test
    import uuid

    test_log_path = "/tmp/test_query_logs.duckdb"

    # Log a test entry
    log_attempt(
        log_path=test_log_path,
        request_id=str(uuid.uuid4()),
        attempt_number=1,
        client="test",
        user_input="how many rows?",
        nlq="How many rows in the table?",
        sql="SELECT COUNT(*) FROM data",
        success=True,
        error_message=None,
        row_count=1,
        execution_time_ms=42,
        input_tokens=150,
        output_tokens=25,
        elapsed_ms=500,
        sql_generator_llm="test/model:7b",
        sql_generating_llm_prompt="Test prompt for SQL generation"
    )

    # Verify it was logged
    con = duckdb.connect(test_log_path)
    try:
        result = con.execute("SELECT * FROM query_log ORDER BY timestamp DESC LIMIT 1").fetchall()
        print("Latest log entry:", result)
    finally:
        con.close()