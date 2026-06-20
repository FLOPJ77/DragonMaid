import html
import json
import os
import sys
import time
import datetime
import requests
import subprocess
import shlex
import threading
import platform
try:
    import msvcrt
except Exception:
    msvcrt = None
try:
    import termios, tty
except Exception:
    termios = None
    tty = None
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs, unquote


class Spinner:
    def __init__(self, message="Loading...", spinner_type="dots"):
        self.message = message
        if spinner_type == "bounce":
            self.frames = ["█   ", " █  ", "  █ ", "   █", "  █ ", " █  ", "█   "]
            self.interval = 0.1
        else:  # "dots"
            self.frames = ["⠏", "⠋", "⠙", "⠼", "⠴", "⠦", "⠧"]
            self.interval = 0.08
        self.stop_event = threading.Event()
        self.thread = None

    def _animate(self):
        while not self.stop_event.is_set():
            for frame in self.frames:
                if self.stop_event.is_set():
                    break
                sys.stdout.write(f"\r\033[37m{frame}\033[0m {self.message}")
                sys.stdout.flush()
                time.sleep(self.interval)

    def start(self):
        if RUN_MODE == "cli":
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._animate, daemon=True)
            self.thread.start()

    def stop(self):
        if self.thread:
            self.stop_event.set()
            self.thread.join()
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()


def format_cli_output(text: str) -> str:
    """Strips HTML tags and programmatically filters out Unicode emojis for CLI mode."""
    clean = ""
    for char in text:
        ord_c = ord(char)
        if (0x2600 <= ord_c <= 0x27BF or 
            0x1F300 <= ord_c <= 0x1F9FF or 
            0x1F600 <= ord_c <= 0x1F64F or 
            ord_c >= 0x1F000):
            continue
        clean += char
    
    clean = (clean.replace("<b>", "")
                  .replace("</b>", "")
                  .replace("<i>", "")
                  .replace("</i>", "")
                  .replace("<code>", "")
                  .replace("</code>", "")
                  .replace("<pre>", "")
                  .replace("</pre>", "")
                  .replace("&lt;", "<")
                  .replace("&gt;", ">"))
    return clean.strip()


def load_env():
    """Pure Python lightweight .env parser."""
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line_str = line.strip()
                if line_str and not line_str.startswith("#") and "=" in line_str:
                    key, val = line_str.split("=", 1)
                    val = val.strip().strip('"').strip("'")
                    os.environ[key.strip()] = val


# Load our secrets on startup
load_env()


def log_debug(category: str, data: str):
    """Appends raw JSON/text payloads to dragonmaid.log on the host."""
    try:
        def redact_sensitive(s: str) -> str:
            if not s:
                return s
            out = s
            # redact API keys and tokens if present
            try:
                key = os.getenv("API_KEY", "")
                if key:
                    out = out.replace(key, "[REDACTED_API_KEY]")
            except Exception:
                pass
            try:
                bot = os.getenv("TELEGRAM_BOT_TOKEN", "")
                if bot:
                    out = out.replace(bot, "[REDACTED_TG_TOKEN]")
            except Exception:
                pass
            return out

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open("dragonmaid.log", "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{category}]\n")
            f.write(redact_sensitive(data) + "\n")
            f.write("=" * 60 + "\n\n")
    except Exception as e:
        print(f"[Log Error] Failed to write to dragonmaid.log: {e}")


# --- CONFIGURATION (Safe & Externalized) ---
API_KEY = os.getenv("API_KEY", "ollama")
API_URL = os.getenv("API_URL", "http://localhost:11434/v1/chat/completions")
MODEL = os.getenv("MODEL", "granite4.1:3b")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")  
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))  

HISTORY_FILE = "history.json"
CONFIG_FILE = "config.json"

# Safe Local Workspace Directory
WORKSPACE_DIR = os.path.abspath("./workspace")

# Global mode variable ('cli' or 'telegram')
RUN_MODE = "cli"

# Global idle variables for dreaming
LAST_ACTIVITY_TIME = time.time()
HAS_DREAMED_SINCE_ACTIVITY = True

# Emergency shutdown flag
EMERGENCY_SHUTDOWN = False
EMERGENCY_REQUESTED = False
EMERGENCY_REQUEST_TIME = 0

# Host command whitelist (only allow these base commands on direct host execution)
HOST_COMMAND_WHITELIST = {
    "ls", "cat", "echo", "ping", "df", "free", "uptime", "whoami",
    "id", "ps", "ss", "netstat", "ip", "ifconfig", "journalctl", "systemctl"
}

# Files that require explicit user approval before being modified or deleted
SENSITIVE_FILENAMES = {"config.json", ".env", "history.json", "knowledge.json", "reminders.txt", "dragonmaid.py", "authorized_keys"}

def _needs_file_approval(filename: str, action: str) -> bool:
    """Return True if a filename should prompt the user before write/delete.
    We protect dotfiles, known sensitive names, and executable/script extensions.
    """
    try:
        name = os.path.basename(filename).lower()
    except Exception:
        name = filename.lower()

    if not name:
        return True
    if name in SENSITIVE_FILENAMES:
        return True
    if name.startswith('.'):
        return True
    _, ext = os.path.splitext(name)
    if ext in {'.py', '.sh', '.exe', '.bat', '.service', '.json', '.conf'}:
        return True
    return False


class EmergencyListener(threading.Thread):
    """Background thread that listens for an emergency key (ESC) and forces immediate shutdown.
    Cross-platform: uses msvcrt on Windows, termios+tty on Unix.
    """
    def __init__(self):
        super().__init__(daemon=True)

    def run(self):
        try:
            global EMERGENCY_REQUESTED, EMERGENCY_REQUEST_TIME
            if msvcrt:
                while True:
                    if msvcrt.kbhit():
                        ch = msvcrt.getch()
                        if ch == b"\x1b":  # ESC
                            now = time.time()
                            if not EMERGENCY_REQUESTED or (now - EMERGENCY_REQUEST_TIME) > 5:
                                EMERGENCY_REQUESTED = True
                                EMERGENCY_REQUEST_TIME = now
                                print("\n[EMERGENCY] Emergency requested — attempting graceful shutdown. Press ESC again within 5s to force.")
                                try:
                                    # attempt lightweight graceful actions
                                    msgs = Memory.load()
                                    Memory.save(msgs)
                                    log_debug("EMERGENCY", "Graceful shutdown requested: memory saved.")
                                except Exception:
                                    pass
                                # wait 5 seconds then force exit if still requested
                                def delayed_exit():
                                    time.sleep(5)
                                    if EMERGENCY_REQUESTED and (time.time() - EMERGENCY_REQUEST_TIME) >= 5:
                                        print("[EMERGENCY] Graceful window ended — exiting now.")
                                        os._exit(0)
                                threading.Thread(target=delayed_exit, daemon=True).start()
                            else:
                                print("\n[EMERGENCY] Force exit triggered. Exiting immediately.")
                                os._exit(1)
                    time.sleep(0.05)
            elif termios and tty:
                fd = sys.stdin.fileno()
                old_settings = termios.tcgetattr(fd)
                try:
                    tty.setcbreak(fd)
                    while True:
                        ch = sys.stdin.read(1)
                        if ch == "\x1b":
                            now = time.time()
                            if not EMERGENCY_REQUESTED or (now - EMERGENCY_REQUEST_TIME) > 5:
                                EMERGENCY_REQUESTED = True
                                EMERGENCY_REQUEST_TIME = now
                                print("\n[EMERGENCY] Emergency requested — attempting graceful shutdown. Press ESC again within 5s to force.")
                                try:
                                    msgs = Memory.load()
                                    Memory.save(msgs)
                                    log_debug("EMERGENCY", "Graceful shutdown requested: memory saved.")
                                except Exception:
                                    pass

                                def delayed_exit_unix():
                                    time.sleep(5)
                                    if EMERGENCY_REQUESTED and (time.time() - EMERGENCY_REQUEST_TIME) >= 5:
                                        print("[EMERGENCY] Graceful window ended — exiting now.")
                                        os._exit(0)
                                threading.Thread(target=delayed_exit_unix, daemon=True).start()
                            else:
                                print("\n[EMERGENCY] Force exit triggered. Exiting immediately.")
                                os._exit(1)
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            # If listener fails, do not crash main program
            return


# --- Dynamic Configuration Loader ---
MAX_HISTORY_MESSAGES = 10

def load_dynamic_config():
    """Loads configuration parameters dynamically from a lightweight local JSON."""
    global MAX_HISTORY_MESSAGES, MODEL, API_URL, API_KEY
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                MAX_HISTORY_MESSAGES = int(cfg.get("MAX_HISTORY_MESSAGES", 10))
                MODEL = cfg.get("MODEL", MODEL)
                API_URL = cfg.get("API_URL", API_URL)
                API_KEY = cfg.get("API_KEY", API_KEY)
        except Exception:
            pass

def save_dynamic_config():
    """Saves updated parameters back to local JSON config."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump({
                "MAX_HISTORY_MESSAGES": MAX_HISTORY_MESSAGES,
                "MODEL": MODEL,
                "API_URL": API_URL,
                "API_KEY": API_KEY
            }, f, indent=2)
        # Also update .env for faster, simpler config on startup
        update_env_file()
    except Exception as e:
        print(f"[Config Error] Failed to write config: {e}")


def update_env_file():
    """Persist key runtime settings to .env for simplicity and fast startup."""
    try:
        from collections import OrderedDict

        env_map = OrderedDict()
        # Load existing .env preserving comments and order
        if os.path.exists('.env'):
            with open('.env', 'r', encoding='utf-8') as f:
                for line in f:
                    raw = line.rstrip('\n')
                    if not raw or raw.strip().startswith('#'):
                        # store comments/blank lines with generated keys to preserve order
                        env_map.setdefault(f"__COMMENT__{len(env_map)}", raw)
                        continue
                    if '=' in raw:
                        k, v = raw.split('=', 1)
                        env_map[k.strip()] = v.strip()
                    else:
                        env_map.setdefault(f"__COMMENT__{len(env_map)}", raw)

        def quoted(val: str) -> str:
            if val is None:
                return None
            s = str(val)
            if any(c.isspace() for c in s) or '"' in s:
                return '"' + s.replace('"', '') + '"'
            return s

        # Update core keys
        env_map["API_KEY"] = quoted(API_KEY)
        env_map["API_URL"] = quoted(API_URL)
        env_map["MODEL"] = quoted(MODEL)
        env_map["ALLOW_HOST_EXECUTION"] = str(ALLOW_HOST_EXECUTION).lower()
        env_map["BYPASS_HOST_GATEKEEPER"] = str(BYPASS_HOST_GATEKEEPER).lower()

        # Preserve or add Telegram settings if present in environment or existing file
        tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
        allowed_uid = os.getenv("ALLOWED_USER_ID")
        if "TELEGRAM_BOT_TOKEN" in env_map or tg_token:
            env_map["TELEGRAM_BOT_TOKEN"] = quoted(tg_token if tg_token is not None else env_map.get("TELEGRAM_BOT_TOKEN"))
        if "ALLOWED_USER_ID" in env_map or allowed_uid:
            env_map["ALLOWED_USER_ID"] = str(allowed_uid if allowed_uid is not None else env_map.get("ALLOWED_USER_ID"))

        # Write back preserving comments and order
        with open('.env', 'w', encoding='utf-8') as f:
            for k, v in env_map.items():
                if k.startswith("__COMMENT__"):
                    f.write(v + '\n')
                else:
                    if v is None:
                        continue
                    f.write(f"{k}={v}\n")
    except Exception as e:
        print(f"[Config Error] Failed to update .env: {e}")


# Load dynamic config values on startup
load_dynamic_config()


# Load safety bypass configuration
BYPASS_HOST_GATEKEEPER = os.getenv("BYPASS_HOST_GATEKEEPER", "false").strip().lower() == "true"



# OPTIMIZED SYSTEM PROMPT (Tailored for DragonMaid):
SYSTEM_PROMPT = {
    "role": "system", 
    "content": (
        "You are DragonMaid, a loyal and helpful maid assistant. Keep responses brief and polite. "
        "Use your tools to manage files, run terminal tasks, execute code, and search the web."
    )
}


# --- State Management (Memory) ---
class Memory:
    @staticmethod
    def load() -> list:
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    history = json.load(f)
                    if not history or history[0].get("role") != "system":
                        history.insert(0, SYSTEM_PROMPT)
                    return history
            except Exception:
                pass
        return [SYSTEM_PROMPT]

    @staticmethod
    def save(messages: list):
        try:
            pruned = [messages[0]]
            chat_turns = messages[1:]
            if len(chat_turns) > MAX_HISTORY_MESSAGES:
                chat_turns = chat_turns[-MAX_HISTORY_MESSAGES:]
            pruned.extend(chat_turns)
            with open(HISTORY_FILE, "w") as f:
                json.dump(pruned, f, indent=2)
        except Exception as e:
            print(f"[Memory Warning] Failed to save state: {e}")


# --- Helper to communicate with Telegram API ---
def send_telegram_request(method: str, payload: dict, timeout: int = 25) -> dict:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        return r.json()
    except requests.exceptions.ReadTimeout:
        return {"ok": True, "result": []}
    except Exception as e:
        print(f"[Telegram Error] Request failed: {e}")
        return {}


# --- DuckDuckGo Zero-Dependency Parser ---
def clean_ddg_url(url: str) -> str:
    """Extracts direct destination URLs out of DuckDuckGo redirect parameters."""
    if "uddg=" in url:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if "uddg" in query:
            return unquote(query["uddg"][0])
    return url

class DDGParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self.current_result = {}
        self.in_result_a = False
        self.in_snippet = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "a" and "result__a" in attrs_dict.get("class", ""):
            self.in_result_a = True
            self.current_result = {
                "url": attrs_dict.get("href", ""),
                "title": "",
                "snippet": ""
            }
        elif "result__snippet" in attrs_dict.get("class", ""):
            self.in_snippet = True

    def handle_data(self, data):
        if self.in_result_a:
            self.current_result["title"] += data
        elif self.in_snippet:
            if self.current_result:
                self.current_result["snippet"] += data
            elif self.results:
                self.results[-1]["snippet"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.in_result_a:
            self.in_result_a = False
            self.results.append(self.current_result)
            self.current_result = {}
        elif self.in_snippet:
            self.in_snippet = False


# --- Core Helpers & Specialized Tools ---

def get_current_time() -> str:
    """Returns the current date, time, year, and day of the week on the host machine."""
    now = datetime.datetime.now()
    return now.strftime("%A, %B %d, %Y, %I:%M %p")


def get_temporal_context() -> str:
    """Calculates today, tomorrow, and yesterday dates programmatically."""
    now = datetime.datetime.now()
    tomorrow = now + datetime.timedelta(days=1)
    yesterday = now - datetime.timedelta(days=1)
    
    today_str = now.strftime("%A, %B %d, %Y")
    time_str = now.strftime("%I:%M %p")
    tomorrow_str = tomorrow.strftime("%A, %B %d, %Y")
    yesterday_str = yesterday.strftime("%A, %B %d, %Y")
    
    return (
        f"Today is {today_str}. "
        f"The current local time is {time_str}. "
        f"Tomorrow is {tomorrow_str}. "
        f"Yesterday was {yesterday_str}."
    )


def safe_path(filename: str) -> str:
    """Blocks directory traversal attacks, resolving symlinks for absolute host safety."""
    resolved = os.path.realpath(os.path.join(WORKSPACE_DIR, filename))
    base_resolved = os.path.realpath(WORKSPACE_DIR)
    if not resolved.startswith(base_resolved):
        raise PermissionError("Path traversal attempt blocked.")
    return resolved


def request_user_approval(action_description: str, content: str, warning_level: str = "medium") -> bool:
    """
    Centralized human-in-the-loop gatekeeper.
    Asks the user for confirmation before running sensitive terminal or code operations.
    """
    if RUN_MODE == "cli":
        print(f"\n[Gatekeeper] Requesting execution approval for: {action_description}")
        print("-" * 50)
        print(content.strip())
        print("-" * 50)
        prompt = "Allow execution? (y/N): " if warning_level != "high" else "DANGER: This runs directly on your HOST machine. Allow execution? (y/N): "
        consent = input(prompt).strip().lower()
        return consent == 'y'
    
    else:
        print(f"\n[Gatekeeper] Requesting remote approval for: {action_description}")
        escaped_content = html.escape(content.strip())
        warning_text = "\n⚠️ <b> DANGER: This runs directly on the HOST machine (Unsandboxed)!</b>" if warning_level == "high" else ""
        
        text_html = (
            f"⚠️ <b>DragonMaid wants to run {action_description}:</b>\n"
            f"<pre><code>{escaped_content}</code></pre>{warning_text}"
        )
        reply_markup = {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": "approve"},
                {"text": "❌ Deny", "callback_data": "deny"}
            ]]
        }
        sent_msg = send_telegram_request("sendMessage", {
            "chat_id": ALLOWED_USER_ID,
            "text": text_html,
            "parse_mode": "HTML",
            "reply_markup": reply_markup
        })
        if not sent_msg.get("ok"):
            print("[Gatekeeper Error] Failed to deliver approval message.")
            return False
            
        prompt_message_id = sent_msg["result"]["message_id"]
        user_decision = None
        offset = 0
        
        while user_decision is None:
            updates = send_telegram_request("getUpdates", {"offset": offset, "timeout": 5}, timeout=10)
            if not updates.get("ok"):
                time.sleep(1)
                continue
                
            for update in updates.get("result", []):
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    cb = update["callback_query"]
                    cb_user_id = cb["from"]["id"]
                    cb_message_id = cb["message"]["message_id"]
                    
                    if cb_user_id == ALLOWED_USER_ID and cb_message_id == prompt_message_id:
                        user_decision = cb["data"]
                        send_telegram_request("answerCallbackQuery", {
                            "callback_query_id": cb["id"],
                            "text": f"Decision: {user_decision.capitalize()}"
                        })
                        
                        status_text = "✅ <b>Executed safely inside sandbox.</b>" if user_decision == "approve" else "❌ <b>Execution Denied by user.</b>"
                        if warning_level == "high":
                            status_text = "✅ <b>Executed directly on host.</b>" if user_decision == "approve" else "❌ <b>Host execution Denied by user.</b>"
                        
                        send_telegram_request("editMessageText", {
                            "chat_id": ALLOWED_USER_ID,
                            "message_id": prompt_message_id,
                            "text": f"{text_html}\n\n{status_text}",
                            "parse_mode": "HTML"
                        })
                        break
            time.sleep(0.5)

        return user_decision == "approve"


def manage_reminders(action: str, datetime_str: str = "", reminder_text: str = "") -> str:
    """Unified task manager tool."""
    action_clean = action.strip().lower()

    if action_clean == "add":
        if not datetime_str or not reminder_text:
            return "Error: Action 'add' requires both datetime_str and reminder_text."
            
        # record invocation to log instead of printing sensitive details to CLI
        log_debug("TOOL_INVOKE", json.dumps({"tool": "manage_reminders", "action": action_clean, "datetime": datetime_str, "reminder_text": reminder_text}, indent=2))
        
        formats = [
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %I:%M %p",
            "%Y-%m-%d %I:%M%p",
            "%Y/%m/%d %H:%M",
            "%Y/%m/%d %I:%M %p",
            "%Y/%m/%d %I:%M%p"
        ]
        parsed_dt = None
        for fmt in formats:
            try:
                parsed_dt = datetime.datetime.strptime(datetime_str.strip(), fmt)
                break
            except ValueError:
                continue
                
        if parsed_dt is None:
            return "Error: Invalid date format. Please use 'YYYY-MM-DD HH:MM'."
            
        normalized_str = parsed_dt.strftime("%Y-%m-%d %H:%M")
        try:
            with open("reminders.txt", "a") as f:
                f.write(f"{normalized_str} | {reminder_text}\n")
            return f"Success: Scheduled '{reminder_text}' for {normalized_str}."
        except Exception as e:
            return f"Error scheduling reminder: {str(e)}"

    elif action_clean == "delete":
        if not reminder_text:
            return "Error: Action 'delete' requires reminder_text as search keyword."
            
        log_debug("TOOL_INVOKE", json.dumps({"tool": "manage_reminders", "action": action_clean, "reminder_text": reminder_text}, indent=2))
        if not os.path.exists("reminders.txt"):
            return "No reminders exist."

        match_text = reminder_text.strip().lower()
        try:
            with open("reminders.txt", "r") as f:
                lines = f.readlines()

            remaining_lines = []
            removed_count = 0

            for line in lines:
                if match_text in line.lower():
                    removed_count += 1
                else:
                    remaining_lines.append(line)

            with open("reminders.txt", "w") as f:
                f.writelines(remaining_lines)

            if removed_count > 0:
                return f"Success: Deleted {removed_count} reminder(s) containing keyword '{reminder_text}'."
            return f"No reminders found containing the keyword '{reminder_text}'."
        except Exception as e:
            return f"Error deleting reminders: {str(e)}"

    elif action_clean == "clear_all":
        log_debug("TOOL_INVOKE", json.dumps({"tool": "manage_reminders", "action": action_clean}, indent=2))
        try:
            with open("reminders.txt", "w") as f:
                f.write("")
            return "Success: Wiped schedule. All reminders deleted."
        except Exception as e:
            return f"Error clearing reminders: {str(e)}"

    elif action_clean == "list":
        log_debug("TOOL_INVOKE", json.dumps({"tool": "manage_reminders", "action": action_clean}, indent=2))
        if not os.path.exists("reminders.txt"):
            return "You have no scheduled reminders."
        try:
            with open("reminders.txt", "r") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
            if not lines:
                return "You have no scheduled reminders."
            
            output = "Active Scheduled Reminders:\n" + "\n".join(lines)
            return output
        except Exception as e:
            return f"Error reading reminders file: {str(e)}"

    return f"Error: Unknown action '{action}'."


def manage_files(action: str, filename: str = "", content: str = "") -> str:
    """Safe workspace directory file manager operating on host."""
    if not os.path.exists(WORKSPACE_DIR):
        os.makedirs(WORKSPACE_DIR)

    action_clean = action.strip().lower()

    if action_clean == "list":
        log_debug("TOOL_INVOKE", json.dumps({"tool": "manage_files", "action": action_clean}, indent=2))
        try:
            files = os.listdir(WORKSPACE_DIR)
            if not files:
                return "The workspace directory is currently empty."
            return "Workspace files:\n" + "\n".join(files)
        except Exception as e:
            return f"Error listing files: {str(e)}"

    if not filename:
        return f"Error: Action '{action}' requires a filename."

    try:
        target_path = safe_path(filename)
    except PermissionError:
        print(f"[Security Warning] Blocked path traversal attempt to: '{filename}'")
        return "Error: Access denied. Directory traversal outside workspace blocked."

    if action_clean == "write":
        log_debug("TOOL_INVOKE", json.dumps({"tool": "manage_files", "action": action_clean, "filename": filename, "content_length": len(content) if isinstance(content, str) else None}, indent=2))

        # If the target filename is sensitive or looks like an executable/script, request user approval
        if _needs_file_approval(filename, "write"):
            preview = (content[:600] + "\n...") if isinstance(content, str) and len(content) > 600 else (content if isinstance(content, str) else "")
            approved = request_user_approval(f"Write file '{filename}' inside workspace", preview, warning_level="high")
            if not approved:
                log_debug("TOOL_REJECTED", f"manage_files write {filename} denied by user")
                return "Error: User denied file write."

        try:
            with open(target_path, "w") as f:
                f.write(content)
            return f"Success: Saved content to '{filename}' inside safe workspace."
        except Exception as e:
            return f"Error writing file: {str(e)}"

    elif action_clean == "read":
        log_debug("TOOL_INVOKE", json.dumps({"tool": "manage_files", "action": action_clean, "filename": filename}, indent=2))
        if not os.path.exists(target_path):
            return f"Error: File '{filename}' does not exist inside workspace."
        try:
            with open(target_path, "r") as f:
                return f"Content of '{filename}':\n\n{f.read()}"
        except Exception as e:
            return f"Error reading file: {str(e)}"

    elif action_clean == "delete":
        log_debug("TOOL_INVOKE", json.dumps({"tool": "manage_files", "action": action_clean, "filename": filename}, indent=2))
        if not os.path.exists(target_path):
            return f"Error: File '{filename}' does not exist inside workspace."

        # Ask for approval for sensitive deletes
        if _needs_file_approval(filename, "delete"):
            try:
                with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
                    current = f.read(600)
            except Exception:
                current = "[Could not read existing file content]"
            approved = request_user_approval(f"Delete file '{filename}' from workspace", current, warning_level="high")
            if not approved:
                log_debug("TOOL_REJECTED", f"manage_files delete {filename} denied by user")
                return "Error: User denied file deletion."

        try:
            os.remove(target_path)
            return f"Success: Deleted '{filename}' from workspace."
        except Exception as e:
            return f"Error deleting file: {str(e)}"

    return f"Error: Unknown action '{action}'."


def manage_knowledge(action: str, key: str = "", value: str = "") -> str:
    """Manages long-term personal knowledge facts."""
    knowledge_file = "knowledge.json"
    action_clean = action.strip().lower()

    db = {}
    if os.path.exists(knowledge_file):
        try:
            with open(knowledge_file, "r") as f:
                db = json.load(f)
        except Exception:
            pass

    if action_clean == "list":
        log_debug("TOOL_INVOKE", json.dumps({"tool": "manage_knowledge", "action": action_clean}, indent=2))
        if not db:
            return "The long-term knowledge database is currently empty."
        return "Long-term Knowledge Keys:\n" + "\n".join(f"- {k}" for k in db.keys())

    if not key:
        return f"Error: Action '{action}' requires a key."

    key_clean = key.strip().lower()

    if action_clean == "write":
        if not value:
            return "Error: Action 'write' requires a value."
        log_debug("TOOL_INVOKE", json.dumps({"tool": "manage_knowledge", "action": action_clean, "key": key_clean, "value_preview": value[:200]}, indent=2))
        db[key_clean] = value.strip()
        try:
            with open(knowledge_file, "w") as f:
                json.dump(db, f, indent=2)
            return f"Success: Saved '{key_clean}' to long-term memory."
        except Exception as e:
            return f"Error saving knowledge: {str(e)}"

    elif action_clean == "read":
        log_debug("TOOL_INVOKE", json.dumps({"tool": "manage_knowledge", "action": action_clean, "key": key_clean}, indent=2))
        if key_clean in db:
            return f"Knowledge for '{key_clean}': {db[key_clean]}"
        return f"No knowledge found for key '{key_clean}'."

    elif action_clean == "delete":
        log_debug("TOOL_INVOKE", json.dumps({"tool": "manage_knowledge", "action": action_clean, "key": key_clean}, indent=2))
        if key_clean in db:
            del db[key_clean]
            try:
                with open(knowledge_file, "w") as f:
                    json.dump(db, f, indent=2)
                return f"Success: Deleted '{key_clean}' from long-term memory."
            except Exception as e:
                return f"Error deleting knowledge: {str(e)}"
        return f"No knowledge found for key '{key_clean}' to delete."

    return f"Error: Unknown action '{action}'."


def safe_web_search(query: str) -> str:
    """
    Searches the web safely using DuckDuckGo HTML static search.
    Features a Price-Boosting Algorithm to prioritize currency/listing results.
    """
    if RUN_MODE == "cli":
        spinner = Spinner(f"[Tool] Searching DuckDuckGo for: \"{query}\"...", spinner_type="bounce")
        spinner.start()
    else:
        print(f"\n[Tool Executing] Performing safe web search for: '{query}'")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://html.duckduckgo.com",
        "Referer": "https://html.duckduckgo.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }
    url = "https://html.duckduckgo.com/html/"
    payload = {"q": query}

    try:
        r = requests.post(url, data=payload, headers=headers, timeout=10)
        if r.status_code != 200:
            return f"Error: Search engine returned status code {r.status_code}"

        parser = DDGParser()
        parser.feed(r.text)
        
        price_results = []
        standard_results = []
        
        for res in parser.results:
            snippet = res.get("snippet", "").lower()
            title = res.get("title", "").lower()
            price_indicators = ["$", "€", "£", "price", "cost", "usd", "eur"]
            
            if any(ind in snippet or ind in title for ind in price_indicators):
                price_results.append(res)
            else:
                standard_results.append(res)

        sorted_results = price_results + standard_results
        top_results = sorted_results[:4]
        
        if not top_results:
            return "No results found for your query."

        output = f"Web Search Results for '{query}':\n\n"
        for i, res in enumerate(top_results, 1):
            clean_url = clean_ddg_url(res["url"])
            output += f"[{i}] {res['title'].strip()}\nURL: {clean_url}\nSnippet: {res['snippet'].strip()}\n\n"

        return output
    except Exception as e:
        return f"Error during web search: {str(e)}"
    finally:
        if RUN_MODE == "cli":
            spinner.stop()


def execute_python_code(code: str) -> str:
    """Runs Python inside a hardened Docker container using non-root limits."""
    if not request_user_approval("Python execution in sandbox", code, warning_level="medium"):
        raise PermissionError("USER_DENIED_EXECUTION")

    try:
        cmd = [
            "docker", "run", "--rm", "-i",
            "--network", "none",
            "--memory", "128m",
            "--cpus", "0.5",
            "--read-only",
            "--user", "1000:1000",
            "python:3.11-slim",
            "python", "-c", code
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout if result.stdout else "[Execution Successful]"
        else:
            return f"Error (Exit Code {result.returncode}):\n{result.stderr}"
    except subprocess.TimeoutExpired:
        return "Error: Sandbox execution timed out."
    except Exception as e:
        return f"Error: {str(e)}"


class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.ignore_depth = 0
        self.ignore_tags = {"script", "style", "head", "meta", "link", "noscript", "iframe", "svg"}

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.ignore_tags:
            self.ignore_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.ignore_tags:
            self.ignore_depth = max(0, self.ignore_depth - 1)

    def handle_data(self, data):
        if self.ignore_depth == 0:
            stripped = data.strip()
            if stripped:
                self.text_parts.append(stripped)

    def get_text(self):
        return "\n".join(self.text_parts)


def execute_terminal_command(command: str) -> str:
    """Runs a shell command inside the secure, isolated Docker container."""
    if not request_user_approval("Terminal run inside sandbox", command, warning_level="medium"):
        raise PermissionError("USER_DENIED_EXECUTION")

    try:
        cmd = [
            "docker", "run", "--rm", "-i",
            "--network", "bridge",
            "--memory", "128m",
            "--cpus", "0.5",
            "--read-only",
            "--user", "1000:1000",
            "--sysctl", "net.ipv4.ping_group_range=0 2147483647",
            "--tmpfs", "/tmp",
            "alpine:latest",
            "sh", "-c", command
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout if result.stdout else "[Execution Successful]"
        else:
            return f"Error (Exit Code {result.returncode}):\n{result.stderr}"
    except subprocess.TimeoutExpired:
        return "Error: Sandbox execution timed out."
    except Exception as e:
        return f"Error: {str(e)}"


def _sanitize_tool_args(tool_name: str, args: dict) -> dict:
    """Basic sanitization for tool arguments. Raises ValueError for unsafe content."""
    sanitized = {}
    max_len = 2000
    dangerous_patterns = [";", "&&", "||", "|", "$()", "`", "$(", "<", ">"]
    for k, v in args.items():
        if isinstance(v, str):
            if len(v) > max_len:
                raise ValueError(f"Argument '{k}' too long")
            low = v.lower()
            # Allow file contents for manage_files (CSS/HTML code may contain ';' and braces)
            if tool_name == "manage_files" and k == "content":
                if "\x00" in v:
                    raise ValueError("Argument 'content' contains null bytes")
                sanitized[k] = v
                continue

            for p in dangerous_patterns:
                if p in low:
                    # allow internal safe commands to include limited characters when explicitly allowed
                    raise ValueError(f"Argument '{k}' contains potentially unsafe characters")
            sanitized[k] = v
        else:
            sanitized[k] = v
    return sanitized


def execute_ssh_command(host: str, command: str = "", user: str = "", port: int = 22, timeout: int = 15) -> str:
    """Execute an SSH command using the system ssh client. Only available in Host Control mode.
    This does not accept shell wrappers and runs the ssh client directly (no shell=True).
    User must approve via HITL unless bypass is active.
    """
    args = {"host": host, "command": command, "user": user, "port": port}
    try:
        args = _sanitize_tool_args("execute_ssh_command", args)
    except ValueError as e:
        return f"Error: Unsafe SSH arguments: {e}"

    ssh_target = f"{user}@{host}" if user else host
    ssh_cmd = ["ssh", "-p", str(port), ssh_target, command]

    if not BYPASS_HOST_GATEKEEPER:
        if not request_user_approval("SSH to host", f"ssh {ssh_target} -p {port} {command}", warning_level="high"):
            raise PermissionError("USER_DENIED_EXECUTION")
    else:
        print(f"[Bypass Mode] Executing SSH: {' '.join(ssh_cmd)}")

    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return result.stdout if result.stdout else "[SSH executed successfully]"
        return f"Error (SSH Exit {result.returncode}):\n{result.stderr}"
    except subprocess.TimeoutExpired:
        return "Error: SSH execution timed out."
    except Exception as e:
        return f"Error executing ssh: {e}"



def execute_host_command(command: str) -> str:
    """Runs a terminal/bash shell command directly on the host machine."""
    # Check if the user has configured the gatekeeper to bypass confirmation
    if not BYPASS_HOST_GATEKEEPER:
        if not request_user_approval("terminal command on the HOST machine", command, warning_level="high"):
            raise PermissionError("USER_DENIED_EXECUTION")
    else:
        # Log the command to the host console so you can still monitor what it does
        print(f"\n[Bypass Mode] Automatically executing host command: {command}")

    try:
        try:
            _sanitize_tool_args("execute_host_command", {"command": command})
        except ValueError as e:
            return f"Error: Unsafe host command: {e}"

        # Prefer not to use the shell on Linux; split the command safely
        try:
            cmd_list = shlex.split(command)
        except Exception:
            # Fallback to shell when splitting fails, but this should be rare
            cmd_list = None

        if cmd_list:
            # Enforce whitelist on the base command
            base_cmd = os.path.basename(cmd_list[0])
            if base_cmd not in HOST_COMMAND_WHITELIST:
                return f"Error: Host command '{base_cmd}' is not allowed by whitelist."
            result = subprocess.run(cmd_list, capture_output=True, text=True, timeout=15)
        else:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\nStderr:\n{result.stderr}"
        return output if output.strip() else "[Command executed with no output]"
    except subprocess.TimeoutExpired:
        return "Error: Host execution timed out after 15 seconds."
    except Exception as e:
        return f"Error executing host command: {str(e)}"




def fetch_webpage_content(url: str) -> str:
    """Fetches raw webpage HTML and extracts clean, readable text with context window safety."""
    if RUN_MODE == "cli":
        spinner = Spinner(f"[Tool] Fetching content from: \"{url}\"...", spinner_type="bounce")
        spinner.start()
    else:
        print(f"\n[Tool Executing] Fetching webpage: '{url}'")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    }

    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return "Error: Invalid URL scheme. Only http and https protocols are supported."

        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return f"Error: Webpage returned status code {r.status_code}"

        parser = HTMLTextExtractor()
        parser.feed(r.text)
        clean_text = parser.get_text()

        if len(clean_text) > 6000:
            return clean_text[:6000] + "\n\n[Content Truncated due to size limits]"
        return clean_text if clean_text else "No readable text content found on the page."

    except Exception as e:
        return f"Error fetching webpage: {str(e)}"
    finally:
        if RUN_MODE == "cli":
            spinner.stop()


# --- TOOL REGISTER ---

AVAILABLE_TOOLS = {
    "manage_reminders": manage_reminders,
    "manage_files": manage_files,            
    "manage_knowledge": manage_knowledge,
    "safe_web_search": safe_web_search,
    "execute_python_code": execute_python_code,
    "execute_terminal_command": execute_terminal_command,
    "execute_host_command": execute_host_command,
    "execute_ssh_command": execute_ssh_command,
    "fetch_webpage_content": fetch_webpage_content  
}

# Human-friendly labels for CLI tool messages
TOOL_DISPLAY_NAMES = {
    "execute_python_code": "Executing Python Code",
    "execute_terminal_command": "Executing Terminal Command",
    "execute_host_command": "Executing Host Command",
    "execute_ssh_command": "Executing SSH Command",
    "manage_files": "Manage Files",
    "manage_reminders": "Manage Reminders",
    "manage_knowledge": "Manage Knowledge",
    "safe_web_search": "Web Search",
    "fetch_webpage_content": "Fetch Webpage Content"
}


# --- TOOL SCHEMA ---
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "manage_reminders",
            "description": "Add, delete, list, or clear scheduled tasks and reminders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Must be one of: 'add' (schedule new), 'delete' (remove matching keyword), 'clear_all' (wipe schedule), or 'list' (view all scheduled reminders)."
                    },
                    "datetime_str": {
                        "type": "string",
                        "description": "Required for 'add'. Use YYYY-MM-DD HH:MM format (e.g. 2026-06-17 14:30)."
                    },
                    "reminder_text": {
                        "type": "string",
                        "description": "Required for 'add' and 'delete'. For 'add': Task text (prefix 'ACTION:' for autonomous tasks). For 'delete': Keyword to match and delete."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_files",
            "description": "Write, read, delete, or list files inside the safe local './workspace/' folder on the server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Must be one of: 'write' (save content to file), 'read' (read file content), 'delete' (remove file), or 'list' (view workspace files)."
                    },
                    "filename": {
                        "type": "string",
                        "description": "The name of the file to manage. Directory traversal outside the workspace is strictly blocked."
                    },
                    "content": {
                        "type": "string",
                        "description": "Required only for 'write' action. The text content to write inside the file."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "safe_web_search",
            "description": "Search web for news, prices, or info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python_code",
            "description": "Run Python code inside a secure container.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"}
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_knowledge",
            "description": "Store, read, delete, or list facts in your permanent memory file 'knowledge.json'. Use this to save long-term personal facts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Must be one of: 'write' (save fact), 'read' (retrieve fact), 'delete' (remove fact), or 'list' (view all keys)."
                    },
                    "key": {
                        "type": "string",
                        "description": "The specific keyword or name of the fact (e.g. 'sister_birthday' or 'printer_model')."
                    },
                    "value": {
                        "type": "string",
                        "description": "Required only for 'write'. The description or text of the fact to store."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_terminal_command",
            "description": "Run standard bash/shell commands safely inside a secure, network-isolated container sandbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell/bash command to run inside the container sandbox."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_host_command",
            "description": "Run shell/bash terminal commands directly on the host machine (not inside a Docker container). Use this when you need to interact with the host system, manage system processes, or invoke local tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command string to execute on the host machine."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_ssh_command",
            "description": "Run a command on a remote host via the system SSH client. Only enabled in Host Control mode.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string"},
                    "user": {"type": "string"},
                    "port": {"type": "integer"},
                    "command": {"type": "string"}
                },
                "required": ["host", "command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage_content",
            "description": "Fetch the raw text contents of a webpage directly from a URL to extract its information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The http/https URL of the webpage to read."
                    }
                },
                "required": ["url"]
            }
        }
    }
]


# --- host ---

# Read safety configuration from environment
ALLOW_HOST_EXECUTION = os.getenv("ALLOW_HOST_EXECUTION", "false").strip().lower() == "true"


def initialize_security_profile(allow_host: bool):
    global TOOLS_SCHEMA, AVAILABLE_TOOLS
    
    # Diagnostic prints removed to avoid leaking environment values at startup.

    if not allow_host:   
        # --- SECURE MODE ---
        # 1. Erase host command from active tools
        if "execute_host_command" in AVAILABLE_TOOLS:
            del AVAILABLE_TOOLS["execute_host_command"]
        if "execute_ssh_command" in AVAILABLE_TOOLS:
            del AVAILABLE_TOOLS["execute_ssh_command"]
            
        # 2. Filter host command out of the JSON schema
        TOOLS_SCHEMA = [
            tool for tool in TOOLS_SCHEMA 
            if tool["function"]["name"] != "execute_host_command"
        ]
        print("[Security Mode] SECURE ACTIVE: Direct host command execution is entirely disabled.")
    else:
        # --- HOST CONTROL MODE ---
        # 1. Erase the sandboxed terminal command so the model doesn't get confused
        if "execute_terminal_command" in AVAILABLE_TOOLS:
            del AVAILABLE_TOOLS["execute_terminal_command"]
            
        # 2. Filter the sandboxed terminal command out of the JSON schema
        TOOLS_SCHEMA = [
            tool for tool in TOOLS_SCHEMA 
            if tool["function"]["name"] != "execute_terminal_command"
        ]
        status = "Bypass Active - Run Automatically" if BYPASS_HOST_GATEKEEPER else "Requires HITL approval"
        print(f"[Security Mode] WARNING: HOST CONTROL ENABLED. Direct, unsandboxed command execution is available ({status}).")



# --- host ---




def check_steering_interrupt():
    """Checks Telegram for a rapid, non-blocking steering update from user."""
    if RUN_MODE != "telegram":
        return None
    try:
        updates = send_telegram_request("getUpdates", {"offset": -1, "limit": 1, "timeout": 0}, timeout=2)
        if updates.get("ok") and updates.get("result"):
            update = updates["result"][0]
            msg = update.get("message", {})
            if msg.get("from", {}).get("id") == ALLOWED_USER_ID:
                text = msg.get("text", "")
                next_offset = update["update_id"] + 1
                send_telegram_request("getUpdates", {"offset": next_offset, "limit": 1, "timeout": 0}, timeout=2)
                return text
    except Exception:
        pass
    return None


# --- Core LLM Processing ---
def run_agent_turn(messages, executed_calls_this_turn=None):
    if executed_calls_this_turn is None:
        executed_calls_this_turn = {}

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    runtime_messages = [messages[0]]
    runtime_messages.append({
        "role": "system",
        "content": f"[System Context] {get_temporal_context()}"
    })
    runtime_messages.extend(messages[1:])
    
    payload = {
        "model": MODEL,
        "messages": runtime_messages,
        "tools": TOOLS_SCHEMA,
        "tool_choice": "auto"
    }

    log_debug("OUTGOING_PAYLOAD", json.dumps(payload, indent=2))

    if RUN_MODE == "cli":
        spinner = Spinner(f"[LLM] Querying model [{MODEL}]...", spinner_type="dots")
        spinner.start()
    else:
        print(f"[LLM] Querying model '{MODEL}'...")

    start_time = time.time()
    
    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=380)
    except requests.exceptions.ConnectionError:
        if RUN_MODE == "cli":
            spinner.stop()
        print("[LLM Connection Error] Could not connect to model service.")
        return "⚠️ I cannot connect to the local Ollama service. Please make sure the service is running and properly configured on the server."
    except Exception as e:
        if RUN_MODE == "cli":
            spinner.stop()
        print(f"[LLM] Exception: {e}")
        return "⚠️ An unexpected error occurred while communicating with the model service."
        
    if RUN_MODE == "cli":
        spinner.stop()
        print(f"[LLM] Response received in {time.time() - start_time:.2f} seconds.")
    else:
        print(f"[LLM] Response received in {time.time() - start_time:.2f} seconds.")
    
    if response.status_code != 200:
        log_debug("INCOMING_ERROR", f"Status: {response.status_code}\nText: {response.text}")
        return "Error communicating with local LLM."

    response_json = response.json()
    log_debug("INCOMING_RESPONSE", json.dumps(response_json, indent=2))

    assistant_message = response_json['choices'][0]['message']
    messages.append(assistant_message)

    # Log what the model produced (redacted)
    try:
        log_debug("ASSISTANT_MESSAGE", json.dumps(assistant_message, indent=2))
    except Exception:
        pass

    if assistant_message.get("tool_calls"):
        for tool_call in assistant_message["tool_calls"]:
            tool_name = tool_call["function"]["name"]
            tool_args = json.loads(tool_call["function"]["arguments"])
            tool_id = tool_call["id"]

            call_signature = f"{tool_name}:{tool_call['function']['arguments']}"

            if call_signature in executed_calls_this_turn:
                tool_output = executed_calls_this_turn[call_signature]
            else:
                if tool_name in AVAILABLE_TOOLS:
                    # sanitize tool args before execution
                    try:
                        tool_args = _sanitize_tool_args(tool_name, tool_args)
                    except ValueError as e:
                        tool_output = f"Error: Unsafe tool arguments: {e}"
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "name": tool_name,
                            "content": tool_output
                        })
                        log_debug("TOOL_REJECTED", f"{tool_name} rejected due to unsafe args: {e}")
                        continue
                    steer_text = check_steering_interrupt()
                    if steer_text:
                        print(f"[Steering] INTERRUPTED BY USER: '{steer_text}'")
                        raise PermissionError(f"STEER_INTERRUPT:{steer_text}")

                    # Do not print full tool arguments to CLI; log them instead for audit.
                    try:
                        log_debug("TOOL_INVOKE", json.dumps({"tool": tool_name, "args": tool_args}, indent=2))
                    except Exception:
                        pass
                    # Show a minimal, friendly label on the CLI (no arguments printed)
                    label = TOOL_DISPLAY_NAMES.get(tool_name, tool_name.replace("_", " ").title())
                    if RUN_MODE == "cli":
                        print(f"[{label}]")
                    else:
                        print(f"\n[Tool Executing] {label}")

                    try:
                        log_debug("TOOL_CALL", f"Calling {tool_name} with args: {json.dumps(tool_args)}")
                        tool_output = AVAILABLE_TOOLS[tool_name](**tool_args)
                        log_debug("TOOL_OUTPUT", f"{tool_name} output:\n{str(tool_output)}")
                    except PermissionError as e:
                        if str(e) == "USER_DENIED_EXECUTION":
                            raise e
                else:
                    tool_output = f"Error: Tool '{tool_name}' not found."

            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "name": tool_name,
                "content": tool_output
            })
        
        Memory.save(messages)
        return run_agent_turn(messages, executed_calls_this_turn)
    
    Memory.save(messages)
    # Prefer assistant content, but if empty, fall back to the last non-empty message
    reply = assistant_message.get("content", "")
    if not reply:
        for m in reversed(messages):
            if m.get("content"):
                reply = m.get("content")
                break
    return reply


# --- Advanced Background Scheduler Engine ---
class BackgroundScheduler:
    def __init__(self, run_agent_turn_fn):
        self.last_reminder_check = 0
        self.reminder_file = "reminders.txt"
        self.run_agent_turn_fn = run_agent_turn_fn

    def tick(self):
        """Monitors clock ticks every 30 seconds to execute scheduled items."""
        current_time = time.time()
        
        global LAST_ACTIVITY_TIME, HAS_DREAMED_SINCE_ACTIVITY
        if not HAS_DREAMED_SINCE_ACTIVITY and (current_time - LAST_ACTIVITY_TIME >= 1800):
            print("[Scheduler] Idle threshold reached. Initiating dream sequence...")
            perform_dream()
            HAS_DREAMED_SINCE_ACTIVITY = True

        if current_time - self.last_reminder_check >= 30:
            self.last_reminder_check = current_time
            self.check_reminders()

    def check_reminders(self):
        if not os.path.exists(self.reminder_file):
            return

        now = datetime.datetime.now()
        remaining_lines = []
        triggered_reminders = []

        try:
            with open(self.reminder_file, "r") as f:
                lines = f.readlines()
            
            for line in lines:
                line_raw = line.strip()
                if not line_raw:
                    continue
                
                if "|" in line_raw:
                    parts = line_raw.split("|", 1)
                    time_str = parts[0].strip()
                    text = parts[1].strip()
                    
                    try:
                        scheduled_time = datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                        if now >= scheduled_time:
                            triggered_reminders.append((time_str, text))
                        else:
                            remaining_lines.append(f"{time_str} | {text}")
                    except ValueError:
                        remaining_lines.append(line_raw)
                else:
                    triggered_reminders.append((now.strftime("%Y-%m-%d %H:%M"), line_raw))

            with open(self.reminder_file, "w") as f:
                for line in remaining_lines:
                    f.write(f"{line}\n")

            for time_str, text in triggered_reminders:
                if text.startswith("ACTION:"):
                    action_instruction = text.replace("ACTION:", "").strip()
                    print(f"[Scheduler] TRIGGERING AUTONOMOUS ACTION: {action_instruction}")
                    
                    if RUN_MODE == "telegram":
                        send_telegram_request("sendMessage", {
                            "chat_id": ALLOWED_USER_ID,
                            "text": f"🐉 <b>[Scheduled Action Triggered]</b>\nRunning: <i>{html.escape(action_instruction)}</i>",
                            "parse_mode": "HTML"
                        })
                    else:
                        print(f"\n[Scheduler Trigger] Running action: {action_instruction}")
                    
                    time.sleep(1)
                    
                    messages = Memory.load()
                    messages.append({
                        "role": "system",
                        "content": (
                            f"[System Update] It is now scheduled action time ({time_str}). "
                            f"Please execute the following scheduled task: {action_instruction}. "
                            "Retrieve information, perform research using search tools if needed, and write your findings back to the user."
                        )
                    })
                    
                    if RUN_MODE == "telegram":
                        send_telegram_request("sendChatAction", {"chat_id": ALLOWED_USER_ID, "action": "typing"})
                    
                    try:
                        reply = self.run_agent_turn_fn(messages)
                    except PermissionError:
                        reply = "❌ <b>Scheduled action aborted: User denied execution.</b>"
                    except Exception as e:
                        reply = f"❌ <b>Scheduled task crashed: {str(e)}</b>"
                    
                    if RUN_MODE == "telegram":
                        send_telegram_request("sendMessage", {
                            "chat_id": ALLOWED_USER_ID,
                            "text": reply,
                            "parse_mode": "HTML"
                        })
                    else:
                        print(f"[DragonMaid]: {reply}\n")
                else:
                    print(f"[Scheduler] Triggered reminder: {text}")
                    if RUN_MODE == "telegram":
                        send_telegram_request("sendMessage", {
                            "chat_id": ALLOWED_USER_ID,
                            "text": f"🔔 <b>Reminder:</b> {html.escape(text)}",
                            "parse_mode": "HTML"
                        })

        except Exception as e:
            print(f"[Scheduler Error] {e}")


# --- Feature 2: Dreaming Engine (Memory Consolidation) ---
def perform_dream():
    """Memory Consolidation & History Compaction Cycle."""
    print("[Scheduler] Starting dreaming cycle (memory consolidation)...")
    messages = Memory.load()
    
    if len(messages) <= 1:
        print("[Scheduler] No conversation history to consolidate.")
        return "No history to consolidate."

    history_text = ""
    for msg in messages:
        if msg["role"] != "system" and msg.get("content"):
            history_text += f"{msg['role'].capitalize()}: {msg['content']}\n"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    dream_payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a memory consolidation engine. Read the conversation history. "
                    "Identify permanent facts about the user (preferences, names, server details, choices). "
                    "Respond ONLY with a valid raw JSON array of objects, where each object has 'key' and 'value'. "
                    "Example: [{\"key\": \"username\", \"value\": \"Alice\"}]. "
                    "If no permanent facts are found, return []. Do not include any explanations, do not write markdown."
                )
            },
            {"role": "user", "content": f"Extract facts from this conversation:\n\n{history_text}"}
        ]
    }

    new_facts_count = 0
    try:
        r = requests.post(API_URL, headers=headers, json=dream_payload, timeout=380)
        if r.status_code == 200:
            response_text = r.json()['choices'][0]['message']['content'].strip()
            
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            facts = json.loads(response_text)
            for fact in facts:
                key = fact.get("key")
                val = fact.get("value")
                if key and val:
                    manage_knowledge("write", key, val)
                    new_facts_count += 1
            print(f"[Scheduler] Consolidated {new_facts_count} new facts into long-term memory.")
        else:
            print(f"[Scheduler Error] Ollama returned status {r.status_code} during dream.")
    except Exception as e:
        print(f"[Scheduler Error] Dreaming failed to extract facts: {e}")

    summary_payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "Summarize the main topic of the conversation in one short sentence (e.g. 'Discussed server setup and set reminders')."},
            {"role": "user", "content": f"Summarize this history:\n\n{history_text}"}
        ]
    }
    
    summary_text = "Previous conversation consolidated."
    try:
        r = requests.post(API_URL, headers=headers, json=summary_payload, timeout=380)
        if r.status_code == 200:
            summary_text = r.json()['choices'][0]['message']['content'].strip()
    except Exception:
        pass

    compacted_messages = [
        SYSTEM_PROMPT,
        {
            "role": "assistant",
            "content": f"[Consolidated Memory Archive] Last active topic: {summary_text}. Important details extracted to long-term memory database."
        }
    ]
    Memory.save(compacted_messages)
    return f"Consolidated {new_facts_count} facts. Last topic summary: '{summary_text}'"


# --- Command Router Layer ---
def handle_command(text: str) -> str:
    """Parses and handles slash commands."""
    parts = text.strip().split(" ", 1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        help_text = (
            "📋 <b>DragonMaid Command List:</b>\n"
            "• <code>/status</code> : Check connection metrics, CPU load, and RAM usage.\n"
            "• <code>/model</code> : View or change the active LLM, API URL, and key.\n"
            "• <code>/history &lt;num&gt;</code> : Set the max message history window (e.g. /history 15).\n"
            "• <code>/dream</code> : Manually trigger memory consolidation right now.\n"
            "• <code>/clear history</code> : Wipe the conversation history file (history.json).\n"
            "• <code>/help</code> : View this command list."
        )
        return help_text

    elif cmd == "/model":
        global MODEL, API_URL, API_KEY
        if not arg:
            masked_key = "None" if not API_KEY else (API_KEY[:4] + "..." if len(API_KEY) > 8 else "Set")
            return (
                "🤖 <b>Current Model Configuration:</b>\n"
                f"• <b>Model:</b> <code>{MODEL}</code>\n"
                f"• <b>API Endpoint:</b> <code>{API_URL}</code>\n"
                f"• <b>API Key:</b> <code>{masked_key}</code>\n\n"
                "💡 <b>To update:</b>\n"
                "• Change model name: <code>/model set &lt;model_name&gt;</code>\n"
                "• Change API URL & Key: <code>/model endpoint &lt;url&gt; [optional_key]</code>\n"
                "• You can also quick-switch model via <code>/model &lt;model_name&gt;</code>"
            )
        
        subparts = arg.strip().split(" ", 1)
        subcmd = subparts[0].lower()
        subarg = subparts[1].strip() if len(subparts) > 1 else ""
        
        if subcmd == "set":
            if not subarg:
                return "⚠️ Usage: /model set <model_name>"
            old_model = MODEL
            MODEL = subarg
            save_dynamic_config()
            return f"🔄 <b>Model changed</b> from <code>{old_model}</code> to <code>{MODEL}</code>."
            
        elif subcmd == "endpoint":
            if not subarg:
                return "⚠️ Usage: /model endpoint <url> [optional_key]"
            
            endpoint_parts = subarg.split(" ", 1)
            new_url = endpoint_parts[0].strip()
            new_key = endpoint_parts[1].strip() if len(endpoint_parts) > 1 else ""
            
            old_url = API_URL
            API_URL = new_url
            if new_key:
                API_KEY = new_key
            
            save_dynamic_config()
            
            key_status = "and API key updated" if new_key else "(API key unchanged)"
            return f"🔄 <b>API Endpoint changed</b>\nFrom: <code>{old_url}</code>\nTo: <code>{API_URL}</code> {key_status}."
            
        else:
            old_model = MODEL
            MODEL = arg.strip()
            save_dynamic_config()
            return f"🔄 <b>Model changed</b> from <code>{old_model}</code> to <code>{MODEL}</code>."

    elif cmd == "/dream":
        print("[Command Router] Manual dream command triggered.")
        return f"😴 <b>Dream sequence initiated...</b>\n{perform_dream()}"

    elif cmd == "/history":
        global MAX_HISTORY_MESSAGES
        if not arg.isdigit():
            return "⚠️ Usage: /history <number> (e.g. /history 15)"
        num = int(arg)
        if num < 2 or num > 50:
            return "⚠️ Please choose a range between 2 and 50 messages."
        
        MAX_HISTORY_MESSAGES = num
        save_dynamic_config()
        print(f"[Command Router] MAX_HISTORY_MESSAGES dynamically updated to {num}.")
        return f"⚙️ <b>Config Updated:</b> Chat history window has been set to <b>{num}</b> messages."

    elif cmd == "/clear":
        # Support: /clear history  -> permanently wipe history.json
        target = arg.strip().lower()
        if not target:
            return "⚠️ Usage: /clear history"

        if target in ("history", "history.json", "all", "everything"):
            # Ask for explicit approval before wiping sensitive file
            approved = request_user_approval(
                "Clear conversation history",
                "This will permanently delete all conversation history stored in history.json. This action is irreversible.",
                warning_level="high"
            )
            if not approved:
                log_debug("TOOL_REJECTED", "clear history denied by user")
                return "❌ Action cancelled by user. History not modified."

            try:
                Memory.save([SYSTEM_PROMPT])
                log_debug("TOOL_INVOKE", "history cleared via /clear command")
                return "✅ <b>History cleared:</b> conversation history wiped."
            except Exception as e:
                return f"Error clearing history: {e}"

        return "⚠️ Unknown target for /clear. Try: /clear history"

    elif cmd == "/status":
        print("[Command Router] Status query triggered.")
        
        ram_used = "Unknown"
        if os.path.exists("/proc/meminfo"):
            try:
                with open("/proc/meminfo", "r") as f:
                    lines = f.readlines()
                total = int(lines[0].split()[1]) // 1024
                free = int(lines[1].split()[1]) // 1024
                ram_used = f"{total - free} MB / {total} MB"
            except Exception:
                pass
                
        cpu_load = "Unknown"
        if os.path.exists("/proc/loadavg"):
            try:
                with open("/proc/loadavg", "r") as f:
                    cpu_load = f.read().split()[0]
            except Exception:
                pass
                
        reminder_count = 0
        if os.path.exists("reminders.txt"):
            try:
                with open("reminders.txt", "r") as f:
                    reminder_count = len([l for l in f.readlines() if l.strip()])
            except Exception:
                pass

        knowledge_count = 0
        if os.path.exists("knowledge.json"):
            try:
                with open("knowledge.json", "r") as f:
                    knowledge_count = len(json.load(f))
            except Exception:
                pass

        ollama_status = "Offline ❌"
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=5)
            if r.status_code == 200:
                ollama_status = "Online (Active) ✅"
        except Exception:
            pass

        status_text = (
            "🐉 <b>DragonMaid System Status:</b>\n"
            f"• <b>Ollama Connection:</b> {ollama_status}\n"
            f"• <b>Active Model:</b> <code>{MODEL}</code>\n"
            f"• <b>Host RAM Used:</b> {ram_used}\n"
            f"• <b>CPU Load (1m):</b> {cpu_load}\n"
            f"• <b>Configured History Limit:</b> {MAX_HISTORY_MESSAGES} messages\n"
            f"• <b>Scheduled Reminders:</b> {reminder_count} pending\n"
            f"• <b>Knowledge Base Size:</b> {knowledge_count} saved facts"
        )
        return status_text

    return "⚠️ Unknown command."


# --- Dual-Mode Execution Launchers ---

def run_cli_mode():
    """Starts the local CLI conversational terminal loop."""
    global LAST_ACTIVITY_TIME, HAS_DREAMED_SINCE_ACTIVITY
    
    print("=== DRAGONMAID TERMINAL CLI MODE ACTIVE ===")
    print(f"Type 'exit' to quit. Context history is synced with {HISTORY_FILE}.\n")
    # Start emergency listener (press ESC to immediately terminate)
    try:
        listener = EmergencyListener()
        listener.start()
        print("Press ESC at any time to trigger EMERGENCY SHUTDOWN.")
    except Exception:
        pass
    
    messages = Memory.load()
    
    if len(messages) > 1:
        print("[System] Loaded existing conversation memory:")
        for msg in messages:
            if msg["role"] == "user":
                print(f"You (from history): {msg['content']}")
            elif msg["role"] == "assistant" and msg.get("content"):
                print(f"DragonMaid (from history): {msg['content']}")
        print("-" * 50 + "\n")
        
    while True:
        try:
            user_input = input("[You]: ").strip()
            if user_input.lower() == "exit":
                break
            if not user_input:
                continue

            if user_input.startswith("/"):
                reply = handle_command(user_input)
                clean_reply = format_cli_output(reply)
                print(f"DragonMaid: {clean_reply}\n")
                continue
                
            LAST_ACTIVITY_TIME = time.time()
            HAS_DREAMED_SINCE_ACTIVITY = False

            messages.append({"role": "user", "content": user_input})
            
            try:
                reply = run_agent_turn(messages)
                clean_reply = format_cli_output(reply)
                print(f"DragonMaid: {clean_reply}\n")
            except Exception as e:
                print(f"\n[Error during execution]: {e}")
                import traceback
                traceback.print_exc()
                print()
            
        except KeyboardInterrupt:
            print("\nShutting down DragonMaid...")
            break


def run_telegram_mode():
    """Starts the safe long-polling Telegram bot gateway."""
    bot_info = send_telegram_request("getMe", {})
    if bot_info.get("ok"):
        print(f"[Diag] Connected. Bot: @{bot_info['result']['username']}")
    else:
        print(f"[Diag] ERROR: Unauthorized.")
        sys.exit(1)

    try:
        ollama_test = requests.get("http://localhost:11434/api/tags", timeout=5)
        if ollama_test.status_code == 200:
            print("[Diag] Ollama is active.")
    except Exception as e:
        print(f"[Diag] WARNING: Ollama is offline: {e}")

    print("\n[Diag] Diagnostics Passed! Listening...")
    print("-" * 45)

    scheduler = BackgroundScheduler(run_agent_turn_fn=run_agent_turn)
    
    print("[Diag] Flushing old pending messages from Telegram queue...")
    startup_flush = send_telegram_request("getUpdates", {"offset": -1, "limit": 1, "timeout": 0}, timeout=5)
    offset = 0
    if startup_flush.get("ok") and startup_flush.get("result"):
        offset = startup_flush["result"][0]["update_id"] + 1
    print("[Diag] Queue flushed. Listening for NEW messages only.")
    print("-" * 45)

    while True:
        try:
            scheduler.tick()

            updates = send_telegram_request("getUpdates", {"offset": offset, "timeout": 15})
            if not updates.get("ok"):
                time.sleep(2)
                continue
                
            results = updates.get("result", [])
            if not results:
                continue

            offset = results[-1]["update_id"] + 1

            send_telegram_request("getUpdates", {"offset": offset, "limit": 1, "timeout": 0}, timeout=2)

            for update in results:
                if "message" in update and "text" in update["message"]:
                    msg = update["message"]
                    sender_id = msg["from"]["id"]
                    text = msg["text"]
                    
                    print(f"\n[Telegram] New message from ID: {sender_id}: '{text}'")
                    if sender_id != ALLOWED_USER_ID:
                        continue

                    if text.startswith("/"):
                        reply = handle_command(text)
                        send_telegram_request("sendMessage", {
                            "chat_id": ALLOWED_USER_ID,
                            "text": reply,
                            "parse_mode": "HTML"
                        })
                        continue
                    
                    global LAST_ACTIVITY_TIME, HAS_DREAMED_SINCE_ACTIVITY
                    LAST_ACTIVITY_TIME = time.time()
                    HAS_DREAMED_SINCE_ACTIVITY = False

                    messages = Memory.load()
                    messages.append({"role": "user", "content": text})
                    
                    send_telegram_request("sendChatAction", {"chat_id": ALLOWED_USER_ID, "action": "typing"})
                    
                    try:
                        reply = run_agent_turn(messages)
                    except PermissionError as e:
                        if str(e).startswith("STEER_INTERRUPT:"):
                            steer_text = str(e).split("STEER_INTERRUPT:")[1]
                            print(f"[Steering] Aborted current task. Redirecting to: '{steer_text}'")
                            
                            messages.append({
                                "role": "system",
                                "content": "[User Interrupt] The user aborted your previous task mid-turn and steered you in a new direction."
                            })
                            messages.append({"role": "user", "content": steer_text})
                            
                            send_telegram_request("sendMessage", {
                                "chat_id": ALLOWED_USER_ID,
                                "text": f"🔄 <b>Redirecting Task:</b> <i>{html.escape(steer_text)}</i>",
                                "parse_mode": "HTML"
                            })
                            send_telegram_request("sendChatAction", {"chat_id": ALLOWED_USER_ID, "action": "typing"})
                            
                            reply = run_agent_turn(messages)
                        else:
                            reply = "❌ <b>Operation cancelled. Code execution was denied by the user.</b>"
                    
                    print(f"[Telegram] Sending response: '{reply}'")
                    send_telegram_request("sendMessage", {
                        "chat_id": ALLOWED_USER_ID,
                        "text": reply,
                        "parse_mode": "HTML"
                    })
                    
        except KeyboardInterrupt:
            print("\nShutting down DragonMaid...")
            break
        except Exception as e:
            print(f"[Error in Main Loop]: {e}")
            time.sleep(5)


def main():
    global RUN_MODE
    print(" ")
    print(" ")
    print(" ")
    print(" ")
    print(" ██████╗ ██████╗  █████╗  ██████╗  ██████╗ ███╗   ██╗███╗   ███╗ █████╗ ██╗██████╗  ")
    print(" ██╔══██╗██╔══██╗██╔══██╗██╔════╝ ██╔═══██╗████╗  ██║████╗ ████║██╔══██╗██║██╔══██╗ ")
    print(" ██║  ██║██████╔╝███████║██║  ███╗██║   ██║██╔██╗ ██║██╔████╔██║███████║██║██║  ██║ ")
    print(" ██║  ██║██╔══██╗██╔══██║██║   ██║██║   ██║██║╚██╗██║██║╚██╔╝██║██╔══██║██║██║  ██║ ")
    print(" ██████╔╝██║  ██║██║  ██║╚██████╔╝╚██████╔╝██║ ╚████║██║ ╚═╝ ██║██║  ██║██║██████╔╝ ")
    print(" ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝╚═════╝  ") 
    print(" ")
    print(" ")
    print(" ")
    print("─────────────────────────────────────────────────────────────────────────────────────")
    print(" ")
    print(" ")
    
    print("Select Security Profile:")
    print("1] Standard Secure Mode (Docker sandbox execution only)")
    print("2] Host Control Mode (Allows direct Host commands, SSH, Cisco tools)")
    print("-" * 45)
    
    sec_choice = input("Select Profile [1 or 2]: ").strip()
    
    if sec_choice == "2":
        allow_host = True
    elif sec_choice == "1":
        allow_host = False
    else:
        # Fall back to your .env file
        allow_host = os.getenv("ALLOW_HOST_EXECUTION", "false").strip().lower() == "true"
        
    # Apply changes to schemas and function mappings cleanly
    initialize_security_profile(allow_host)
    
    print("\nSelect Interface Mode:")
    print("1] Chat Locally in Server Terminal [CLI]")
    print("2] Launch Always-On Telegram Bot Gateway")
    print("-" * 45)
    
    choice = input("Enter Choice [1 or 2]: ").strip()
    
    if choice == "2":
        RUN_MODE = "telegram"
        run_telegram_mode()
    else:
        RUN_MODE = "cli"
        run_cli_mode()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down DragonMaid...")
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
