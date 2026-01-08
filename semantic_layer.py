import json
import duckdb
from pathlib import Path


def load_config(config_path: str = None) -> dict:
    if config_path is None:
        # Get the directory where this script lives
        script_dir = Path(__file__).parent
        config_path = script_dir / "config.json"

    with open(config_path, "r") as f:
        return json.load(f)


def _get_data_source(tool_config: dict) -> tuple[duckdb.DuckDBPyConnection, str, str]:
    """
    Determine data source from tool config and return connection, query target, and table name.

    Supports two modes:
    - db_path: Connect to a DuckDB database file, query tables directly
    - parquet_path: Connect in-memory, query parquet file by path

    Args:
        tool_config: A tool-specific config section (e.g., config["data_query"])

    Returns:
        (connection, query_target, table_name)
        - query_target: What to use in FROM clause (table name or file path)
        - table_name: The table name for LLM prompts
    """
    db_config = tool_config["database"]
    table_name = db_config.get("table_name", "")

    # Check for DuckDB database file first
    db_path = db_config.get("db_path", "")
    if db_path:
        db_path = Path(db_path).expanduser()
        con = duckdb.connect(str(db_path))

        # Auto-discover table if not specified
        if not table_name:
            tables = con.execute("SHOW TABLES").fetchall()
            if len(tables) == 1:
                table_name = tables[0][0]
            elif len(tables) == 0:
                raise ValueError(f"No tables found in database: {db_path}")
            else:
                table_names = [t[0] for t in tables]
                raise ValueError(f"Multiple tables found, specify table_name in config: {table_names}")

        return con, table_name, table_name

    # Fall back to parquet file
    parquet_path = db_config.get("parquet_path", "")
    if parquet_path:
        parquet_path = str(Path(parquet_path).expanduser())
        con = duckdb.connect()
        table_name = table_name or "data"
        return con, f"'{parquet_path}'", table_name

    raise ValueError("Tool config must specify either 'db_path' or 'parquet_path' in database section")


def build_semantic_context(tool_config: dict) -> dict:
    """
    Build semantic context with automatic schema introspection.

    Args:
        tool_config: A tool-specific config section (e.g., config["data_query"])

    Returns a dict with separate components that llm_client can assemble
    into the optimal prompt structure for the configured LLM.
    """

    prompt_format = tool_config["llm"].get("prompt_format", {})

    con, query_target, table_name = _get_data_source(tool_config)

    # Update config with discovered table name (for downstream use)
    tool_config["database"]["table_name"] = table_name

    context = {
        "schema_ddl": "",
        "column_info": [],
        "hints": []
    }

    # 1. Auto-introspect schema and generate DDL
    try:
        schema_query = f"DESCRIBE SELECT * FROM {query_target}"
        columns = con.execute(schema_query).fetchall()

        ddl_lines = [f"CREATE TABLE {table_name} ("]
        context["column_info"] = []

        for i, col in enumerate(columns):
            col_name = col[0]
            col_type = col[1]
            context["column_info"].append({"name": col_name, "type": col_type})

            comma = "," if i < len(columns) - 1 else ""
            ddl_lines.append(f"    {col_name} {col_type}{comma}")

        ddl_lines.append(");")
        context["schema_ddl"] = "\n".join(ddl_lines)
    except Exception as e:
        context["schema_ddl"] = f"-- Schema introspection failed: {e}"

    # 2. Run any custom auto-queries from config
    auto_queries = tool_config["semantic_layer"].get("auto_queries", [])
    context["auto_query_results"] = []
    for query_config in auto_queries:
        # Support both string (legacy) and dict format
        if isinstance(query_config, str):
            query_template = query_config
            label = None
        else:
            query_template = query_config["query"]
            label = query_config.get("label")
        
        try:
            query = query_template.replace("{query_target}", query_target).replace("{table_name}", table_name)
            # Also support legacy placeholder
            query = query.replace("{parquet_path}", query_target)
            cursor = con.execute(query)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            context["auto_query_results"].append({
                "query": query_template,
                "label": label,
                "columns": columns,
                "rows": rows
            })
        except Exception as e:
            context["auto_query_results"].append({
                "query": query_template,
                "label": label,
                "error": str(e)
            })

    # 3. Add static hints from config
    context["hints"] = tool_config["semantic_layer"].get("static_context", [])

    con.close()
    return context


def format_context_for_prompt(context: dict, tool_config: dict = None) -> str:
    """
    Format the semantic context based on LLM prompt format configuration.

    Args:
        context: The semantic context dict from build_semantic_context
        tool_config: A tool-specific config section (e.g., config["data_query"])

    Default format follows Qwen2.5-Coder's text-to-SQL training structure:
    DDL -> Samples -> Hints -> Question
    """

    prompt_format = {}
    if tool_config:
        prompt_format = tool_config["llm"].get("prompt_format", {})

    hint_style = prompt_format.get("hint_style", "sql_comment")

    parts = []

    # Schema as DDL
    parts.append("/* Table Schema */")
    parts.append(context["schema_ddl"])

    # Auto query results (dynamic context from config-defined queries)
    if context.get("auto_query_results"):
        for result in context["auto_query_results"]:
            if "error" in result:
                parts.append(f"\n/* Auto query failed: {result['error']} */")
            else:
                # Use label if provided, otherwise generic header
                label = result.get("label") or "Auto Query Result"
                parts.append(f"\n/* {label} */")
                columns = result["columns"]
                rows = result["rows"]
                parts.append(",".join(columns))
                for row in rows:
                    csv_values = []
                    for val in row:
                        if val is None:
                            csv_values.append("")
                        elif isinstance(val, str):
                            escaped = val.replace('"', '""')
                            csv_values.append(f'"{escaped}"')
                        else:
                            csv_values.append(str(val))
                    parts.append(",".join(csv_values))

    # Domain hints
    if context.get("hints"):
        parts.append("\n/* Important Notes */")
        for hint in context["hints"]:
            if hint_style == "sql_comment":
                parts.append(f"-- {hint}")
            else:
                parts.append(hint)

    return "\n".join(parts)


if __name__ == "__main__":
    # Test the semantic layer for both tools
    config = load_config()

    print("=== DATA QUERY SEMANTIC CONTEXT ===")
    try:
        data_context = build_semantic_context(config["data_query"])
        data_formatted = format_context_for_prompt(data_context, config["data_query"])
        print(data_formatted)
    except Exception as e:
        print(f"Data query context failed (expected if no data configured): {e}")

    print("\n\n=== LOG QUERY SEMANTIC CONTEXT ===")
    try:
        log_context = build_semantic_context(config["log_query"])
        log_formatted = format_context_for_prompt(log_context, config["log_query"])
        print(log_formatted)
    except Exception as e:
        print(f"Log query context failed (expected if no logs exist yet): {e}")
