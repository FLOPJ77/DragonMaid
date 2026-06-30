import os
import re
from datetime import datetime
from src.config import config
from src.logger import logger
from src.llm import query_ollama

# Global state to monitor activity
activity_state = {
    "last_activity_time": datetime.now(),
    "has_dreamed": True # Set True initially so it doesn't dream immediately on startup
}

def record_activity():
    """
    Called whenever user input, agent response, or tool execution happens
    to delay idle dream state.
    """
    activity_state["last_activity_time"] = datetime.now()
    activity_state["has_dreamed"] = False

def run_dream_mode():
    """
    Consolidates recent chat logs and updates knowledge.md in the workspace.
    """
    logger.dream("Entering Dream Mode: Consolidating memory...")
    
    # 1. Read recent chat logs from dragonmaid.log
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_path = os.path.join(project_root, "dragonmaid.log")
    
    recent_history = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                # Read last 300 lines of logs to consolidate
                lines = f.readlines()[-300:]
                
            for line in lines:
                # Match lines like: [timestamp] [USER_INPUT/AGENT_OUTPUT] [System/Agent] message
                match = re.match(r'^\[([^\]]+)\]\s+\[(USER_INPUT|AGENT_OUTPUT)\]\s+\[([^\]]+)\]\s+(.*)$', line)
                if match:
                    timestamp = match.group(1)
                    role = "User" if match.group(2) == "USER_INPUT" else match.group(3)
                    msg = match.group(4)
                    recent_history.append(f"[{timestamp}] {role}: {msg}")
        except Exception as e:
            logger.error("System", f"Dream Mode: Failed to parse log file: {e}")
            
    history_text = "\n".join(recent_history)
    if not history_text:
        logger.dream("No recent activity logs found to consolidate. Dream Mode skipped.")
        activity_state["has_dreamed"] = True
        return "No recent logs found. Dream Mode skipped."
        
    # 2. Read existing knowledge.md
    knowledge_path = os.path.join(config.workspace_dir, "knowledge.md")
    existing_knowledge = ""
    if os.path.exists(knowledge_path):
        try:
            with open(knowledge_path, "r", encoding="utf-8") as f:
                existing_knowledge = f.read()
        except Exception as e:
            logger.error("System", f"Dream Mode: Failed to read knowledge.md: {e}")
            
    # 3. Build synthesis prompt
    dream_prompt = f"""You are a personal profile compiler for DragonMaid House.
Review the following recent conversation history:
--- RECENT HISTORY ---
{history_text}
----------------------

Existing Profile:
{existing_knowledge or "[No existing profile]"}

Please synthesize this information and compile a clean, minimal user profile card.
Only keep critical permanent facts: Name, Surname, Job/Role, and essential user settings/preferences.
Do NOT include conversation summaries, task details, or topic explanations. Keep the entire profile under 5 bullet points.

Format the output strictly as a markdown document:
# User Profile
- Name: <value>
- Job/Role: <value>
- Key Notes: <value>

Output ONLY the markdown. Do NOT wrap it in a code block. Do NOT write any introduction or conversation.
"""

    messages = [
        {"role": "system", "content": "You are a dense user profile compiler. Output user profile markdown directly with no conversational text."},
        {"role": "user", "content": dream_prompt}
    ]
    
    # Call Ollama
    summary = query_ollama(messages)
    
    # 4. Save back to knowledge.md
    if summary and not summary.startswith("Error"):
        # Strip code block wrapping if model ignored instructions
        clean_summary = summary.strip()
        if clean_summary.startswith("```markdown"):
            clean_summary = clean_summary[11:]
        elif clean_summary.startswith("```"):
            clean_summary = clean_summary[3:]
        if clean_summary.endswith("```"):
            clean_summary = clean_summary[:-3]
            
        clean_summary = clean_summary.strip()
        
        try:
            os.makedirs(config.workspace_dir, exist_ok=True)
            with open(knowledge_path, "w", encoding="utf-8") as f:
                f.write(clean_summary)
            logger.dream(f"Knowledge consolidated and written to {knowledge_path}")
            activity_state["has_dreamed"] = True
            return f"Success: Dream Mode completed. Knowledge updated at {knowledge_path}"
        except Exception as e:
            logger.error("System", f"Dream Mode: Failed to write knowledge.md: {e}")
            return f"Error: Failed to save consolidated knowledge: {str(e)}"
    else:
        logger.warning("System", "Dream Mode: Model failed to generate memory consolidation.")
        return "Error: Memory consolidation failed."
