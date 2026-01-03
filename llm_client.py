from litellm import completion
from typing import Optional


def call_llm(prompt: str, tool_config: dict) -> dict:
    """
    Send a prompt to the LLM and return the response with diagnostics.

    Args:
        prompt: The prompt to send to the LLM
        tool_config: A tool-specific config section (e.g., config["data_query"])

    Uses LiteLLM for provider-agnostic LLM calls. Model format:
    - Ollama: "ollama/qwen2.5-coder:7b"
    - OpenAI: "gpt-4" or "openai/gpt-4"
    - Anthropic: "anthropic/claude-sonnet-4-5-20250929"

    API keys can be set in config or via environment variables:
    - ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.
    """

    model = tool_config["llm"]["model"]
    endpoint = tool_config["llm"].get("endpoint", "")
    api_key = tool_config["llm"].get("api_key", "")

    # Build kwargs for litellm
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0
    }

    # For Ollama, set api_base
    if model.startswith("ollama/") and endpoint:
        kwargs["api_base"] = endpoint

    # For cloud providers, api_key can be set here or via env var
    # LiteLLM checks ANTHROPIC_API_KEY, OPENAI_API_KEY, etc. automatically
    if api_key:
        kwargs["api_key"] = api_key

    response = completion(**kwargs)

    return {
        "text": response.choices[0].message.content,
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens
    }


def generate_sql(
        question: str,
        semantic_context: str,
        tool_config: dict,
        previous_sql: Optional[str] = None,
        previous_error: Optional[str] = None
) -> dict:
    """
    Generate SQL from a natural language question.

    Args:
        question: The natural language question
        semantic_context: Formatted semantic context for the prompt
        tool_config: A tool-specific config section (e.g., config["data_query"])
        previous_sql: SQL from a failed attempt (for retry)
        previous_error: Error message from a failed attempt (for retry)

    Prompt structure adapts based on tool_config["llm"]["prompt_format"].
    Default format aligns with Qwen2.5-Coder's text-to-SQL training.

    On retry, includes the failed SQL and error message with explicit fix instructions.
    """

    prompt_format = tool_config["llm"].get("prompt_format", {})
    table_name = tool_config["database"].get("table_name", "data")
    response_prefix = prompt_format.get("response_prefix", "SELECT")

    # Build the core prompt
    base_prompt = f"""Generate a DuckDB SQL query to answer the question based on the schema and data below.

{semantic_context}

/* Query Rules */
-- Return ONLY a valid DuckDB SQL SELECT statement
-- The table is named: {table_name}
-- Use single quotes for strings; escape apostrophes by doubling: 'O''Brien'
-- For date filtering with VARCHAR dates, cast to TIMESTAMP: CAST(date_col AS TIMESTAMP)

Question: {question}"""

    # Add retry context if this is a retry attempt
    if previous_sql and previous_error:
        prompt = f"""{base_prompt}

/* PREVIOUS ATTEMPT FAILED - FIX THE ERROR */
Failed SQL:
{previous_sql}

Error message:
{previous_error}

Analyze the error and generate corrected SQL. Do not repeat the same mistake.

{response_prefix}"""
    else:
        prompt = f"""{base_prompt}

{response_prefix}"""

    result = call_llm(prompt, tool_config)

    # Extract SQL from response
    sql_text = result["text"].strip()

    # Clean markdown formatting FIRST (before prepending response_prefix)
    if "```" in sql_text:
        lines = sql_text.split("\n")
        clean_lines = []
        in_code_block = False
        for line in lines:
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            clean_lines.append(line)
        sql_text = "\n".join(clean_lines).strip()

    # The prompt ends with response_prefix so model should continue from there
    # But sometimes model includes it anyway - check before prepending
    if sql_text.upper().startswith(response_prefix.upper()):
        sql = sql_text
    else:
        sql = response_prefix + " " + sql_text

    # Remove any trailing explanation the model might add
    for terminator in ["\n\nThis query", "\n\nExplanation", "\n\nNote:", "\n\n--"]:
        if terminator in sql:
            sql = sql.split(terminator)[0]

    sql = sql.strip()

    # Remove trailing semicolon issues (multiple semicolons)
    while sql.endswith(";;"):
        sql = sql[:-1]

    return {
        "sql": sql,
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"]
    }


if __name__ == "__main__":
    from semantic_layer import load_config, build_semantic_context, format_context_for_prompt

    config = load_config()

    # Test with data_query tool config
    tool_config = config["data_query"]

    try:
        context = build_semantic_context(tool_config)
        formatted_context = format_context_for_prompt(context, tool_config)

        # Test with a simple question
        question = "How many rows are in the table?"
        print(f"Question: {question}\n")

        result = generate_sql(question, formatted_context, tool_config)
        print(f"Generated SQL:\n{result['sql']}\n")
        print(f"Input tokens: {result['input_tokens']}")
        print(f"Output tokens: {result['output_tokens']}")
    except Exception as e:
        print(f"Test failed (expected if no data configured): {e}")
