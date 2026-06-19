# DragonMaid

This is DragonMaid version 1, a secure, lightweight personal AI assistant. It provides low-overhead task automation, scheduling, local memory consolidation, and terminal action handling.

Designed for small LLMs (such as `granite4.1:8b`), DragonMaid aims to be fast and safe without the resource strain of heavy multi-agent frameworks.

## Security & Philosophy

- **Human-in-the-Loop (HITL) Gatekeeper**: No execution of Python scripts or terminal commands takes place autonomously. Whether you use the local CLI terminal or Telegram, DragonMaid prompts you for manual approval.
- **Minimal Dependencies**: Relies solely on Python's standard library and the lightweight `requests` package.
- **Docker-Isolated by Default**: Safe terminal tasks and Python evaluations are container-isolated.
- **Direct Host Access**: Includes optional direct host command execution tools that strictly require critical-level user confirmation before launching.

---


## Installation

### Prerequisites
- **Python 3.10+**
- **Docker** (For sandbox environments)
- **Ollama** or any OpenAI-compliant API wrapper running locally.

### Setup
work in progress...


## Commands
work in progress...
