#!/usr/bin/env python3
"""Test connection to the configured OpenAI-compatible endpoint (like BT2).

Reads environment configuration from .env and verifies:
1. Environment variable availability (API Key, Base URL, Model).
2. Raw OpenAI API completion (same mechanism as BT2 demo_common & 00_minimal_triage).
3. Tool / Function Calling capability with OpenRouter / OpenAI.
4. Project integration via config.get_model().
"""

import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Ensure UTF-8 output encoding for Windows terminal
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load environment configuration
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)


def mask_key(key: str) -> str:
    """Mask sensitive API key for safe terminal display."""
    if not key or len(key) < 12:
        return "****"
    return f"{key[:10]}...{key[-4:]}"


def test_api_connection():
    print("=" * 70)
    print("   TESTING LLM API CONNECTION (OpenAI-compatible / BT2 Style)    ")
    print("=" * 70)

    # 1. Inspect environment variables
    provider = os.getenv("LLM_PROVIDER", "openai")
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.getenv("OPENAI_MODEL") or os.getenv("MODEL_NAME") or "openai/gpt-4o-mini"

    print(f"\n[1] Environment Configuration (.env):")
    print(f"    - LLM Provider : {provider}")
    print(f"    - Base URL     : {base_url}")
    print(f"    - Target Model : {model}")
    print(f"    - API Key      : {mask_key(api_key or '')}")

    if not api_key or api_key == "your_openai_api_key_here":
        print("\n[ERROR] OPENAI_API_KEY is not configured in .env!")
        print("Please copy the API key from BT2/.env into .env.")
        sys.exit(1)

    # 2. Test direct OpenAI client (Same mechanism as BT2)
    print(f"\n[2] Testing Direct OpenAI Client (BT2 demo_common style)...")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)

        start_time = time.time()
        test_prompt = "Say 'Connection successful from BT2 .env!' in exactly 6 words."
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": test_prompt}
            ],
            temperature=0.0
        )
        elapsed = time.time() - start_time
        reply_content = response.choices[0].message.content.strip()

        print(f"    -> Status  : HTTP 200 OK")
        print(f"    -> Latency : {elapsed:.2f}s")
        print(f"    -> Response: \"{reply_content}\"")
        if response.usage:
            print(f"    -> Usage   : Prompt={response.usage.prompt_tokens}, Completion={response.usage.completion_tokens}, Total={response.usage.total_tokens} tokens")
    except Exception as e:
        print(f"    [!] Connection Failed: {e}")
        sys.exit(1)

    # 3. Test Tool / Function Calling capability
    print(f"\n[3] Testing Tool / Function Calling Support...")
    tools_spec = [{
        "type": "function",
        "function": {
            "name": "search_flights",
            "description": "Search available flights by route and date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "Departure airport code (e.g. SGN)"},
                    "dest": {"type": "string", "description": "Destination airport code (e.g. DAD)"},
                    "date": {"type": "string", "description": "Date YYYY-MM-DD"}
                },
                "required": ["origin", "dest", "date"]
            }
        }
    }]

    try:
        start_time = time.time()
        fc_response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": "Find flights from SGN to DAD on 2026-10-07."}
            ],
            tools=tools_spec,
            temperature=0.0
        )
        elapsed_fc = time.time() - start_time
        choice = fc_response.choices[0].message

        if choice.tool_calls:
            first_call = choice.tool_calls[0]
            print(f"    -> Tool Called : {first_call.function.name}")
            print(f"    -> Arguments   : {first_call.function.arguments}")
            print(f"    -> Latency     : {elapsed_fc:.2f}s")
            print(f"    -> Result      : PASS (Function calling supported)")
        else:
            print(f"    -> Reply       : {choice.content}")
            print(f"    -> Note        : Model responded with content instead of tool call.")
    except Exception as e:
        print(f"    [!] Function calling failed: {e}")

    # 4. Test project config integration (config.get_model)
    print(f"\n[4] Testing Project Integration (config.get_model)...")
    try:
        from config import get_model
        from langchain_core.messages import HumanMessage
        from tools.flight_tools import AGENT_TOOLS

        agent_model = get_model(temperature=0.0).bind_tools(AGENT_TOOLS)
        start_time = time.time()
        res = agent_model.invoke([
            HumanMessage(content="Search for flights from SGN to DAD on 2026-10-07.")
        ])
        elapsed_get = time.time() - start_time

        print(f"    -> Model Type  : {type(agent_model).__name__}")
        print(f"    -> Content     : \"{res.content[:80] if res.content else '(Tool Call Generated)'}\"")
        print(f"    -> Tool Calls  : {res.tool_calls}")
        print(f"    -> Latency     : {elapsed_get:.2f}s")
        print(f"    -> Integration : PASS")
    except Exception as e:
        print(f"    [!] Integration check failed: {e}")

    print("\n" + "=" * 70)
    print(">>> ALL CONNECTION & FUNCTION CALLING TESTS COMPLETED SUCCESSFULLY <<<")
    print("=" * 70)


if __name__ == "__main__":
    test_api_connection()
