import os
import sys

class Config:
    def __init__(self):
        # Find or load from .env file
        self.load_env()

        self.api_key = os.getenv("API_KEY", "ollama")
        self.api_url = os.getenv("API_URL", "http://localhost:11434/v1/chat/completions")
        self.model = os.getenv("MODEL", "granite4.1:3b")
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        
        # Parse allowed Telegram IDs
        allowed_id_str = os.getenv("ALLOWED_USER_ID")
        self.allowed_user_ids = []
        if allowed_id_str:
            try:
                # Support comma-separated IDs
                self.allowed_user_ids = [int(x.strip()) for x in allowed_id_str.split(",") if x.strip()]
            except ValueError:
                print(f"Warning: Invalid ALLOWED_USER_ID '{allowed_id_str}'. Must be numeric IDs.", file=sys.stderr)
        
        # Security/execution settings
        self.allow_host_execution = self._parse_bool(os.getenv("ALLOW_HOST_EXECUTION", "false"))
        self.bypass_host_gatekeeper = self._parse_bool(os.getenv("BYPASS_HOST_GATEKEEPER", "true"))
        
        # Default workspace directory
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.workspace_dir = os.path.abspath(os.getenv("WORKSPACE_DIR", os.path.join(project_root, "workspace")))
        
        # Loop limit & dream inactivity
        try:
            self.max_iterations = int(os.getenv("MAX_ITERATIONS", "15"))
        except ValueError:
            self.max_iterations = 15
            
        try:
            self.dream_inactivity_minutes = int(os.getenv("DREAM_INACTIVITY_MINUTES", "30"))
        except ValueError:
            self.dream_inactivity_minutes = 30

    def load_env(self):
        # Basic .env parser to avoid heavy external dependencies like python-dotenv
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(project_root, ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, value = line.split("=", 1)
                        # Strip quotes if present
                        key = key.strip()
                        value = value.strip().strip("'\"")
                        if key and not os.environ.get(key):
                            os.environ[key] = value

    def _parse_bool(self, val):
        if not val:
            return False
        return val.lower() in ("true", "1", "yes", "on")

    def save_env_value(self, key, value):
        """
        Updates or appends a key-value pair in the local .env file.
        """
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(project_root, ".env")
        
        lines = []
        key_found = False
        
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, v = stripped.split("=", 1)
                if k.strip() == key:
                    new_lines.append(f"{key}={value}\n")
                    key_found = True
                    continue
            new_lines.append(line)
            
        if not key_found:
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] += "\n"
            new_lines.append(f"{key}={value}\n")
            
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            os.environ[key] = str(value)
        except Exception as e:
            print(f"Error saving {key} to .env: {e}", file=sys.stderr)

# Singleton configuration instance
config = Config()
