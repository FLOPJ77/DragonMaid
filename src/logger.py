import os
import sys
from datetime import datetime

class Logger:
    def __init__(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.log_path = os.path.join(project_root, "dragonmaid.log")
        
    def _log(self, level, agent, message):
        timestamp = datetime.now().isoformat()
        log_line = f"[{timestamp}] [{level}] [{agent}] {message}"
        
        # Append to log file
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except Exception as e:
            print(f"Logging error: Could not write to {self.log_path}. Error: {e}", file=sys.stderr)
            
        # Optional: Print to stderr/stdout for development/CLI if verbose (we will print from CLI UI directly though)
        
    def info(self, agent, message):
        self._log("INFO", agent, message)
        
    def warning(self, agent, message):
        self._log("WARNING", agent, message)
        
    def error(self, agent, message):
        self._log("ERROR", agent, message)
        
    def user_input(self, text):
        self._log("USER_INPUT", "System", text)
        
    def agent_output(self, agent, text):
        self._log("AGENT_OUTPUT", agent, text)
        
    def tool_call(self, agent, tool_name, args):
        self._log("TOOL_CALL", agent, f"Called {tool_name} with args: {args}")
        
    def tool_result(self, agent, tool_name, result):
        # Truncate result in logs if it's too long, but keep standard details
        max_log_len = 500
        res_str = str(result)
        if len(res_str) > max_log_len:
            res_str = res_str[:max_log_len] + f"... [truncated, total {len(res_str)} chars]"
        self._log("TOOL_RESULT", agent, f"Result from {tool_name}: {res_str}")
        
    def dream(self, message):
        self._log("DREAM_MODE", "System", message)

logger = Logger()
