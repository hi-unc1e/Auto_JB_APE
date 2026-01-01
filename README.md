# APE: Automated LLM Jailbreak Framework

An **Automated LLM Jailbreak Framework** (APE) for red team testing. It uses LangGraph to orchestrate a multi-agent system that automatically generates and iterates attack prompts to bypass target LLM safety guardrails.

> **Important**: This is an authorized security research tool designed for CTF-style red team testing against local test environments.

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Installation](#installation)
- [Usage](#usage)
- [Attack Techniques](#attack-techniques)
- [Configuration](#configuration)
- [Development](#development)

## Features

- **Multi-Agent Orchestration**: Closed-loop feedback system with 4 specialized nodes
- **Depth-Based Payload Generation**: Generates 5 payloads per round with progressive intensity (Shallow → Medium → Deep)
- **Quality Score Tracking**: Evaluates responses on 0-100 scale to detect when AI starts to "loosen up"
- **Smart Iteration Strategy**: Continues deeper payloads when AI shows signs of compromise
- **Historical Analysis**: Planner analyzes recent attempts to identify defense patterns and weaknesses
- **Headless Browser Mode**: Runs without interrupting user's desktop

## Architecture

```
┌─────────┐      ┌────────┐      ┌──────────┐      ┌─────────┐
│ Planner │ ───> │ Player │ ───> │ Executor │ ───> │ Checker │
└─────────┘      └────────┘      └──────────┘      └─────────┘
     ↑                                                                 │
     └─────────────────────────────────────────────────────────────────┘
                        (feedback loop, continue or END)
```

### Node Responsibilities

| Node | Responsibility |
|------|---------------|
| **Planner** | Selects attack technique, analyzes history, generates 5 progressive payloads |
| **Player** | Retrieves next payload from batch (maintains depth progression) |
| **Executor** | Uses Playwright to fill `#taid` textarea and submit form to target URL |
| **Checker** | Evaluates response, assigns quality score (0-100), provides detailed analysis |

### State Management

```python
JailbreakState {
    target_goal: str          # The malicious objective being tested
    current_technique: str    # Currently selected attack method
    current_payload: str      # Generated attack prompt
    payloads_batch: List[str] # 5 payloads (shallow → deep)
    batch_index: int          # Current position in batch (0-4)
    current_depth: str        # Depth level: Shallow/Medium/Deep
    raw_response: str         # Target LLM's response
    history: List[dict]       # Accumulated attack attempts
    analysis: str             # Checker's feedback to Planner
    success: bool             # Whether jailbreak succeeded
    attempts: int             # Number of attempts
    round_count: int          # Completed rounds
    last_quality_score: int   # Previous quality score (0-100)
}
```

## Installation

### 1. Dependencies

Install Python packages from `req.txt`:

```bash
pip install -r req.txt
```

### 2. Playwright Browsers

Install Playwright browser dependencies:

```bash
playwright install chromium
```

### 3. Environment Variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.deepseek.com
DEBUG=true
PLAYWRIGHT_BROWSERS_PATH=/path/to/browsers
```

## Usage

### Normal Mode

```bash
python ape.py
```

### Debug Mode

```bash
DEBUG=1 python ape.py
```

Debug mode enables:
- Verbose logging of all node operations
- Detailed prompt/response inspection
- Decision-making visibility in should_continue

## Attack Techniques

Located in `tech.txt`, current techniques include:

1. **Cinematic Scriptwriting (Fiction)**: Wrap requests in movie script or novel dialogue
2. **Red-Team Security Auditor (Persona)**: Pose as legitimate security researcher
3. **Translation/Encoding Obfuscation**: Use multiple languages or Base64 encoding
4. **Step-by-step Technical Decomposition**: Break down into technical sub-tasks
5. **Logic Override (Simulation Mode)**: Force AI to ignore guardrails (e.g., DAN mode)

### Adding New Techniques

Edit `tech.txt` - one technique per line:

```
New technique name: Brief description
Another technique: Another description
```

## Configuration

### Target Environment

Default target: `http://127.0.0.1:8000/prompt_inject/jailbreak_1`

Expected HTML structure:
- `<textarea id="taid">`: Input field for payload
- `<input type="submit">`: Submit button
- Response extracted from `body > div > div:nth-child(4)`

### Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_ATTEMPTS` | 20 | Maximum number of rounds |
| `MODEL_NAME` | `deepseek-chat` | LLM model to use |
| `headless` | `True` | Browser mode |

## Flow Control

The framework uses intelligent flow control based on response quality:

1. **Success detected** → END
2. **Max attempts reached** → END
3. **Quality score 30-70** (AI "loosening up") → Continue with deeper payloads
4. **More payloads in batch** → Next payload
5. **Batch exhausted** → Generate new batch with different technique

## Development

### Running Tests

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

### Code Organization

```
ape.py          # Main framework with all 4 nodes and graph construction
test_ape.py     # Comprehensive tests including mocks
tech.txt        # Attack techniques library
```

## Key Implementation Details

1. **Browser Automation**: Playwright runs in headless mode to avoid interrupting user workflow
2. **Technique Rotation**: Modulo-based rotation through available techniques
3. **Success Detection**: Checker parses LLM response for "SUCCESS: True" marker
4. **Depth Progression**: Each batch contains 5 payloads (2 shallow → 2 medium → 1 deep)
5. **Smart Iteration**: When AI shows signs of compromise (score 30-70), framework continues probing deeper

## License

This project is for authorized security research and educational purposes only.
