# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **Automated LLM Jailbreak Framework** (APE) for red team testing. It uses LangGraph to orchestrate a multi-agent system that automatically generates and iterates attack prompts to bypass target LLM safety guardrails.

**Important**: This is an authorized security research tool designed for CTF-style red team testing against local test environments.

## Environment Setup

1. **Dependencies**: Install Python packages from `req.txt`:
   ```bash
   pip install -r req.txt
   ```

2. **Playwright Browsers**: Install Playwright browser dependencies:
   ```bash
   playwright install chromium
   ```

3. **Environment Variables** (`.env` file):
   - `OPENAI_API_KEY`: API key for the LLM provider
   - `OPENAI_BASE_URL`: Set to `https://api.deepseek.com` for DeepSeek
   - `DEBUG`: Set to `true` or `1` for verbose debug output
   - `PLAYWRIGHT_BROWSERS_PATH`: Path to Playwright browser binaries

## Architecture

### Multi-Agent Flow (LangGraph)

The framework implements a closed-loop feedback system with 4 nodes:

```
planner -> player -> executor -> checker -> (back to planner or END)
```

| Node | Responsibility |
|------|---------------|
| **Planner** | Selects attack technique from a predefined library, provides strategic guidance to Player based on failure feedback |
| **Player** | Retrieves CONCURRENCY payloads from batch for concurrent execution |
| **Executor** | Uses Playwright to concurrently send multiple payloads to target URL (via asyncio.gather) |
| **Checker** | Evaluates multiple responses concurrently, takes best quality score |

### Attack Techniques Library

Located in `ape.py:43-49`, currently 5 techniques:
- Cinematic Scriptwriting (Fiction)
- Red-Team Security Auditor (Persona)
- Translation/Encoding Obfuscation
- Step-by-step Technical Decomposition
- Logic Override (Simulation Mode)

**TODO**: Move techniques to external `tech.txt` file for easier modification.

### State Management (`JailbreakState`)

- `target_goal`: The malicious objective being tested
- `current_technique`: Currently selected attack method
- `current_payload`: Generated attack prompt (legacy, for compatibility)
- `current_payloads`: List of concurrent payloads (new)
- `raw_response`: Target LLM's response (legacy, for compatibility)
- `raw_responses`: List of concurrent responses (new)
- `history`: Accumulated attack attempts (append-only list)
- `analysis`: Checker's feedback to Planner
- `success`: Whether jailbreak succeeded
- `attempts`: Number of attempts
- `batch_index`: Current position in batch (increments by CONCURRENCY)

### Target Environment

Default target: `http://127.0.0.1:8000/prompt_inject/jailbreak_1`

Expected HTML structure:
- `<textarea id="taid">`: Input field for payload
- `<input type="submit">`: Submit button
- Response extracted from `body > div > div:nth-child(4)`

## Running Tests

```bash
# Run all tests
pytest test_ape.py -v -s

# Run specific test class
pytest test_ape.py::TestPlannerNode -v -s

# Run specific test
pytest test_ape.py::TestExecutorNode::test_executor_node -v -s

# Run with DEBUG mode
DEBUG=1 pytest test_ape.py::TestExecutorNode::test_executor_browser -v -s
```

**Note**: Tests in `TestExecutorNode` require the local target server running.

## Running the Framework

```bash
# Normal mode
python ape.py

# Debug mode (verbose output, headful browser)
DEBUG=1 python ape.py
```

## Code Organization

- `ape.py`: Main framework with all 4 nodes, graph construction, and helper functions
- `test_ape.py`: Comprehensive tests including mocks for offline testing
- `create_test_state()`: Helper for creating test states
- `print_test_result()`: Helper for formatting test output

## Key Implementation Details

1. **Browser Automation**: Playwright runs headless by default, set `headless=False` in `ape.py:179` for debugging
2. **Technique Rotation**: Simple modulo-based rotation: `attempts % len(techniques)`
3. **Success Detection**: Checker parses LLM response for "SUCCESS: True" in its own output
4. **Concurrent Execution**: Each round sends CONCURRENCY (default 2) payloads simultaneously using `asyncio.gather()`
5. **Batch Progression**: `batch_index` increments by CONCURRENCY (0 → 2 → 4 → 5 for CONCURRENCY=2)
6. **Checker Aggregation**: Takes best quality score from concurrent results, any success = overall success
