import time
import sys
import os
import requests
from src.config import config
from src.logger import logger
from src.agents import Agent, HOUSE_PROMPT, run_agent_loop
from src.memory import run_dream_mode, record_activity
from src.tools import reminders

# Session history map: user_id -> chat_history list
session_histories = {}

# Active agent instance for Telegram sessions
house_agent = Agent("House Dragonmaid", HOUSE_PROMPT)

def send_telegram_message(chat_id, text):
    """
    Helper to send a message to a specific Telegram chat.
    """
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.error("Telegram", f"Failed to send message: HTTP {r.status_code} - {r.text}")
    except Exception as e:
        logger.error("Telegram", f"Exception sending message: {e}")

def send_telegram_action(chat_id, action="typing"):
    """
    Sends a chat action (like 'typing') to a specific Telegram chat.
    """
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendChatAction"
    payload = {
        "chat_id": chat_id,
        "action": action
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error("Telegram", f"Failed to send chat action: {e}")

def handle_telegram_command(cmd_line, chat_id, user_id):
    """
    Processes slash commands originating from Telegram.
    """
    cmd_parts = cmd_line.strip().split(" ", 1)
    cmd = cmd_parts[0].lower()
    arg = cmd_parts[1] if len(cmd_parts) > 1 else ""
    
    if cmd == "/help":
        help_text = (
            "*DragonMaid House — Telegram Interface*\n\n"
            "Available Commands:\n"
            "• `/help` - List available commands\n"
            "• `/model <name>` - Switch Ollama model\n"
            "• `/host [on/off]` - Enable/disable or toggle host execution\n"
            "• `/dream` - Trigger manual Dream Mode memory consolidation\n"
            "• `/status` - Show model, uptime, and reminders\n"
            "• `/clear` - Clear chat history context\n"
            "• `/stop` - Emergency stop / graceful shutdown"
        )
        send_telegram_message(chat_id, help_text)
        
    elif cmd == "/model":
        if not arg:
            send_telegram_message(chat_id, "⚠️ Please specify a model name. Example: `/model qwen2.5-coder:3b`")
        else:
            config.model = arg
            config.save_env_value("MODEL", arg)
            logger.info("Telegram", f"Switched model to: {arg} (by user {user_id})")
            send_telegram_message(chat_id, f"✅ Active model switched to `{arg}`.")
            
    elif cmd == "/host":
        if arg.lower() in ("on", "true", "1", "yes"):
            config.allow_host_execution = True
            config.save_env_value("ALLOW_HOST_EXECUTION", "true")
            logger.info("Telegram", f"Host execution enabled by user {user_id}.")
            send_telegram_message(chat_id, "✅ Host execution has been enabled.")
        elif arg.lower() in ("off", "false", "0", "no"):
            config.allow_host_execution = False
            config.save_env_value("ALLOW_HOST_EXECUTION", "false")
            logger.info("Telegram", f"Host execution disabled by user {user_id}.")
            send_telegram_message(chat_id, "✅ Host execution has been disabled.")
        elif not arg:
            config.allow_host_execution = not config.allow_host_execution
            val_str = "true" if config.allow_host_execution else "false"
            config.save_env_value("ALLOW_HOST_EXECUTION", val_str)
            logger.info("Telegram", f"Host execution toggled to {config.allow_host_execution} by user {user_id}.")
            status_str = "ENABLED" if config.allow_host_execution else "DISABLED"
            send_telegram_message(chat_id, f"🔄 Host execution is now *{status_str}*.")
        else:
            send_telegram_message(chat_id, "⚠️ Invalid argument. Use: `/host [on/off]`")
            
    elif cmd == "/dream":
        send_telegram_message(chat_id, "💤 Consolidating memory in Dream Mode...")
        res = run_dream_mode()
        send_telegram_message(chat_id, f"💤 *Dream Report*:\n{res}")
        
    elif cmd == "/status":
        from src.cli import get_uptime
        rem_list = reminders("list", format_for_user=True)
        status_text = (
            f"ℹ️ *Framework Status*:\n"
            f"• *Model*: `{config.model}`\n"
            f"• *Uptime*: {get_uptime()}\n"
            f"• *Workspace*: `{config.workspace_dir}`\n"
            f"• *Host Execution*: `{'ENABLED' if config.allow_host_execution else 'DISABLED'}`\n\n"
            f"⏰ *Pending Reminders*:\n{rem_list}"
        )
        send_telegram_message(chat_id, status_text)
        
    elif cmd == "/clear":
        if user_id in session_histories:
            session_histories[user_id].clear()
        from src.llm import unload_model
        unload_model()
        logger.info("Telegram", f"Session history cleared and model unloaded by user {user_id}.")
        send_telegram_message(chat_id, "🧹 Active session history cleared and model unloaded from RAM.")
        
    elif cmd == "/stop":
        send_telegram_message(chat_id, "🛑 Emergency stop accepted. Unloading model and shutting down...")
        logger.info("Telegram", f"Emergency stop command executed by user {user_id}.")
        from src.llm import unload_model
        unload_model()
        # Exit immediately
        os._exit(0)
    else:
        send_telegram_message(chat_id, f"❌ Unknown command '{cmd}'. Send `/help` for assistance.")

def process_telegram_message(message):
    """
    Validates sender whitelist and routes the request.
    """
    msg_from = message.get("from", {})
    user_id = msg_from.get("id")
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    
    if not user_id or not chat_id or not text:
        return
        
    # Check whitelist
    if user_id not in config.allowed_user_ids:
        logger.warning("Telegram", f"Ignored message from unauthorized user ID: {user_id}")
        return
        
    # User is authorized, update activity timestamps
    record_activity()
    logger.user_input(f"[Telegram User {user_id}] {text}")
    
    if text.startswith("/"):
        handle_telegram_command(text, chat_id, user_id)
        return
        
    # Regular prompt
    send_telegram_action(chat_id, "typing")
    
    # Fetch user history context
    if user_id not in session_histories:
        session_histories[user_id] = []
    user_history = session_histories[user_id]
    
    try:
        response, updated_history = run_agent_loop(
            house_agent,
            text,
            external_history=user_history
        )
        
        # Update user history reference
        session_histories[user_id] = updated_history
        
        # Send response back
        send_telegram_message(chat_id, response)
        record_activity()
    except Exception as e:
        logger.error("Telegram", f"Error in agent processing: {e}")
        send_telegram_message(chat_id, f"⚠️ Error processing request: {e}")

def poll_telegram_updates():
    """
    Main long-polling update loop for Telegram Bot API.
    """
    if not config.telegram_bot_token:
        logger.warning("Telegram", "No TELEGRAM_BOT_TOKEN provided. Telegram interface is disabled.")
        return
        
    if not config.allowed_user_ids:
        logger.warning("Telegram", "No ALLOWED_USER_ID configured. The bot will ignore all incoming messages!")
        
    logger.info("Telegram", "Starting Telegram long-polling loop...")
    offset = 0
    
    while True:
        url = f"https://api.telegram.org/bot{config.telegram_bot_token}/getUpdates"
        params = {
            "offset": offset,
            "timeout": 30
        }
        try:
            r = requests.get(url, params=params, timeout=35)
            if r.status_code == 200:
                data = r.json()
                if data.get("ok"):
                    updates = data.get("result", [])
                    for update in updates:
                        offset = update.get("update_id") + 1
                        message = update.get("message")
                        if message:
                            process_telegram_message(message)
                else:
                    logger.error("Telegram", f"API Error: {data}")
                    time.sleep(5)
            elif r.status_code == 401 or r.status_code == 404:
                logger.error("Telegram", f"Invalid bot token or API URL error. HTTP {r.status_code}.")
                time.sleep(30) # Prevent tight loop on auth errors
            else:
                logger.error("Telegram", f"HTTP Error {r.status_code} fetching updates.")
                time.sleep(5)
        except requests.exceptions.Timeout:
            # Expected during long polling
            pass
        except Exception as e:
            logger.error("Telegram", f"Polling loop exception: {e}")
            time.sleep(5)
