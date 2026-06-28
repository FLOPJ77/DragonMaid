import os
import sys
import time
import json
import warnings
warnings.filterwarnings("ignore")
import threading
from datetime import datetime

# Add project root to sys.path to ensure correct imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config import config
from src.logger import logger
from src.cli import run_cli_loop, COLOR_HOUSE, COLOR_RESET, COLOR_USER
from src.telegram_bot import poll_telegram_updates, send_telegram_message
from src.memory import activity_state, run_dream_mode
from src.agents import Agent, HOUSE_PROMPT, run_agent_loop

def initialize_workspace():
    """
    Sets up the authorized workspace folder and initial configuration files.
    """
    if not os.path.exists(config.workspace_dir):
        os.makedirs(config.workspace_dir, exist_ok=True)
        logger.info("System", f"Created workspace directory at {config.workspace_dir}")
        
    reminders_file = os.path.join(config.workspace_dir, "reminders.json")
    if not os.path.exists(reminders_file):
        try:
            with open(reminders_file, "w", encoding="utf-8") as f:
                json.dump([], f)
            logger.info("System", "Initialized empty reminders.json")
        except Exception as e:
            logger.error("System", f"Failed to initialize reminders.json: {e}")

def run_agent_reminder_task(message_text):
    """
    Runs the agent reasoning loop in a separate thread when an agent reminder fires.
    """
    logger.info("House Dragonmaid", f"Executing self-reminder reasoning task: {message_text}")
    try:
        agent = Agent("House Dragonmaid", HOUSE_PROMPT)
        # Run agent loop with reminder context
        response, _ = run_agent_loop(agent, f"You set a reminder for yourself: '{message_text}'. Please investigate or perform the necessary actions now.")
        
        # Display response on local CLI terminal
        print(f"\n{COLOR_HOUSE}[House Dragonmaid (Self Reminder Notification)]{COLOR_RESET} {response}")
        print(f"{COLOR_USER}You > {COLOR_RESET}", end="", flush=True)
        
        # Broadcast response to whitelisted Telegram users
        if config.telegram_bot_token and config.allowed_user_ids:
            for user_id in config.allowed_user_ids:
                send_telegram_message(
                    user_id, 
                    f"⏰ *Self-Reminder Fired*:\n_{message_text}_\n\n🤖 *House Dragonmaid Action Report*:\n{response}"
                )
    except Exception as e:
        logger.error("System", f"Failed to run agent reminder thread: {e}")

def poll_reminders_loop():
    """
    Background loop checking scheduled reminders.json every 5 seconds.
    """
    reminders_file = os.path.join(config.workspace_dir, "reminders.json")
    
    while True:
        try:
            if os.path.exists(reminders_file):
                # Load current reminders list
                with open(reminders_file, "r", encoding="utf-8") as f:
                    all_reminders = json.load(f)
                    
                updated = False
                now = datetime.now()
                
                for r in all_reminders:
                    if r["status"] == "pending":
                        try:
                            scheduled_dt = datetime.fromisoformat(r["scheduled_time"])
                        except Exception:
                            scheduled_dt = None
                            
                        if scheduled_dt and scheduled_dt <= now:
                            r["status"] = "fired"
                            updated = True
                        
                            msg = r["message"]
                            recipient = r["recipient"]
                            
                            logger.info("System", f"Firing reminder (ID: {r['id']}, Recipient: {recipient}): {msg}")
                            
                            if recipient == "user":
                                # Output to local console
                                print(f"\n🔔 {COLOR_HOUSE}[User Reminder Alert]{COLOR_RESET} {msg}")
                                print(f"{COLOR_USER}You > {COLOR_RESET}", end="", flush=True)
                                
                                # Deliver to whitelisted Telegram user IDs
                                if config.telegram_bot_token and config.allowed_user_ids:
                                    for uid in config.allowed_user_ids:
                                        send_telegram_message(uid, f"🔔 *Reminder Alert*:\n{msg}")
                            else:
                                # Recipient is "agent" itself, trigger autonomous loop in thread
                                t = threading.Thread(target=run_agent_reminder_task, args=(msg,), daemon=True)
                                t.start()
                            
                if updated:
                    # Filter out fired reminders to keep file clean
                    pending_reminders = [r for r in all_reminders if r["status"] == "pending"]
                    with open(reminders_file, "w", encoding="utf-8") as f:
                        json.dump(pending_reminders, f, indent=2)
                        
        except Exception as e:
            logger.error("System", f"Error in reminders poller loop: {e}")
            
        time.sleep(5)

def poll_dream_inactivity_loop():
    """
    Background loop checking inactivity to trigger passive Dream Mode memory consolidation.
    """
    while True:
        try:
            # Check elapsed time since last activity record
            elapsed = (datetime.now() - activity_state["last_activity_time"]).total_seconds() / 60.0
            
            if elapsed >= config.dream_inactivity_minutes and not activity_state["has_dreamed"]:
                logger.info("System", f"System inactive for {elapsed:.1f} minutes. Activating Dream Mode...")
                # Start Dream Mode execution
                run_dream_mode()
        except Exception as e:
            logger.error("System", f"Error in dream inactivity poller loop: {e}")
            
        time.sleep(60)

def main():
    logger.info("System", "Starting DragonMaid House local LLM framework...")
    
    # 1. Setup workspace
    initialize_workspace()
    
    # 2. Start background daemons
    reminders_thread = threading.Thread(target=poll_reminders_loop, daemon=True)
    reminders_thread.start()
    logger.info("System", "Reminders checking background thread started.")
    
    dream_thread = threading.Thread(target=poll_dream_inactivity_loop, daemon=True)
    dream_thread.start()
    logger.info("System", "Dream Mode inactivity monitor background thread started.")
    
    # 3. Start Telegram interface if configured
    if config.telegram_bot_token:
        tg_thread = threading.Thread(target=poll_telegram_updates, daemon=True)
        tg_thread.start()
        logger.info("System", "Telegram bot polling background thread started.")
    else:
        logger.info("System", "Telegram bot token is not configured. Running CLI only.")
        
    # 4. Handover main thread to interactive CLI loop
    run_cli_loop()

if __name__ == "__main__":
    main()
