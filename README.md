# NLQ-to-SQL MCP Server Template

A template for building MCP servers that enable natural language queries against structured data. Clone this repo, point it at your data, and start querying.

## Features

- **Two query tools**: Query your data AND query server logs using natural language
- **Per-tool configuration**: Each tool has its own LLM, database, and semantic layer settings
- **Provider-agnostic LLM**: Use local (Ollama) or cloud (Anthropic, OpenAI) LLMs via LiteLLM
- **Automatic schema introspection**: DDL, sample data, and categorical values discovered at startup
- **Query logging**: All attempts logged for analysis and semantic layer refinement

## Quick Start

1. **Clone this template**
   ```bash
   git clone <this-repo> my-data-mcp
   cd my-data-mcp
   ```

2. **Install dependencies**
   ```bash
   pip install duckdb litellm mcp
   ```

3. **Ensure Ollama is running** (or configure a cloud LLM)
   ```bash
   ollama pull qwen2.5-coder:7b
   ollama serve
   ```

4. **Update `config.json`**
   - In `data_query.database`: Set `db_path` or `parquet_path` to your data
   - In `log_query.database`: Set `db_path` for query logs
   - Optionally configure different LLMs per tool

5. **Test the semantic layer**
   ```bash
   python semantic_layer.py
   ```
   Review the auto-introspected schema and sample data.

6. **Test SQL generation**
   ```bash
   python llm_client.py
   ```

7. **Run the MCP server**
   ```bash
   python server.py
   ```

8. **Configure Claude Desktop** to connect to your server

## Configuration Structure

Each tool has its own complete configuration:

```json
{
  "data_query": {
    "llm": { ... },
    "database": { ... },
    "semantic_layer": { ... }
  },
  "log_query": {
    "llm": { ... },
    "database": { ... },
    "semantic_layer": { ... }
  }
}
```

### Per-Tool LLM Configuration

Each tool can use a different LLM provider:

**Local (Ollama):**
```json
"llm": {
  "model": "ollama/qwen2.5-coder:7b",
  "endpoint": "http://localhost:11434",
  "api_key": ""
}
```

**Anthropic:**
```json
"llm": {
  "model": "anthropic/claude-sonnet-4-5-20250929",
  "endpoint": "",
  "api_key": "sk-ant-..."
}
```

**OpenAI:**
```json
"llm": {
  "model": "gpt-4",
  "endpoint": "",
  "api_key": "sk-..."
}
```

API keys can also be set via environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.).

### Per-Tool Database Configuration

**data_query** - Your domain data:
```json
"database": {
  "parquet_path": "/path/to/data.parquet",
  "db_path": "",
  "table_name": "data",
  "max_retries": 3
}
```

**log_query** - Query logs (fixed schema):
```json
"database": {
  "db_path": "~/path/to/query_logs.duckdb",
  "table_name": "query_log",
  "max_retries": 1
}
```

### Per-Tool Semantic Layer

Each tool has its own `semantic_layer` section with `auto_queries` and `static_context` tailored to its data.

## Tools

### query_data

Queries your domain data. Update the docstring in `server.py` to describe your specific data.

### query_logs

Queries the server's query log table. Useful for:
- Analyzing success/failure rates
- Finding questions that need better semantic hints
- Tracking token usage and costs
- Debugging query patterns

## Customization

### Essential: Update `config.json`

- **`data_query.semantic_layer.static_context`**: Add domain-specific mappings and hints
- **`data_query.database`**: Point to your data file
- **LLM settings**: Configure local or cloud LLM per tool

### Optional: Customize server.py

- Change the server name: `FastMCP("your-domain")`
- Update the `query_data` docstring to describe your data
- Rename tools if desired

## Files

| File | Purpose |
|------|---------|
| `config.json` | All configuration (per-tool LLM, database, semantic layer) |
| `server.py` | MCP server entry point with two tools |
| `semantic_layer.py` | Auto-introspects schema, builds prompt context |
| `llm_client.py` | LLM communication via LiteLLM |
| `query_executor.py` | SQL execution, retry logic |
| `query_logger.py` | Audit logging |
| `PROJECT_SPEC.md` | Full architecture documentation |

## Query Logging

All queries from both tools are logged to the `log_query.database.db_path` file with:
- Request ID (groups retries)
- Natural language question
- Generated SQL
- Success/failure + error messages
- Token counts per attempt
- Execution time

Query the logs using the `query_logs` tool to analyze patterns and refine your semantic layer.

## License

[Your license here]
