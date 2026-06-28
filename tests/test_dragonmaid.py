import unittest
import os
import sys
import shutil
import warnings
warnings.filterwarnings("ignore")
from datetime import datetime, timedelta

# Ensure project root is in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config import config
from src.agents import parse_tool_calls
from src.tools import parse_reminder_time, resolve_safe_path, file_manager

class TestDragonMaid(unittest.TestCase):
    
    def setUp(self):
        # Temporarily redirect workspace to a test folder under project root
        self.original_workspace = config.workspace_dir
        self.test_workspace = os.path.join(project_root, "test_workspace")
        config.workspace_dir = self.test_workspace
        if os.path.exists(self.test_workspace):
            shutil.rmtree(self.test_workspace)
        os.makedirs(self.test_workspace, exist_ok=True)

    def tearDown(self):
        # Restore original workspace and clean up
        config.workspace_dir = self.original_workspace
        if os.path.exists(self.test_workspace):
            shutil.rmtree(self.test_workspace)

    # 1. Test Config Loading
    def test_config_loading(self):
        self.assertIsNotNone(config.model)
        self.assertIsNotNone(config.workspace_dir)
        self.assertFalse(config.allow_host_execution) # Default should be false for safety
        self.assertTrue(config.bypass_host_gatekeeper)

    # 2. Test Tool Parsing Logic
    def test_tool_parsing(self):
        # Single code block
        text_single = """
        Let me run this tool.
        ```json
        {
          "tool": "file_manager",
          "args": {
            "action": "write",
            "path": "test.txt",
            "content": "hello"
          }
        }
        ```
        That is all.
        """
        calls = parse_tool_calls(text_single)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["tool"], "file_manager")
        self.assertEqual(calls[0]["args"]["path"], "test.txt")

        # Multiple code blocks
        text_multi = """
        ```json
        {"tool": "time_inject", "args": {}}
        ```
        and
        ```json
        {"tool": "web_search", "args": {"query": "test"}}
        ```
        """
        calls_multi = parse_tool_calls(text_multi)
        self.assertEqual(len(calls_multi), 2)
        self.assertEqual(calls_multi[0]["tool"], "time_inject")
        self.assertEqual(calls_multi[1]["tool"], "web_search")

        # Raw JSON text
        text_raw = '{"tool": "bash_exec", "args": {"command": "ls"}}'
        calls_raw = parse_tool_calls(text_raw)
        self.assertEqual(len(calls_raw), 1)
        self.assertEqual(calls_raw[0]["tool"], "bash_exec")

    # 3. Test Reminder Time Parsing
    def test_reminder_time_parsing(self):
        now = datetime.now()
        
        # Test relative minute
        t_5m = parse_reminder_time("in 5m")
        self.assertIsNotNone(t_5m)
        self.assertAlmostEqual((t_5m - now).total_seconds(), 300, delta=5)
        
        # Test relative hour
        t_2h = parse_reminder_time("in 2 hours")
        self.assertIsNotNone(t_2h)
        self.assertAlmostEqual((t_2h - now).total_seconds(), 7200, delta=5)

        # Test relative second shorthand
        t_10s = parse_reminder_time("10s")
        self.assertIsNotNone(t_10s)
        self.assertAlmostEqual((t_10s - now).total_seconds(), 10, delta=2)
        
        # Test relative day
        t_1d = parse_reminder_time("in 1 day")
        self.assertIsNotNone(t_1d)
        self.assertAlmostEqual((t_1d - now).total_seconds(), 86400, delta=5)
        
        # Test compound relative formats
        t_compound = parse_reminder_time("in 16h30m")
        self.assertIsNotNone(t_compound)
        self.assertAlmostEqual((t_compound - now).total_seconds(), 59400, delta=5)
        
        # Test absolute time HH:MM
        t_abs = parse_reminder_time("23:59")
        self.assertIsNotNone(t_abs)
        self.assertEqual(t_abs.hour, 23)
        self.assertEqual(t_abs.minute, 59)

    # 4. Test File Manager Directory Jail
    def test_file_manager_sandbox(self):
        # Safe operations
        res_write = file_manager("write", "subfolder/hello.txt", "content here")
        self.assertTrue("written successfully" in res_write)
        
        res_read = file_manager("read", "subfolder/hello.txt")
        self.assertEqual(res_read, "content here")
        
        res_list = file_manager("list", "subfolder")
        self.assertTrue("hello.txt" in res_list)
        
        # Unsafe operations (directory traversal jail breach)
        with self.assertRaises(PermissionError):
            resolve_safe_path("../secret.txt")
            
        with self.assertRaises(PermissionError):
            resolve_safe_path("/etc/passwd")

        # Running file manager on outside file should return Permission Error msg
        res_unsafe_read = file_manager("read", "../../secret.txt")
        self.assertTrue("Access Denied" in res_unsafe_read)

        res_unsafe_write = file_manager("write", "/tmp/hack.txt", "hack")
        self.assertTrue("Access Denied" in res_unsafe_write)

if __name__ == "__main__":
    unittest.main()
