import os
import subprocess
import requests
import json
import urllib.parse
from datetime import datetime, timedelta
import re
import uuid
from html import unescape
from src.config import config
from src.logger import logger

# Helper to check and resolve path securely inside workspace
def resolve_safe_path(relative_path):
    # Ensure workspace directory exists
    if not os.path.exists(config.workspace_dir):
        os.makedirs(config.workspace_dir, exist_ok=True)
        
    # Standardize path
    joined = os.path.join(config.workspace_dir, relative_path)
    resolved = os.path.abspath(joined)
    
    # Enforce directory jail
    if os.path.commonpath([config.workspace_dir, resolved]) == config.workspace_dir:
        return resolved
    raise PermissionError(f"Access Denied: Path '{relative_path}' is outside the authorized workspace.")

# 1. FILE MANAGER TOOL
def file_manager(action, path, content=None):
    """
    Manage files and folders securely in the workspace.
    action: 'list' (list files), 'read' (read file), 'write' (create/overwrite file), 'delete' (delete file/folder)
    path: path relative to the workspace
    content: string content for write action
    """
    try:
        if action == "list":
            safe_path = resolve_safe_path(path)
            if not os.path.exists(safe_path):
                return f"Error: Path '{path}' does not exist."
            
            if os.path.isdir(safe_path):
                items = os.listdir(safe_path)
                result = []
                for item in sorted(items):
                    full_item_path = os.path.join(safe_path, item)
                    is_dir = os.path.isdir(full_item_path)
                    size = os.path.getsize(full_item_path) if not is_dir else "-"
                    item_type = "DIR" if is_dir else "FILE"
                    result.append(f"{item_type:4} | {item} | {size} bytes" if not is_dir else f"{item_type:4} | {item}/")
                return "\n".join(result) if result else "Directory is empty."
            else:
                return f"Error: '{path}' is a file, not a directory. Use action='read' instead."
                
        elif action == "read":
            safe_path = resolve_safe_path(path)
            if not os.path.exists(safe_path):
                return f"Error: File '{path}' does not exist."
            if os.path.isdir(safe_path):
                return f"Error: '{path}' is a directory. Use action='list' instead."
                
            with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
                
        elif action == "write":
            safe_path = resolve_safe_path(path)
            # Create parent dirs if necessary
            os.makedirs(os.path.dirname(safe_path), exist_ok=True)
            with open(safe_path, "w", encoding="utf-8") as f:
                f.write(content or "")
            return f"Success: File '{path}' written successfully."
            
        elif action == "delete":
            safe_path = resolve_safe_path(path)
            if not os.path.exists(safe_path):
                return f"Error: Path '{path}' does not exist."
                
            if os.path.isdir(safe_path):
                # Simple recursive delete
                import shutil
                shutil.rmtree(safe_path)
                return f"Success: Directory '{path}' and all contents deleted."
            else:
                os.remove(safe_path)
                return f"Success: File '{path}' deleted."
        else:
            return f"Error: Unknown action '{action}'."
            
    except PermissionError as pe:
        return str(pe)
    except Exception as e:
        return f"Error executing file_manager: {str(e)}"

# 2. BASH EXECUTION TOOL
def bash_exec(command):
    """
    Run bash command.
    Only allowed if ALLOW_HOST_EXECUTION is true.
    """
    if not config.allow_host_execution:
        return ("Host execution is disabled by default for security. "
                "To enable bash/python commands, set ALLOW_HOST_EXECUTION=true in the .env configuration.")
                
    try:
        # Resolve workspace path and use it as cwd
        if not os.path.exists(config.workspace_dir):
            os.makedirs(config.workspace_dir, exist_ok=True)
            
        res = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=config.workspace_dir
        )
        output = []
        if res.stdout:
            output.append(res.stdout)
        if res.stderr:
            output.append("[STDERR]\n" + res.stderr)
        return "\n".join(output) if output else "[Command finished with no output]"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 30 seconds."
    except Exception as e:
        return f"Error running bash command: {str(e)}"

# 3. PYTHON EXECUTION TOOL
def python_exec(code):
    """
    Run Python code snippet.
    Only allowed if ALLOW_HOST_EXECUTION is true.
    """
    if not config.allow_host_execution:
        return ("Host execution is disabled by default for security. "
                "To enable bash/python commands, set ALLOW_HOST_EXECUTION=true in the .env configuration.")
                
    try:
        if not os.path.exists(config.workspace_dir):
            os.makedirs(config.workspace_dir, exist_ok=True)
            
        res = subprocess.run(
            ["python3", "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=config.workspace_dir
        )
        output = []
        if res.stdout:
            output.append(res.stdout)
        if res.stderr:
            output.append("[STDERR]\n" + res.stderr)
        return "\n".join(output) if output else "[Code executed successfully with no output]"
    except subprocess.TimeoutExpired:
        return "Error: Code execution timed out after 30 seconds."
    except Exception as e:
        return f"Error executing Python code: {str(e)}"

# 4. WEB SEARCH TOOL (DuckDuckGo HTML Search + Wikipedia)
def web_search(query):
    """
    Queries DuckDuckGo HTML search for real-time web results and Wikipedia for encyclopedic depth.
    Combines results (up to 3 from DuckDuckGo and 2 from Wikipedia) to provide both fresh news and rich facts.
    """
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 1. Query DuckDuckGo HTML search (up to 3 results)
    ddg_html_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}"
    try:
        r = requests.get(ddg_html_url, headers=headers, timeout=8)
        if r.status_code == 200:
            html = r.text
            
            # Find result__title links
            title_matches = re.findall(
                r'<h2 class="result__title">\s*<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                html,
                re.DOTALL
            )
            
            # Find result__snippet text blocks
            snippet_matches = re.findall(
                r'<a class="result__snippet"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                html,
                re.DOTALL
            )
            
            for i in range(min(len(title_matches), len(snippet_matches))):
                if len(results) >= 3:
                    break
                raw_url, title_raw = title_matches[i]
                _, snippet_raw = snippet_matches[i]
                
                title = re.sub(r'<[^>]*>', '', title_raw).strip()
                title = unescape(title)
                
                snippet = re.sub(r'<[^>]*>', '', snippet_raw).strip()
                snippet = unescape(snippet)
                
                url_href = raw_url
                if "uddg=" in url_href:
                    parsed_url = urllib.parse.urlparse(url_href)
                    query_params = urllib.parse.parse_qs(parsed_url.query)
                    real_url = query_params.get("uddg", [url_href])[0]
                else:
                    real_url = url_href
                    if real_url.startswith("//"):
                        real_url = "https:" + real_url
                        
                results.append({
                    "title": title,
                    "snippet": snippet,
                    "url": real_url,
                    "source": "Web Search"
                })
    except Exception:
        pass
        
    # 2. Query Wikipedia Search API (up to 2 results, or up to 5 if DDG returned nothing)
    max_wiki = 5 if not results else 2
    wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote_plus(query)}&format=json&utf8="
    try:
        r = requests.get(wiki_url, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            search_items = data.get("query", {}).get("search", [])
            for item in search_items[:max_wiki]:
                title = item.get("title", "")
                snippet_raw = item.get("snippet", "")
                snippet = re.sub(r'<[^>]*>', '', snippet_raw)
                snippet = unescape(snippet)
                url_encoded_title = urllib.parse.quote(title.replace(" ", "_"))
                url = f"https://en.wikipedia.org/wiki/{url_encoded_title}"
                
                results.append({
                    "title": title,
                    "snippet": snippet,
                    "url": url,
                    "source": "Wikipedia"
                })
    except Exception:
        pass
        
    # 3. Fallback to DDG Instant Answers if we still have absolutely nothing
    if not results:
        ddg_api_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote_plus(query)}&format=json&no_html=1"
        try:
            r = requests.get(ddg_api_url, headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                abstract = data.get("AbstractText", "")
                abstract_url = data.get("AbstractURL", "")
                if abstract:
                    results.append({
                        "title": data.get("Heading", "Instant Answer"),
                        "snippet": abstract,
                        "url": abstract_url,
                        "source": "Instant Answer"
                    })
        except Exception:
            pass
            
    if not results:
        return f"No search results found for '{query}'."
        
    formatted_results = []
    for idx, r in enumerate(results[:5]):
        formatted_results.append(
            f"[{idx+1}] {r['title']} ({r.get('source', 'Search')})\n"
            f"Snippet: {r['snippet']}\n"
            f"Link: {r['url']}\n"
        )
    return "\n".join(formatted_results)

# 5. TIME INJECT TOOL
def time_inject():
    """
    Returns the current formatted date and time.
    """
    now = datetime.now()
    return f"Current local time: {now.strftime('%A, %B %d, %Y, %I:%M:%S %p')} (ISO: {now.isoformat()})"

# 6. REMINDERS TOOL
def reminders(action, time=None, message=None, recipient="user", format_for_user=False):
    """
    Manage reminders.
    action: 'schedule' (schedule a reminder), 'list' (list pending reminders), 'cancel' (cancel a reminder)
    time: relative (e.g. 'in 5m', 'in 2h') or absolute (HH:MM or YYYY-MM-DD HH:MM:SS)
    message: text description of the reminder
    recipient: 'user' or 'agent'
    """
    reminders_file = resolve_safe_path("reminders.json")
    
    # Load existing reminders
    all_reminders = []
    if os.path.exists(reminders_file):
        try:
            with open(reminders_file, "r", encoding="utf-8") as f:
                all_reminders = json.load(f)
        except Exception:
            all_reminders = []
            
    if action == "schedule":
        if not time or not message:
            return "Error: Both 'time' and 'message' are required to schedule a reminder."
            
        target_time = parse_reminder_time(time)
        if not target_time:
            return f"Error: Could not parse time string '{time}'. Examples: 'in 5m', 'in 2h', '18:30', '2026-06-25 18:30:00'."
            
        # Auto-detect recipient if it involves agent tasks
        action_indicators = ["search", "check", "run", "execute", "spawn", "query", "find", "list", "consolidate", "dream"]
        msg_lower = message.lower()
        if any(indicator in msg_lower for indicator in action_indicators):
            recipient = "agent"
            
        reminder_id = str(uuid.uuid4())[:8]
        new_reminder = {
            "id": reminder_id,
            "scheduled_time": target_time.isoformat(),
            "message": message,
            "recipient": recipient,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        all_reminders.append(new_reminder)
        
        # Save reminders
        try:
            with open(reminders_file, "w", encoding="utf-8") as f:
                json.dump(all_reminders, f, indent=2)
        except Exception as e:
            return f"Error saving reminders: {str(e)}"
            
        return f"Success: Reminder '{message}' scheduled for {new_reminder['scheduled_time']} (ID: {reminder_id}, Recipient: {recipient})."
        
    elif action == "list":
        pending = [r for r in all_reminders if r["status"] == "pending"]
        if not pending:
            return "No pending reminders."
            
        res = []
        for r in pending:
            if format_for_user:
                try:
                    dt = datetime.fromisoformat(r["scheduled_time"])
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    time_str = r["scheduled_time"]
                res.append(f"• {r['message']} (at {time_str})")
            else:
                res.append(f"[{r['id']}] Time: {r['scheduled_time']} | Recipient: {r['recipient']} | Message: {r['message']}")
        return "\n".join(res)
        
    elif action == "cancel":
        if not time:
            return "Error: Reminder ID or name is required in the 'time' argument to cancel."
        id_to_cancel = time.strip()
        
        if id_to_cancel.lower() == "all":
            try:
                with open(reminders_file, "w", encoding="utf-8") as f:
                    json.dump([], f, indent=2)
                return "Success: All pending reminders have been deleted."
            except Exception as e:
                return f"Error clearing reminders: {str(e)}"
                
        # Find matches by ID or name
        target = [r for r in all_reminders if r["id"] == id_to_cancel and r["status"] == "pending"]
        if not target:
            target = [r for r in all_reminders if r["status"] == "pending" and id_to_cancel.lower() in r["message"].lower()]
            
        if not target:
            return f"Error: No pending reminder found matching '{id_to_cancel}'."
        elif len(target) > 1:
            names = ", ".join([f"'{r['message']}' (ID: {r['id']})" for r in target])
            return f"Error: Multiple reminders matched '{id_to_cancel}': {names}. Please cancel using a more specific name or ID."
            
        target_reminder = target[0]
        all_reminders = [r for r in all_reminders if r["id"] != target_reminder["id"]]
        
        pending_reminders = [r for r in all_reminders if r["status"] == "pending"]
        try:
            with open(reminders_file, "w", encoding="utf-8") as f:
                json.dump(pending_reminders, f, indent=2)
            return f"Success: Reminder '{target_reminder['message']}' has been deleted."
        except Exception as e:
            return f"Error saving reminders: {str(e)}"
            
    elif action == "edit":
        if not time:
            return "Error: Reminder ID or name is required in the 'time' argument to edit."
        id_to_edit = time.strip()
        
        # Find matches by ID or name
        target = [r for r in all_reminders if r["id"] == id_to_edit and r["status"] == "pending"]
        if not target:
            target = [r for r in all_reminders if r["status"] == "pending" and id_to_edit.lower() in r["message"].lower()]
            
        if not target:
            return f"Error: No pending reminder found matching '{id_to_edit}'."
        elif len(target) > 1:
            names = ", ".join([f"'{r['message']}' (ID: {r['id']})" for r in target])
            return f"Error: Multiple reminders matched '{id_to_edit}': {names}. Please edit using a more specific name or ID."
            
        target_reminder = target[0]
        
        new_time_str = None
        new_msg_str = None
        
        if message:
            if "|" in message:
                parts = message.split("|", 1)
                new_time_str = parts[0].strip()
                new_msg_str = parts[1].strip()
            else:
                parsed_t = parse_reminder_time(message.strip())
                if parsed_t:
                    new_time_str = message.strip()
                else:
                    new_msg_str = message.strip()
                    
        if new_time_str:
            parsed_t = parse_reminder_time(new_time_str)
            if not parsed_t:
                return f"Error: Could not parse new time '{new_time_str}'."
            target_reminder["scheduled_time"] = parsed_t.isoformat()
            
        if new_msg_str:
            target_reminder["message"] = new_msg_str
            
        pending_reminders = [r for r in all_reminders if r["status"] == "pending"]
        try:
            with open(reminders_file, "w", encoding="utf-8") as f:
                json.dump(pending_reminders, f, indent=2)
            return f"Success: Reminder updated. New Message: '{target_reminder['message']}', New Time: {target_reminder['scheduled_time']}."
        except Exception as e:
            return f"Error saving reminders: {str(e)}"
    else:
        return f"Error: Unknown action '{action}'."

def parse_reminder_time(time_str):
    """
    Parses a time string and returns a datetime object in local time.
    Supports relative (in 5m, in 2h, in 1d, 10s, 16h30m) and absolute formats (HH:MM, YYYY-MM-DD HH:MM:SS)
    """
    time_str = time_str.strip().lower()
    now = datetime.now()
    
    # 1. Check relative format: match any sequences of numbers followed by units
    # e.g., "in 16h30m", "2 hours 15 mins", "10s"
    matches = re.findall(r'(\d+)\s*(s|sec|second|m|min|minute|h|hr|hour|d|day)s?', time_str)
    if matches and (time_str.startswith("in ") or any(x in time_str for x in ["s", "m", "h", "d"])):
        total_seconds = 0
        for amount_str, unit in matches:
            amount = int(amount_str)
            if unit.startswith('s'):
                total_seconds += amount
            elif unit.startswith('m'):
                total_seconds += amount * 60
            elif unit.startswith('h'):
                total_seconds += amount * 3600
            elif unit.startswith('d'):
                total_seconds += amount * 86400
        if total_seconds > 0:
            return now + timedelta(seconds=total_seconds)
            
    # 2. Check HH:MM format
    match_hm = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
    if match_hm:
        hour = int(match_hm.group(1))
        minute = int(match_hm.group(2))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target < now:
            # Scheduled for tomorrow if time has already passed today
            target += timedelta(days=1)
        return target
        
    # 3. Check full ISO/datetime format
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M'):
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue
            
    return None

# Route tool calls dynamically
def execute_tool(tool_name, args):
    """
    Routes tool execution based on the JSON parser findings.
    """
    # Standardize argument parsing safely
    if not isinstance(args, dict):
        return f"Error: Tool arguments must be a dictionary. Got: {type(args)}"
        
    logger.tool_call("System", tool_name, args)
    
    if tool_name == "file_manager":
        res = file_manager(args.get("action"), args.get("path"), args.get("content"))
    elif tool_name == "bash_exec":
        res = bash_exec(args.get("command"))
    elif tool_name == "python_exec":
        res = python_exec(args.get("code"))
    elif tool_name == "web_search":
        res = web_search(args.get("query"))
    elif tool_name == "time_inject":
        res = time_inject()
    elif tool_name == "reminders":
        res = reminders(args.get("action"), args.get("time"), args.get("message"), args.get("recipient", "user"))
    else:
        res = f"Error: Tool '{tool_name}' is not recognized."
        
    logger.tool_result("System", tool_name, res)
    return res
