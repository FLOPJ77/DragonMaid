# DragonMaid House — Local LLM Agent Framework

DragonMaid House is a lightweight, secure Python framework designed to run local LLMs via Ollama on macOS (Apple Silicon M3) and Linux (Debian). It coordinates a lead orchestrator agent (**House Dragonmaid**) and a roster of specialized sub-agents (**Chamber, Parlor, Kitchen, Nurse, Laundry**) capable of executing tasks autonomously and concurrently.

---

## Features
- **Local Ollama Integration**: Runs completely locally with minimal external dependencies.
- **Secure Sandboxed Workspace**: Restricts file system tools to a designated jail directory (`workspace/`).
- **Parallel Sub-Agent Spawning**: Orchestrates concurrent thread-based workers when the lead agent delegates subtasks.
- **Dream Mode (Consolidation)**: Automatically synthesizes context, decisions, and tasks into `knowledge.md` during periods of inactivity.
- **Background Reminders**: Supports relative and absolute scheduling for both the user and the agent itself.
- **Dual Interfaces**: Native colored CLI and a whitelisted, long-polling Telegram bot.

---

## Setup Instructions

### Prerequisites
- Python 3.9+
- Ollama running locally. Ensure you have pulled a suitable small model (e.g. `granite4.1:3b`, `qwen2.5-coder:3b`, `gemma3:4b`):
  ```bash
  ollama pull granite4.1:3b
  ```

### Installation

#### macOS & Linux
1. Clone the repository and navigate into it:
   ```bash
   git clone https://github.com/your-username/dragonmaid.git
   cd dragonmaid
   ```
2. Set up the virtual environment (if not already done):
   ```bash
   python3 -m venv myenv
   source myenv/bin/activate
   pip install -r requirements.txt
   ```
   *(Note: The only dependency is `requests` to keep the codebase lightweight and audit-friendly.)*

3. Configure environment variables in `.env` (see section below).

---

## Configuration (`.env`)

Create a `.env` file in the root directory (or copy from `.env.example`):

```env
# Ollama Connection Parameters
API_KEY=ollama
API_URL=http://localhost:11434/v1/chat/completions
MODEL=granite4.1:3b

# Telegram Configuration
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
ALLOWED_USER_ID=your_telegram_user_id  # Numeric ID of owner (comma-separate for multiple)

# Security Controls
ALLOW_HOST_EXECUTION=false  # Set true to enable bash/python commands on the host
WORKSPACE_DIR=./workspace
```

---

## Running the Framework

Start the application:
```bash
./myenv/bin/python src/main.py
```
This launches the interactive CLI in the main terminal, starts the reminders checker and Dream Mode activity monitor in the background, and runs the Telegram bot listener (if a bot token is provided).

---

## Chat Commands
Commands work in both the CLI and Telegram:
- `/help` — List available commands.
- `/model <name>` — Switch the active Ollama model on the fly.
- `/host [on/off]` — Enable/disable or toggle host execution (shell/python commands) on the fly.
- `/dream` — Trigger Dream Mode immediately to update `knowledge.md`.
- `/status` — Show the active model, uptime, configurations, and pending reminders.
- `/clear` — Clear the current chat context and unload the model from RAM.
- `/stop` — Unload the model from memory and graceful shutdown.

---

## Tool Calling Format

Tools expect JSON code blocks. The system prompt instructs models to output tool calls in the following structure:

```json
{
  "tool": "tool_name",
  "args": {
    "arg1": "value"
  }
}
```

### Available Tools
1. **`file_manager`**: Manage files within the workspace.
   - Args: `{"action": "list"|"read"|"write"|"delete", "path": "filename", "content": "file data"}`
2. **`bash_exec`**: Execute terminal scripts (sandbox restricted).
   - Args: `{"command": "cmd"}`
3. **`python_exec`**: Execute python code (sandbox restricted).
   - Args: `{"code": "python snippet"}`
4. **`web_search`**: Lightweight search querying Wikipedia and DuckDuckGo.
   - Args: `{"query": "search query"}`
5. **`time_inject`**: Returns the current time.
   - Args: `{}`
6. **`reminders`**: Set timer alerts.
   - Args: `{"action": "schedule"|"list"|"cancel", "time": "in 5m"|"18:30", "message": "msg", "recipient": "user"|"agent"}`

---

## Agent Roster

- **House Dragonmaid** (Orchestrator) — Runs the main loop and routes complex tasks to sub-agents.
- **Chamber Dragonmaid** (CI/CD) — Environment setups, Ansible, and Git operations.
- **Parlor Dragonmaid** (Network) — Nginx, DNS BIND9, firewall rules, and packet captures.
- **Kitchen Dragonmaid** (SysAdmin) — DB optimization, Docker management, and system stats.
- **Nurse Dragonmaid** (Security) — Audit logs, vulnerability audits, repairs, and backups.
- **Laundry Dragonmaid** (Cleanup) — File rotation, sanitization, caches, and Windows PowerShell.
