# NLQ-to-SQL MCP Server — Project Specification Template

## Overview

An MCP server that enables natural language queries against structured data. Users ask questions in plain English via an MCP client (e.g., Claude Desktop); the server translates these to SQL using a local or cloud LLM, executes against a database, and returns results with diagnostic metrics.

The server provides **two query tools**:
1. **query_data**: Query your domain-specific data
2. **query_logs**: Query the server's own query logs for analysis and debugging

Each tool has independent configuration for LLM, database, and semantic layer.

This pattern is applicable to any domain with structured, queryable data: health metrics, sales data, IoT telemetry, financial records, operational logs, etc.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   MCP Client    │────▶│   MCP Server    │────▶│   SQL Builder   │
│ (Claude Desktop)│◀────│    (Python)     │◀────│   LLM (LiteLLM) │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
     ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
     │   Data Database │ │   Log Database  │ │  Tool Configs   │
     │  (query_data)   │ │  (query_logs)   │ │  (per-tool LLM) │
     └─────────────────┘ └─────────────────┘ └─────────────────┘
```

**Components:**

| Component | Role |
|-----------|------|
| MCP Client | User interface; sends natural language questions, displays results |
| MCP Server | Orchestrates flow; manages two tools with independent configs |
| SQL Builder LLM | Translates NLQ to SQL; configurable per tool via LiteLLM |
| Data Database | Your domain data; queried by query_data tool |
| Log Database | Query attempt logs; queried by query_logs tool |
| Tool Configs | Per-tool LLM, database, and semantic layer settings |

## Core Flow

1. User asks a natural language question in the MCP client
2. MCP server receives the question and routes to appropriate tool
3. Tool builds prompt: tool-specific semantic context + question
4. Tool sends prompt to its configured LLM via LiteLLM
5. LLM returns a SQL SELECT statement
6. Server sanitizes SQL (fixes common LLM generation errors)
7. Server executes SQL against the tool's database
8. If SQL fails, error is sent back to LLM for revision (up to N retries per tool config)
9. Server logs the attempt to the log database
10. Server returns query results + diagnostic metrics to MCP client
11. MCP client (Claude) formulates the final answer for the user

## Technical Stack

| Component | Technology | Notes |
|-----------|------------|-------|
| Language | Python | |
| MCP Framework | FastMCP | Simplifies MCP server implementation |
| Database | DuckDB | Supports .duckdb files or Parquet/CSV |
| LLM Integration | LiteLLM | Provider-agnostic; supports 100+ LLMs |
| LLM Runtime | Ollama / OpenAI / Anthropic / etc. | Configurable per tool |
| MCP Client | Claude Desktop | Standard MCP protocol; swappable |

## Data Sources

Each tool supports two data source types:

### DuckDB Database File
```json
"database": {
  "db_path": "~/path/to/data.duckdb",
  "table_name": ""
}
```
- Connects read-only to an existing DuckDB database
- `table_name` auto-discovered if database has exactly one table
- Best for: Data already in DuckDB, or the log database

### Parquet File
```json
"database": {
  "parquet_path": "/path/to/data.parquet",
  "table_name": "data"
}
```
- Creates in-memory DuckDB connection with a view to the file
- `table_name` becomes the view name (required, defaults to "data")
- Best for: Single-file data exports, columnar analytics data

## Configuration

JSON configuration file stored in the project root. Structure with per-tool sections:

```json
{
  "data_query": {
    "llm": {
      "model": "ollama/qwen3:8b",
      "endpoint": "http://localhost:11434",
      "api_key": "",
      "keep_alive": "15m",
      "prompt_format": {
        "structure": "ddl-samples-hints-question",
        "include_sample_rows": true,
        "sample_row_count": 8,
        "hint_style": "sql_comment",
        "response_prefix": "SELECT"
      }
    },
    "database": {
      "db_path": "",
      "parquet_path": "",
      "table_name": "",
      "max_retries": 3
    },
    "semantic_layer": {
      "auto_queries": [],
      "static_context": [
        "=== DATABASE ENGINE ===",
        "DuckDB syntax only.",
        
        "=== QUERY RULES ===",
        "Do not filter on columns unless the question explicitly mentions them.",
        
        "=== TYPE/CATEGORY MAPPINGS ===",
        "[Natural language term] → [database value]",
        
        "=== AGGREGATION RULES ===",
        "[Which columns to SUM vs AVG, special handling notes]"
      ]
    }
  },
  "log_query": {
    "llm": {
      "model": "ollama/qwen3:8b",
      "endpoint": "http://localhost:11434",
      "api_key": "",
      "prompt_format": { ... }
    },
    "database": {
      "db_path": "~/path/to/query_logs.duckdb",
      "table_name": "query_log",
      "max_retries": 1
    },
    "semantic_layer": {
      "auto_queries": [],
      "static_context": [
        "=== SCHEMA PURPOSE ===",
        "This table logs all NLQ-to-SQL query attempts.",
        
        "=== KEY COLUMNS ===",
        "request_id: Groups retry attempts for a single question.",
        "attempt_number: 1 = initial, 2+ = retry.",
        "user_input: Raw input from user in client app.",
        "success: TRUE if SQL executed without error.",
        "elapsed_ms: Cumulative time since tool was called."
      ]
    }
  }
}
```

### Per-Tool LLM Configuration

Uses [LiteLLM](https://github.com/BerriAI/litellm) for provider-agnostic LLM calls. Each tool can use a different provider.

| Setting | Description |
|---------|-------------|
| `model` | LiteLLM model string (e.g., `ollama/qwen3:8b`, `anthropic/claude-sonnet-4-5-20250929`, `gpt-4`) |
| `endpoint` | API base URL (required for Ollama, ignored for cloud providers) |
| `api_key` | API key (or set via environment: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.) |
| `keep_alive` | Ollama only: how long to keep model loaded (e.g., `"15m"`, `"1h"`, `"0"` to unload immediately) |

**Example: Local for logs, cloud for data queries:**

```json
"data_query": {
  "llm": {
    "model": "anthropic/claude-sonnet-4-5-20250929",
    "api_key": "sk-ant-..."
  }
},
"log_query": {
  "llm": {
    "model": "ollama/qwen3:8b",
    "endpoint": "http://localhost:11434",
    "keep_alive": "15m"
  }
}
```

### LLM Model Selection (Local/Ollama)

For local LLM deployment on Apple Silicon (16GB RAM), we tested several models for text-to-SQL accuracy and instruction-following. The key issue was models adding unsolicited WHERE clauses (e.g., filtering by `source_name`) when the semantic layer explicitly says "Do not filter on columns unless the question explicitly mentions them."

**Benchmark Results (5 test queries, Mac M4 16GB):**

| Model | Accuracy | Avg Time | Avg Tokens | Notes |
|-------|----------|----------|------------|-------|
| qwen2.5-coder:7b | 3/5 (60%) | ~24s | ~55 | Fast but ignores "don't filter" instruction |
| qwen3:8b (thinking) | 4/5 (80%) | ~85s | ~1100 | Better instruction-following, slow |
| **qwen3:8b (/no_think)** | **5/5 (100%)** | **~62s** | **~650** | **Best accuracy, reasonable speed** |

**Recommendation:** Use `ollama/qwen3:8b` with `/no_think` prefix in prompts for best instruction-following. The thinking mode improves reasoning but adds significant latency.

**Other models considered:**
- `duckdb-nsql:7b` — Purpose-built for DuckDB, but trained on schema→SQL patterns, not semantic layer instructions
- `sqlcoder:15b` — Requires 16GB+ RAM, marginal benefit over qwen3:8b
- `qwen2.5-coder:14b` — Larger version of 7b, may fit with Q4 quantization

### Ollama Performance Tuning

By default, Ollama unloads models after 5 minutes of idle time. For MCP servers with intermittent queries, this causes slow cold starts (~5-10s model load time).

**Solution:** Set `keep_alive` in config.json to keep model loaded between requests:

```json
"llm": {
  "model": "ollama/qwen3:8b",
  "endpoint": "http://localhost:11434",
  "keep_alive": "15m",
  ...
}
```

**Implementation note:** LiteLLM doesn't pass `keep_alive` directly to Ollama. Use `extra_body` in llm_client.py:

```python
# In llm_client.py - LiteLLM requires extra_body for Ollama-specific params
keep_alive = tool_config["llm"].get("keep_alive")
if keep_alive:
    kwargs["extra_body"] = {"keep_alive": keep_alive}
```

To manually unload a model:
```bash
ollama stop qwen3:8b
```

To check what's currently loaded:
```bash
ollama ps
```

### LLM Prompt Format Options

The `prompt_format` section controls how the semantic context is assembled:

| Setting | Options | Description |
|---------|---------|-------------|
| `structure` | `ddl-samples-hints-question` | Order of prompt components |
| `include_sample_rows` | `true`/`false` | Whether to include example data rows |
| `sample_row_count` | integer | Number of sample rows to include |
| `hint_style` | `sql_comment`, `prose`, `json` | How hints are formatted |
| `response_prefix` | string (e.g., `"SELECT"`) | Text to prime the LLM's response |

## MCP Tools

### query_data

Queries your domain-specific data. Customize the docstring in `server.py` to describe your data.

```python
@mcp.tool()
def query_data(question: str, ctx: Context) -> dict:
    """
    Query data using natural language.
    # TODO: Update this docstring for your domain
    """
```

### query_logs

Queries the server's query log table. Fixed schema, pre-configured semantic layer.

```python
@mcp.tool()
def query_logs(question: str, ctx: Context) -> dict:
    """
    Query the server's query logs using natural language.
    
    The query_log table tracks all NLQ-to-SQL attempts with:
    - request_id: Groups retry attempts for a single question
    - attempt_number: 1 = initial, 2+ = retry
    - user_input: Raw input from user in client app
    - success, error_message, row_count, execution_time_ms
    - input_tokens, output_tokens: LLM token usage
    - elapsed_ms: Cumulative time since tool was called
    - sql_generator_llm: LLM model used to generate the SQL
    """
```

## Semantic Layer

The semantic layer provides context to the LLM for accurate SQL generation. It has three components:

### 1. Auto Queries (SQL-driven, run at startup)

SQL queries defined in `auto_queries` that run at startup and inject results into the prompt:

```json
"auto_queries": [
  "SELECT MetricClass, TypeCode, SQLOperations FROM read_csv_auto('metric_classes.csv')",
  "SELECT DISTINCT type, unit FROM {query_target} WHERE unit IS NOT NULL",
  "SELECT type, COUNT(*) as row_count FROM {query_target} GROUP BY type"
]
```

- Schema introspection (column names, types) — built-in
- Sample data rows — built-in
- Metric class lookups from CSV files via DuckDB's `read_csv_auto()`
- Distinct values, date ranges, row counts — custom queries

### 2. Metric Classes CSV (reference data)

A CSV file mapping data types to their aggregation behavior:

```csv
MetricClass,TypeCode,SQLOperations
Cumulative,StepCount,SUM
Discrete,HeartRate,AVG/MIN/MAX
Event,HighHeartRateEvent,COUNT
```

**MetricClass definitions:**
- **Cumulative**: Additive within time period. Use `SUM(value)`.
- **Discrete**: Independent point-in-time measurement. Use `AVG/MIN/MAX(value)`. Never SUM.
- **Event**: Occurrence count. Use `COUNT(*)`. Value column is NULL or irrelevant.

Loaded via auto query: `SELECT * FROM read_csv_auto('metric_classes.csv')`

### 3. Static Context (config-driven hints)

Domain knowledge the LLM can't infer from data:

```json
"static_context": [
  "=== DATE HANDLING ===",
  "For 'today': WHERE CAST(start_date AS DATE) = CURRENT_DATE",
  
  "=== NATURAL LANGUAGE MAPPINGS ===",
  "'steps' = StepCount",
  "'heart rate' = HeartRate"
]
```

Keep static context focused on:
- Database engine syntax
- Date/time patterns
- Natural language → type mappings (aliases)
- Domain-specific logic (e.g., sleep stages, workout handling)

## MCP Response Structure

Each response includes:

```python
{
    "success": bool,
    "columns": ["col1", "col2", ...],
    "rows": [[val1, val2, ...], ...],
    "row_count": int,
    "diagnostics": {
        "sql": "SELECT ...",
        "retry_count": int,
        "errors": [{"sql": "...", "error": "..."}],
        "input_tokens": int,
        "output_tokens": int
    }
}
```

## Query Logging

All query attempts from both tools are logged to the `log_query.database.db_path` database:

| Column | Type | Description |
|--------|------|-------------|
| request_id | VARCHAR | Groups retry attempts for a single question |
| attempt_number | INTEGER | 1 for initial, 2+ for retries |
| timestamp | TIMESTAMP | When the attempt occurred |
| client | VARCHAR | MCP client name |
| user_input | VARCHAR | Raw input from user in client app |
| nlq | VARCHAR | Natural language question passed to tool |
| sql | VARCHAR | Generated SQL |
| success | BOOLEAN | Whether SQL executed without error |
| error_message | VARCHAR | Database error if failed |
| row_count | INTEGER | Rows returned if successful |
| execution_time_ms | INTEGER | Query execution time (DuckDB only) |
| input_tokens | INTEGER | Tokens sent to LLM for this attempt |
| output_tokens | INTEGER | Tokens received from LLM for this attempt |
| elapsed_ms | INTEGER | Cumulative time since tool was called |
| sql_generator_llm | VARCHAR | LLM model used to generate the SQL |

**Uses:**
- Identify common failure patterns → refine semantic layer
- Track success rate over time
- Analyze which question types need better hints
- Audit trail for debugging
- Query logs using the `query_logs` tool!

## SQL Sanitization

Common LLM generation errors to catch before execution:

| Error Pattern | Fix |
|---------------|-----|
| `SELECT WITH cte AS` | Remove leading `SELECT` |
| Multiple trailing semicolons | Reduce to single or none |
| Markdown code fences | Strip ``` wrappers |
| Trailing explanations | Truncate at explanation markers |

## Key Design Decisions

1. **Two tools with independent configs**: query_data for domain data, query_logs for server analysis
2. **Per-tool LLM configuration**: Use local LLM for logs, cloud for complex data queries
3. **Per-tool retry settings**: Logs need fewer retries (fixed schema)
4. **LiteLLM for provider flexibility**: Single interface to 100+ LLM providers
5. **Shared log database**: Both tools log to the same database for unified analysis
6. **Semantic layer as prompt engineering**: Most "tuning" happens in config, not code
7. **Protocol-based client**: MCP standard allows swapping frontends without server changes

## Implementation Checklist

- [ ] Define data schema and prepare data file/database
- [ ] Create initial config.json with both tool configurations
- [ ] Configure data_query LLM and database settings
- [ ] Configure log_query database path
- [ ] Customize data_query semantic layer hints
- [ ] Test with representative questions; refine semantic layer
- [ ] Use query_logs tool to analyze failures and improve hints

## File Structure

```
project-root/
├── config.json           # All configuration (per-tool)
├── server.py             # MCP server with two tools
├── semantic_layer.py     # Context builder (per-tool)
├── llm_client.py         # LLM communication via LiteLLM
├── query_executor.py     # SQL execution + retry logic
├── query_logger.py       # Audit logging
├── metric_classes.csv    # MetricClass → TypeCode → SQLOperations mapping
└── [data files]          # DuckDB, Parquet, or CSV files
```

## Appendix: Static Context Categories

After implementing metric classes via CSV, keep static_context focused on domain knowledge:

```
=== METRIC CLASS DEFINITIONS ===
[Brief description of Cumulative, Discrete, Event]

=== DATABASE ENGINE ===
[Syntax notes specific to your DB]

=== DATE HANDLING ===
[Date formats, casting, common patterns like 'today', 'last week']

=== DOMAIN-SPECIFIC LOGIC ===
[Sleep stages, workout handling, special column semantics]

=== NATURAL LANGUAGE MAPPINGS ===
[Aliases: 'steps' = StepCount, 'HR' = HeartRate]
```

Aggregation rules (SUM vs AVG) are now handled by the metric_classes.csv lookup.