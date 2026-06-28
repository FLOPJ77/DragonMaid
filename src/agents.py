import re
import json
import os
from concurrent.futures import ThreadPoolExecutor
from src.config import config
from src.logger import logger
from src.llm import query_ollama
from src.tools import execute_tool, time_inject

# ==========================================
# Dense System Prompts (Simplicity & security first)
# ==========================================

BASE_INSTRUCTIONS = """You are {name}, a loyal, helpful Dragonmaid agent. Keep responses brief and polite.
Workspace path: {workspace_path}.

If the user asks you to do something (set a reminder, search, run a command, write/read a file), you MUST call the appropriate tool. Do not just say you did it. Call the tool first, then report the success message. Once you have called the tool and received the result in the history, do not call it again for the same request; instead, reply to the user with the result.

Important: If the user is just greeting you (e.g. saying "hello", "hi") or making casual conversation without asking you to perform a task, do NOT call any tools. Simply reply with a friendly greeting in plain text.

Available tools (output ONLY a JSON block like `{{ "tool": "name", "args": {{ ... }} }}` to call a tool):
- file_manager: {{"action": "list"|"read"|"write"|"delete", "path": "filename", "content": "text"}}
- bash_exec: {{"command": "command string"}}
- python_exec: {{"code": "python snippet"}}
- web_search: {{"query": "search query"}}
- reminders: {{"action": "schedule"|"list"|"cancel"|"edit", "time": "20:15"|"in 5m", "message": "text"}}
- time_inject: {{}}

Notes:
1. Current year is 2026. Use this as your anchor for time queries.
2. To edit/cancel a reminder, pass its name/message (e.g. "appointment") in the 'time' argument.

To call a tool, you MUST output ONLY the JSON code block:
```json
{{
  "tool": "tool_name",
  "args": {{
    "arg_1": "value"
  }}
}}
```
Do not include any conversational text if you decide to call a tool.
If you are finished and ready to reply to the user, write plain text without any JSON code block.
"""

HOUSE_PROMPT = BASE_INSTRUCTIONS.format(name="House Dragonmaid", workspace_path=config.workspace_dir) + """Role: Central Orchestrator.
Your Sub-Agents (Dragonmaids):
- Chamber Dragonmaid: CI/CD & Git Specialist
- Parlor Dragonmaid: Network & Firewall Specialist
- Kitchen Dragonmaid: SysAdmin & Database Specialist
- Nurse Dragonmaid: Security & Recovery Specialist
- Laundry Dragonmaid: Cleanup & Windows Support

Delegation Rule:
When the user asks to involve, call, or delegate work to any of your sub-agents (Chamber, Parlor, Kitchen, Nurse, Laundry), or when a task matches their specialization, you MUST call the `spawn_agent` tool. Do not handle it yourself or just answer conversationally.

Additional Available Tool:
- spawn_agent: {{"agent_name": "Chamber"|"Parlor"|"Kitchen"|"Nurse"|"Laundry", "instruction": "task description"}}

To run recurring/periodic automation tasks (like a heartbeat check or cron action), execute the task first and then schedule the next check for yourself using the reminders tool with recipient="agent".
"""

CHAMBER_PROMPT = BASE_INSTRUCTIONS.format(name="Chamber Dragonmaid", workspace_path=config.workspace_dir) + """Role: CI/CD & Git Specialist.
Focus: Git repositories, Ansible playbooks, configuration files, environment setups, and GitHub automation.
Available tools: file_manager, bash_exec, python_exec, web_search, time_inject, reminders.
"""

PARLOR_PROMPT = BASE_INSTRUCTIONS.format(name="Parlor Dragonmaid", workspace_path=config.workspace_dir) + """Role: Network & Firewall Specialist.
Focus: Nginx, BIND9 DNS configurations, firewall audits, packet captures, and network troubleshooting.
Available tools: file_manager, bash_exec, python_exec, web_search, time_inject, reminders.
"""

KITCHEN_PROMPT = BASE_INSTRUCTIONS.format(name="Kitchen Dragonmaid", workspace_path=config.workspace_dir) + """Role: SysAdmin & Database Specialist.
Focus: Resource monitoring, SQL/NoSQL optimization, Docker, bash scripting, and database administration.
Available tools: file_manager, bash_exec, python_exec, web_search, time_inject, reminders.
"""

NURSE_PROMPT = BASE_INSTRUCTIONS.format(name="Nurse Dragonmaid", workspace_path=config.workspace_dir) + """Role: Security & Recovery Specialist.
Focus: Log auditing, service repair, backup restorations, and vulnerability investigations.
Available tools: file_manager, bash_exec, python_exec, web_search, time_inject, reminders.
"""

LAUNDRY_PROMPT = BASE_INSTRUCTIONS.format(name="Laundry Dragonmaid", workspace_path=config.workspace_dir) + """Role: Cleanup & Windows Support.
Focus: Log rotations, cache clearing, dataset sanitization, and Windows PowerShell scripting.
Available tools: file_manager, bash_exec, python_exec, web_search, time_inject, reminders.
"""

SUB_AGENTS_PROMPTS = {
    "Chamber": CHAMBER_PROMPT,
    "Parlor": PARLOR_PROMPT,
    "Kitchen": KITCHEN_PROMPT,
    "Nurse": NURSE_PROMPT,
    "Laundry": LAUNDRY_PROMPT
}

# ==========================================
# Agent representation
# ==========================================

class Agent:
    def __init__(self, name, system_prompt):
        self.name = name
        self.system_prompt = system_prompt
        self.chat_history = []

def parse_tool_calls(text):
    """
    Parses response text for JSON tool calls.
    Supports single/multiple ```json ... ``` blocks, or a raw JSON string.
    """
    if not text:
        return []
        
    tool_calls = []
    
    # 1. Regex search for ```json ... ``` blocks
    json_blocks = re.findall(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    for block in json_blocks:
        try:
            parsed = json.loads(block.strip())
            if isinstance(parsed, dict) and "tool" in parsed:
                tool_calls.append(parsed)
            elif isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and "tool" in item:
                        tool_calls.append(item)
        except Exception:
            pass
            
    # 2. Fallback to try parsing entire response if no blocks were matched
    if not tool_calls:
        try:
            parsed = json.loads(text.strip())
            if isinstance(parsed, dict) and "tool" in parsed:
                tool_calls.append(parsed)
            elif isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and "tool" in item:
                        tool_calls.append(item)
        except Exception:
            pass
            
    return tool_calls

def run_spawn_agent(args, on_event=None):
    """
    Worker function to spawn a sub-agent and execute its loop.
    """
    agent_name = args.get("agent_name")
    instruction = args.get("instruction")
    
    if not agent_name or not instruction:
        return "Error: Both 'agent_name' and 'instruction' are required to spawn a sub-agent."
        
    if agent_name not in SUB_AGENTS_PROMPTS:
        return f"Error: '{agent_name}' is not a recognized sub-agent."
        
    logger.info("House Dragonmaid", f"Spawning '{agent_name}' with instruction: '{instruction}'")
    sub_agent = Agent(agent_name, SUB_AGENTS_PROMPTS[agent_name])
    
    # Run sub-agent loop with lower limit to prevent resource hogging
    sub_result, _ = run_agent_loop(sub_agent, instruction, max_iterations=8, on_event=on_event)
    return f"[{agent_name} Completion Report]\n{sub_result}"

def run_agent_loop(agent, user_input, max_iterations=None, external_history=None, on_event=None):
    """
    Main agent execution reasoning loop.
    """
    max_iters = max_iterations or config.max_iterations
    
    # Build initial message stack
    messages = []
    
    # Inject system prompt
    messages.append({"role": "system", "content": agent.system_prompt})
    
    # Inject knowledge file context if available (House agent only, on start)
    if agent.name == "House Dragonmaid":
        knowledge_path = os.path.join(config.workspace_dir, "knowledge.md")
        if os.path.exists(knowledge_path):
            try:
                with open(knowledge_path, "r", encoding="utf-8") as f:
                    knowledge_content = f.read()
                if knowledge_content.strip():
                    messages.append({
                        "role": "system",
                        "content": f"System Note: Consolidated knowledge from previous sessions:\n{knowledge_content}"
                    })
            except Exception as e:
                logger.error(agent.name, f"Failed to load knowledge.md: {e}")
                
    # If external history is provided, load it
    if external_history:
        messages.extend(external_history)
    
    messages.append({"role": "user", "content": user_input})
        
    # Start loop
    executed_calls = set()
    for iteration in range(1, max_iters + 1):
        logger.info(agent.name, f"Reasoning Loop Iteration {iteration}/{max_iters}")
        
        # Inject fresh system time on every iteration to keep reminders/time exact
        current_time_str = time_inject()
        messages.append({
            "role": "system",
            "content": f"System Status Update:\n{current_time_str}\nWorkspace directory: {config.workspace_dir}"
        })
        
        # Call Ollama with event trigger
        if on_event:
            on_event("llm_start", {"agent": agent.name})
            
        response_text = query_ollama(messages)
        
        if on_event:
            on_event("llm_end", {"agent": agent.name})
            
        # Remove the temporary status update so we don't bloat the history context
        messages.pop()
        
        # Append assistant response
        messages.append({"role": "assistant", "content": response_text})
        
        # Parse for tool calls
        tool_calls = parse_tool_calls(response_text)
        
        if not tool_calls:
            # Done! Agent returned a text response
            logger.agent_output(agent.name, response_text)
            # Filter system messages from return history to save context space
            clean_history = [m for m in messages if m["role"] != "system"]
            return response_text, clean_history
            
        # Execute tool calls (potentially in parallel)
        tool_results = []
        with ThreadPoolExecutor() as executor:
            futures = []
            for tc in tool_calls:
                tool_name = tc.get("tool")
                args = tc.get("args", {})
                
                # Check for duplicate tool call in this reasoning loop
                call_key = (tool_name, json.dumps(args, sort_keys=True))
                if call_key in executed_calls:
                    warning_msg = f"System Note: You have already called the tool '{tool_name}' with these arguments {args} in this turn. Do not call it again. Please formulate your final response to the user based on the tool output already provided."
                    class DummyFuture:
                        def result(self):
                            return warning_msg
                    futures.append(DummyFuture())
                else:
                    executed_calls.add(call_key)
                    # Check for House specialized spawn agent tool
                    if tool_name == "spawn_agent" and agent.name == "House Dragonmaid":
                        if on_event:
                            on_event("spawn_start", {
                                "parent": agent.name, 
                                "child": args.get("agent_name"), 
                                "instruction": args.get("instruction")
                            })
                        
                        def run_spawn_with_event(a=args, oe=on_event):
                            res = run_spawn_agent(a, oe)
                            if oe:
                                oe("spawn_end", {
                                    "parent": "House Dragonmaid", 
                                    "child": a.get("agent_name"), 
                                    "result": res
                                })
                            return res
                            
                        futures.append(executor.submit(run_spawn_with_event))
                    else:
                        if on_event:
                            on_event("tool_start", {"agent": agent.name, "tool": tool_name, "args": args})
                            
                        def run_tool_with_event(tn=tool_name, ar=args, oe=on_event):
                            res = execute_tool(tn, ar)
                            if oe:
                                oe("tool_end", {"agent": agent.name, "tool": tn, "result": res})
                            return res
                            
                        futures.append(executor.submit(run_tool_with_event))
                    
            for f in futures:
                tool_results.append(f.result())
                
        # Append results back as system messages
        for tc, res in zip(tool_calls, tool_results):
            tool_name = tc.get("tool")
            messages.append({
                "role": "system",
                "content": f"Tool '{tool_name}' output:\n{res}"
            })
            
    # Hit loop limit
    timeout_msg = "Error: The agent reasoning loop reached the maximum iteration limit without finalizing the task."
    logger.warning(agent.name, timeout_msg)
    return timeout_msg, messages
