import sys
import os
import time
import threading
from datetime import datetime
from src.config import config
from src.logger import logger
from src.agents import Agent, HOUSE_PROMPT, run_agent_loop
from src.memory import run_dream_mode, record_activity
from src.tools import reminders

# ANSI Colors - Soft Pink, Soft Red, White, Dim Gray
COLOR_RESET = "\033[0m"
COLOR_HOUSE = "\033[38;5;218m"    # Soft pink (pastel)
COLOR_USER = "\033[1;37m"         # Bold white
COLOR_SYSTEM = "\033[37m"         # White
COLOR_WARNING = "\033[93m"        # Yellow
COLOR_MODEL = "\033[38;5;117m"      # Soft pastel cyan/light blue
COLOR_ERROR = "\033[38;5;203m"    # Soft red (pastel)
COLOR_DIM = "\033[90m"            # Dark Gray

# System uptime track
app_start_time = datetime.now()

class Spinner:
    def __init__(self, message="Working..."):
        self.message = message
        self.frames = ["⠏", "⠋", "⠙", "⠼", "⠴", "⠦", "⠧"]
        self.active = False
        self.thread = None

    def _spin(self):
        idx = 0
        while self.active:
            # Print frame + message in white
            sys.stdout.write(f"\r\033[37m{self.frames[idx]}\033[0m {self.message}")
            sys.stdout.flush()
            idx = (idx + 1) % len(self.frames)
            time.sleep(0.08)
        # Clear spinner line when stopped
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def start(self):
        if not self.active:
            self.active = True
            self.thread = threading.Thread(target=self._spin, daemon=True)
            self.thread.start()

    def stop(self):
        if self.active:
            self.active = False
            if self.thread:
                self.thread.join()
            self.thread = None

# Maid Delegation Colors
MAID_COLORS = {
    "House": "\033[38;5;225m",        # Even softer pale pink for House delegation
    "Chamber": "\033[38;5;242m",      # Soft dark black/slate
    "Parlor": "\033[38;5;157m",       # Soft pastel green
    "Kitchen": "\033[38;5;210m",      # Soft pastel red
    "Nurse": "\033[38;5;255m",        # Soft pink/white
    "Laundry": "\033[38;5;183m",      # Soft lavender / violet
}

def get_maid_color(name):
    if not name:
        return COLOR_DIM
    clean_name = str(name).replace(" Dragonmaid", "").strip()
    return MAID_COLORS.get(clean_name, COLOR_DIM)

cli_spinner = Spinner("Working...")

def cli_event_handler(event_type, data):
    global cli_spinner
    if event_type == "llm_start":
        agent = data.get("agent", "House Dragonmaid")
        clean_agent = agent.replace(" Dragonmaid", "").strip()
        color = get_maid_color(clean_agent)
        if agent == "House Dragonmaid":
            cli_spinner.message = "Working..."
        else:
            cli_spinner.message = f"{color}{clean_agent}{COLOR_RESET} is working..."
        cli_spinner.start()
    elif event_type == "llm_end":
        cli_spinner.stop()
    elif event_type == "tool_start":
        cli_spinner.stop()
        tool_name = data.get("tool")
        print(f"{COLOR_DIM}[tool execution] [{tool_name}] executing...{COLOR_RESET}")
    elif event_type == "tool_end":
        cli_spinner.stop()
    elif event_type == "spawn_start":
        cli_spinner.stop()
        child = data.get("child", "").replace(" Dragonmaid", "").strip()
        instruction = data.get("instruction")
        house_col = get_maid_color("House")
        child_col = get_maid_color(child)
        print(f"{COLOR_DIM}[maid delegation] {house_col}[House]{COLOR_DIM} requested help from {child_col}[{child}]{COLOR_DIM} for: \"{instruction}\"{COLOR_RESET}")
    elif event_type == "spawn_end":
        cli_spinner.stop()
        child = data.get("child", "").replace(" Dragonmaid", "").strip()
        child_col = get_maid_color(child)
        print(f"{COLOR_DIM}[maid delegation] {child_col}[{child}]{COLOR_DIM} finished task.{COLOR_RESET}")

def print_house(text):
    print(f"\n{COLOR_HOUSE}[House Dragonmaid]{COLOR_RESET} {text}")

def print_system(text):
    print(f"{COLOR_SYSTEM}[System]{COLOR_RESET} {text}")

def print_warning(text):
    print(f"{COLOR_WARNING}[Warning]{COLOR_RESET} {text}")

def print_error(text):
    print(f"{COLOR_ERROR}[Error]{COLOR_RESET} {text}")

def get_uptime():
    delta = datetime.now() - app_start_time
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{delta.days}d {hours}h {minutes}m {seconds}s"

def display_help():
    help_text = f"""
{COLOR_HOUSE}DragonMaid House — Command Line Interface{COLOR_RESET}
Available Commands:
  {COLOR_SYSTEM}/help{COLOR_RESET}          - List available commands
  {COLOR_SYSTEM}/model <name>{COLOR_RESET}  - Switch the active Ollama model on the fly
  {COLOR_SYSTEM}/host [on/off]{COLOR_RESET} - Enable/disable or toggle host execution (shell/python commands)
  {COLOR_SYSTEM}/dream{COLOR_RESET}         - Trigger Dream Mode memory consolidation immediately
  {COLOR_SYSTEM}/status{COLOR_RESET}        - Show active model, uptime, and pending reminders
  {COLOR_SYSTEM}/clear{COLOR_RESET}         - Clear the current conversation history
  {COLOR_SYSTEM}/stop{COLOR_RESET}          - Emergency stop and shutdown the system
"""
    print(help_text)

def handle_command(cmd_line, chat_history):
    cmd_parts = cmd_line.strip().split(" ", 1)
    cmd = cmd_parts[0].lower()
    arg = cmd_parts[1] if len(cmd_parts) > 1 else ""
    
    if cmd == "/help":
        display_help()
        return True
    elif cmd == "/model":
        if not arg:
            print_error("Please specify a model name. Example: /model qwen2.5-coder:3b")
        else:
            config.model = arg
            logger.info("System", f"Switched model to: {arg}")
            print_system(f"Active model switched to '{COLOR_MODEL}{arg}{COLOR_SYSTEM}'")
        return True
    elif cmd == "/host":
        if arg.lower() in ("on", "true", "1", "yes"):
            config.allow_host_execution = True
            logger.info("System", "Host execution enabled via command.")
            print_system("Host execution has been enabled.")
        elif arg.lower() in ("off", "false", "0", "no"):
            config.allow_host_execution = False
            logger.info("System", "Host execution disabled via command.")
            print_system("Host execution has been disabled.")
        elif not arg:
            config.allow_host_execution = not config.allow_host_execution
            logger.info("System", f"Host execution toggled to: {config.allow_host_execution}")
            print_system(f"Host execution is now {'ENABLED' if config.allow_host_execution else 'DISABLED'}.")
        else:
            print_error("Invalid argument. Use: /host [on/off]")
        return True
    elif cmd == "/dream":
        print_system("Triggering manual Dream Mode consolidation...")
        res = run_dream_mode()
        print_system(res)
        return True
    elif cmd == "/status":
        print_system("Current Framework Status:")
        print(f"  Active Model:      {config.model}")
        print(f"  System Uptime:     {get_uptime()}")
        print(f"  Workspace:         {config.workspace_dir}")
        print(f"  Host Execution:    {'ENABLED' if config.allow_host_execution else 'DISABLED'}")
        print("  Pending Reminders:")
        rem_list = reminders("list", format_for_user=True)
        for line in rem_list.split("\n"):
            print(f"    {line}")
        return True
    elif cmd == "/clear":
        chat_history.clear()
        from src.llm import unload_model
        unload_model()
        logger.info("System", "Chat session history cleared and model unloaded by user command.")
        print_system("Active chat session history has been cleared and the model has been unloaded from RAM.")
        return True
    elif cmd == "/stop":
        print_system("Graceful shutdown requested. Unloading model...")
        from src.llm import unload_model
        unload_model()
        print_system("Good bye!")
        sys.exit(0)
    else:
        print_error(f"Unknown command '{cmd}'. Type /help for assistance.")
        return True

def run_cli_loop():
    # Initialize main agent
    house_agent = Agent("House Dragonmaid", HOUSE_PROMPT)
    chat_history = []
    
    print(f"\n{COLOR_HOUSE}*** Welcome to the DragonMaid House local LLM Framework ***{COLOR_RESET}")
    print(f"Default model: {COLOR_MODEL}{config.model}{COLOR_RESET}")
    print("Type /help to list available commands. Press Ctrl+C at any prompt to exit.")
    
    while True:
        try:
            # Refresh activity record on loop start
            record_activity()
            
            # Read input
            prompt = input(f"\n{COLOR_USER}You > {COLOR_RESET}").strip()
            if not prompt:
                continue
                
            # Handle commands
            if prompt.startswith("/"):
                handle_command(prompt, chat_history)
                continue
                
            # Log and update activity
            logger.user_input(prompt)
            record_activity()
            
            # Start reasoning loop with current history context and event spinner
            response, updated_history = run_agent_loop(
                house_agent,
                prompt,
                external_history=chat_history,
                on_event=cli_event_handler
            )
            cli_spinner.stop()
            
            # Update history reference
            chat_history.clear()
            chat_history.extend(updated_history)
            
            # Print response
            print_house(response)
            record_activity()
            
        except KeyboardInterrupt:
            # Handle user interruption graceful exit
            cli_spinner.stop()
            print("\n")
            print_warning("Emergency stop caught. Unloading model...")
            from src.llm import unload_model
            unload_model()
            print_warning("Shutting down framework...")
            logger.info("System", "Application terminated by Ctrl+C.")
            sys.exit(0)
        except Exception as e:
            print_error(f"CLI Loop Error: {e}")
            logger.error("CLI", f"Error in loop: {str(e)}")
            time.sleep(1)
