
<img width="900" alt="Dragonmaid" src="https://github.com/user-attachments/assets/64c5759b-f637-4a49-bdf0-82a809725c6c" />

# 🌸 DragonMaid — Local LLM Agent Framework 🌸

DragonMaid is a lightweight, secure Python framework designed to run local LLMs via Ollama on macOS and Linux (Debian). It coordinates the lead orchestrator agent **House Dragonmaid** and a roster of specialized sub-agents **Chamber, Parlor, Kitchen, Nurse, Laundry** capable of executing tasks autonomously and concurrently.

<br>

## Agent Roster

- **🌸 House Dragonmaid** (Orchestrator) — Runs the main loop and routes complex tasks to sub-agents.
- **🧹 Chamber Dragonmaid** (CI/CD) — Environment setups, Ansible, and Git operations.
- **🛋️ Parlor Dragonmaid** (Network) — Apache, DNS BIND9, firewall rules, and packet captures.
- **🍳 Kitchen Dragonmaid** (SysAdmin) — DB optimization, Docker management, and system stats.
- **🩺 Nurse Dragonmaid** (Security) — Audit logs, vulnerability audits, repairs, and backups.
- **🧺 Laundry Dragonmaid** (Cleanup) — File rotation, sanitization, caches, and Windows PowerShell.


<br>



## Features
- **Local Ollama Integration**: Runs completely locally with minimal external dependencies.
- **Secure Sandboxed Workspace**: Restricts file system tools to a designated jail directory (`workspace/`).
- **Parallel Sub-Agent Spawning**: Orchestrates concurrent thread-based workers when the lead agent delegates subtasks.
- **Dream Mode (Consolidation)**: Automatically synthesizes context, decisions, and tasks into `knowledge.md` during periods of inactivity.
- **Background Reminders**: Supports relative and absolute scheduling for both the user and the agent itself.
- **Dual Interfaces**: Native colored CLI and a whitelisted, long-polling Telegram bot.

<br>

> [!WARNING]
> Be carefoul with it, it still an AI agent that can touch and run command directly on the machine.



<br>


## Setup Instructions

### Prerequisites
- Python 3.9+
- Ollama running locally. Ensure you have pulled a suitable small model (e.g. `granite4.1:3b`, `qwen2.5-coder:3b`, `gemma3:4b`):

  ```bash
  ollama pull granite4.1:3b
  ```
> [!NOTE]
> If you have enough RAM to run bigger model like `granite4.1:8b` dont hesitate to do it because it is a way better.
> You can find more info about small local LLM here [AI Local Models](https://github.com/FLOPJ77/Guides/blob/main/ai_local_models.md) 


### Installation

#### macOS & Linux
1. Clone the repository and navigate into it:
   ```bash
   git clone https://github.com/FLOPJ77/DragonMaid.git
   cd dragonmaid
   ```
2. Set up the virtual environment (if not already done):
   ```bash
   python3 -m venv myenv
   source myenv/bin/activate
   pip install requests
   ```
   *(Note: The only dependency is `requests` to keep the codebase lightweight and audit-friendly.)*

3. Configure environment variables in `.env` (see section below).


<br>


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


<br>


## Running the Framework

Start the application:
```bash
./myenv/bin/python src/main.py
```
This launches the interactive CLI in the main terminal, starts the reminders checker and Dream Mode activity monitor in the background, and runs the Telegram bot listener (if a bot token is provided).

> [!IMPORTANT]
> Ensure ollama is running on youre machine:
>
>```bash
>ollama serve
>```

<br>


## Chat Commands
Commands work in both the CLI and Telegram:
- `/help` — List available commands.
- `/model <name>` — Switch the active Ollama model on the fly.
- `/host [on/off]` — Enable/disable or toggle host execution (shell/python commands) on the fly.
- `/dream` — Trigger Dream Mode immediately to update `knowledge.md`.
- `/status` — Show the active model, uptime, configurations, and pending reminders.
- `/clear` — Clear the current chat context and unload the model from RAM.
- `/stop` — Unload the model from memory and graceful shutdown.


<br>


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
  

<br>

# THANK YOU! AND SEE YOU SOON!

This is my first attempt to make something like this so it can miss a lot of tools and cool features that others framworks have but i am working on a newer version with a lot of new features!

### Feel free to use it and modify it and make it better for you!

<br>

![Apple](https://img.shields.io/badge/macOS-white?style=for-the-badge&logo=apple&logoColor=black) ![Linux](https://img.shields.io/badge/Linux-FF6B9D?style=for-the-badge&logo=linux&logoColor=white) ![Debian](https://img.shields.io/badge/Debian-ff2954?style=for-the-badge&logo=debian&logoColor=white) ![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white) ![Bash](https://img.shields.io/badge/Bash-9B35D4?style=for-the-badge&logo=gnubash&logoColor=white) [![Ollama](https://img.shields.io/badge/Ollama-white?style=for-the-badge&logo=ollama&logoColor=black)](https://ollama.com) ![AI Agents](https://img.shields.io/badge/AI%20Agents-00c46c?style=for-the-badge)


<br>

