# HealthKit MCP Server — Project Specification

## Overview

An MCP server that enables natural language queries against Apple HealthKit data. Users ask questions in plain English via an MCP client (e.g., Claude Desktop); the server translates these to SQL using a local LLM, executes against a DuckDB database or Parquet file, and returns results with diagnostic metrics.

The server provides **two query tools**:
1. **query_data**: Query HealthKit data (health table)
2. **query_logs**: Query the server's own query logs for analysis and debugging

Each tool has independent configuration for LLM, database, and semantic layer.

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
     │  Health Parquet │ │   Log Database  │ │  Tool Configs   │
     │  (query_data)   │ │  (query_logs)   │ │  (per-tool LLM) │
     └─────────────────┘ └─────────────────┘ └─────────────────┘
```

## Core Flow

1. User asks a natural language question in the MCP client
2. MCP server receives the question and routes to appropriate tool
3. Tool builds prompt: schema DDL + auto-query results + static hints + question
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
| Database | DuckDB | Supports .duckdb files or Parquet |
| LLM Integration | LiteLLM | Provider-agnostic; supports 100+ LLMs |
| LLM Runtime | LM Studio (data) / Ollama (logs) | Local inference |
| MCP Client | Claude Desktop | Standard MCP protocol |

## Data Model

The health table is a flattened representation of Apple HealthKit data. All record types share the same schema, with the `type` column distinguishing record types.

### Record Classes

Records fall into four classes, each requiring different SQL aggregation:

| Class | Description | Aggregation | Example Types |
|-------|-------------|-------------|---------------|
| Cumulative | Additive within time period | SUM(value) | StepCount, ActiveEnergyBurned, DistanceWalkingRunning |
| Discrete | Independent point-in-time measurement | AVG/MIN/MAX(value) | HeartRate, RestingHeartRate, BodyMass, VO2Max |
| Event | Occurrence count | COUNT(*) | SleepAnalysis stages, HighHeartRateEvent |
| Workout | Single workout session | COUNT(*), SUM/AVG on duration_min, distance_km, energy_kcal | WorkoutCycling, WorkoutWalking, WorkoutPickleball |

The `classes.csv` file maps each `type` value to its class and correct SQL operation.

### Column Usage by Record Type

| Columns | Used By | Notes |
|---------|---------|-------|
| type, value, unit, start_date, end_date | Most metrics | Core measurement data |
| value_category | SleepAnalysis, AppleStandHour | Category instead of numeric value |
| duration_min, distance_km, energy_kcal | Workouts | Workout-specific metrics |
| start_lat, start_lon | Workouts | GPS starting location |

## Configuration

### Current Configuration (config.json)

```json
{
  "data_query": {
    "llm": {
      "model": "openai/qwen3-8b-mlx",
      "endpoint": "http://localhost:1234/v1",
      "api_key": "lm-studio",
      "no_think": true,
      "prompt_format": {
        "structure": "ddl-samples-hints-question",
        "hint_style": "sql_comment",
        "response_prefix": "SELECT"
      }
    },
    "database": {
      "parquet_path": "/path/to/health.parquet",
      "table_name": "health",
      "max_retries": 3
    },
    "semantic_layer": {
      "auto_queries": [...],
      "static_context": [...]
    }
  },
  "log_query": {
    "llm": {
      "model": "ollama/qwen2.5-coder:7b",
      "endpoint": "http://localhost:11434",
      "keep_alive": "15m",
      "no_think": true,
      "prompt_format": {...}
    },
    "database": {
      "db_path": "~/path/to/query_logs.duckdb",
      "table_name": "query_log",
      "max_retries": 1
    },
    "semantic_layer": {...}
  }
}
```

### LLM Configuration

| Setting | Description |
|---------|-------------|
| `model` | LiteLLM model string (e.g., `openai/qwen3-8b-mlx`, `ollama/qwen2.5-coder:7b`) |
| `endpoint` | API base URL for local LLMs |
| `api_key` | API key (or set via environment variable) |
| `no_think` | Disable thinking mode for qwen3 models |
| `keep_alive` | Ollama only: how long to keep model loaded |

### Prompt Format Options

| Setting | Description |
|---------|-------------|
| `hint_style` | How hints are formatted (`sql_comment`, `prose`, `json`) |
| `response_prefix` | Text to prime LLM response (e.g., `"SELECT"`) |

## Semantic Layer

The semantic layer provides context to the LLM for accurate SQL generation. It consists of:

### 1. Schema DDL (auto-generated)

Introspected from the data source at runtime:

```sql
CREATE TABLE health (
    type VARCHAR,
    value DOUBLE,
    ...
);
```

### 2. Auto Queries (config-driven)

SQL queries that run at startup, with labeled results injected into the prompt:

```json
"auto_queries": [
  {
    "label": "record class to type column mapping",
    "query": "SELECT MetricClass, TypeCode, SQLOperations FROM read_csv_auto('classes.csv')"
  }
]
```

### 3. Static Context (config-driven hints)

Domain knowledge organized into sections:

```
=== TABLE OVERVIEW ===
[Table structure, record classes, date column format]

=== DATABASE ENGINE ===
[DuckDB syntax notes]

=== NATURAL LANGUAGE TO TYPE MAPPINGS ===
['steps' = StepCount, 'heart rate' = HeartRate, etc.]
```

### Current Static Context (data_query)

```
=== TABLE OVERVIEW ===
The health table contains Apple HealthKit data flattened into a single table.
The table contains 4 classes of records:
*Cumulative: Multiple records are additive within a time period. Use SUM(value).
*Discrete: Each record is an independent point-in-time measurement. Use AVG(value), MIN(value), or MAX(value). Never SUM.
*Event: Records represent occurrences, not measurements. Use COUNT(*).
*Workout: Each record is a single workout session. Use COUNT(*) for number of workouts. Use SUM/AVG on duration_min, distance_km, energy_kcal for totals or averages. Workout types are stored as 'Workout' + activity name (e.g., WorkoutCycling, WorkoutWalking). Workout records also have start_lat and start_lon columns for GPS starting location.
The 'type' column maps to Class (see classes.csv) which determines the correct aggregation.
Date columns are start_date and end_date, stored as VARCHAR in 'YYYY-MM-DD HH:MM:SS' format. Cast to TIMESTAMP or DATE for comparisons.

=== DATABASE ENGINE ===
DuckDB syntax only.

=== NATURAL LANGUAGE TO TYPE MAPPINGS ===
'steps' = StepCount
'heart rate' or 'HR' or 'pulse' = HeartRate
'cycling' or 'bike ride' = WorkoutCycling
'HIIT' or 'interval training' = WorkoutHighIntensityIntervalTraining
[... additional mappings for 20 workout types ...]
```

## Prompt Construction

The final prompt sent to the SQL-generating LLM includes:

1. **Schema DDL** — Table structure
2. **Auto Query Results** — Labeled CSV data (e.g., class mappings)
3. **Static Hints** — Domain knowledge as SQL comments
4. **Query Rules** — Including today's date (injected dynamically)
5. **Question** — The user's natural language query
6. **Response Prefix** — Primes the LLM to start with SELECT

Example query rules section:
```
/* Query Rules */
-- Today's date is: 2026-01-08
-- Return ONLY a valid DuckDB SQL SELECT statement
-- The table is named: health
```

## MCP Response Structure

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
        "output_tokens": int,
        "elapsed_ms": int
    }
}
```

## Query Logging

All query attempts are logged to the query_logs database:

| Column | Description |
|--------|-------------|
| request_id | Groups retry attempts for a single question |
| attempt_number | 1 = initial, 2+ = retry |
| timestamp | When the attempt occurred |
| client | MCP client name |
| nlq | Natural language question |
| sql | Generated SQL |
| success | Whether SQL executed without error |
| error_message | Database error if failed |
| row_count | Rows returned if successful |
| input_tokens | Tokens sent to LLM |
| output_tokens | Tokens received from LLM |
| elapsed_ms | Cumulative time since tool was called |
| sql_generator_llm | LLM model used |
| sql_generating_llm_prompt | Full prompt sent to LLM |

Use the `query_logs` tool to analyze failures and improve the semantic layer.

## File Structure

```
healthkit-mcp-v4/
├── config.json           # All configuration (per-tool)
├── server.py             # MCP server with two tools
├── semantic_layer.py     # Context builder
├── llm_client.py         # LLM communication via LiteLLM
├── query_executor.py     # SQL execution + retry logic
├── query_logger.py       # Audit logging
├── classes.csv           # Class → TypeCode → SQLOperations mapping
├── query_logs.duckdb     # Query attempt logs
└── PROJECT_SPEC.md       # This file
```

## Design Principles

1. **Start simple** — Add complexity only when logs show specific failures
2. **Config over code** — Semantic layer tuning happens in config.json
3. **Let logs guide improvements** — Use query_logs to identify what's failing
4. **Lean prompts** — Minimize tokens while maintaining accuracy
5. **Dynamic date injection** — LLM always knows today's date
6. **Labeled auto-queries** — LLM understands what reference data means

## Change Log

### 2026-01-09: Added Workout Class to Semantic Layer

**Summary**: Extended the semantic layer to properly handle workout records as a distinct fourth record class.

**Changes made**:

1. **config.json — TABLE OVERVIEW section**:
   - Changed "3 classes" to "4 classes"
   - Added Workout class description with guidance on columns (duration_min, distance_km, energy_kcal, start_lat, start_lon) and aggregation patterns

2. **config.json — NATURAL LANGUAGE TO TYPE MAPPINGS section**:
   - Added 7 new mappings: HIIT, elliptical, core training, cooldown, skiing, rowing, pilates

3. **classes.csv**:
   - Added all 20 workout types found in the data with MetricClass=Workout and SQLOperations=COUNT/SUM/AVG

**Test queries** (run via Claude Desktop to verify LLM generates correct SQL):

| Query | Expected Behavior |
|-------|-------------------|
| "How many cycling workouts did I do last month?" | COUNT(*) with type='WorkoutCycling' |
| "What was my total cycling distance in 2024?" | SUM(distance_km) with type='WorkoutCycling' |
| "Average duration of my HIIT workouts" | AVG(duration_min) with type='WorkoutHighIntensityIntervalTraining' |
| "How many calories did I burn in pickleball this year?" | SUM(energy_kcal) with type='WorkoutPickleball' |
| "Show my elliptical workouts from December" | SELECT with type='WorkoutElliptical' and date filter |
| "List workouts near Austin" | Uses start_lat/start_lon with coordinate bounding box |
