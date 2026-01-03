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
      "model": "ollama/qwen2.5-coder:7b",
      "endpoint": "http://localhost:11434",
      "api_key": "",
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
      "model": "ollama/qwen2.5-coder:7b",
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
        "success: TRUE if SQL executed without error."
      ]
    }
  }
}
```

### Per-Tool LLM Configuration

Uses [LiteLLM](https://github.com/BerriAI/litellm) for provider-agnostic LLM calls. Each tool can use a different provider.

| Setting | Description |
|---------|-------------|
| `model` | LiteLLM model string (e.g., `ollama/qwen2.5-coder:7b`, `anthropic/claude-sonnet-4-5-20250929`, `gpt-4`) |
| `endpoint` | API base URL (required for Ollama, ignored for cloud providers) |
| `api_key` | API key (or set via environment: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.) |

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
    "model": "ollama/qwen2.5-coder:7b",
    "endpoint": "http://localhost:11434"
  }
}
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
    - success, error_message, row_count, execution_time_ms
    - input_tokens, output_tokens: LLM token usage
    """
```

## Semantic Layer

A hybrid approach provides the LLM with data context:

### Auto-Generated (SQL-driven, built at startup)

- Schema introspection (column names, types)
- Distinct values for categorical columns
- Date range of data
- Sample data rows (formatted as CSV for clarity)

### Manually Curated (config-driven)

- Database engine syntax notes
- Natural language → database value mappings
- Aggregation rules (SUM vs AVG)
- Common query patterns
- Domain-specific disambiguation
- Query rules (e.g., "Don't filter unless explicitly mentioned")

Each tool has its own semantic layer configuration in its `semantic_layer` section.

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
| nlq | VARCHAR | Original natural language question |
| sql | VARCHAR | Generated SQL |
| success | BOOLEAN | Whether SQL executed without error |
| error_message | VARCHAR | Database error if failed |
| row_count | INTEGER | Rows returned if successful |
| execution_time_ms | INTEGER | Query execution time |
| input_tokens | INTEGER | Tokens sent to LLM for this attempt |
| output_tokens | INTEGER | Tokens received from LLM for this attempt |

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
└── [data files]          # DuckDB, Parquet, or CSV files
```

## Appendix: Sample Static Context Categories

Adapt these categories for your domain's `data_query.semantic_layer.static_context`:

```
=== DATABASE ENGINE ===
[Syntax notes, function names specific to your DB]

=== SCHEMA ===
[Table and column descriptions]

=== DATE HANDLING ===
[Date formats, casting requirements, common date patterns]

=== QUERY RULES ===
Do not filter on columns unless the question explicitly mentions them.
[Other behavioral guidance for the LLM]

=== TYPE/CATEGORY MAPPINGS ===
[Natural language synonyms → actual database values]

=== AGGREGATION RULES ===
[Which metrics to SUM vs AVG, special calculations]

=== COMMON QUERY PATTERNS ===
[Proven SQL patterns for frequent question types]

=== OUTPUT GUIDELINES ===
[Column aliasing, rounding, ordering conventions]
```
