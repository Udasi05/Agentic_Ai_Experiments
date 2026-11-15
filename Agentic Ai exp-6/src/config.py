"""Configuration constants for the PR Review Assistant."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PROJECT = PROJECT_ROOT / "sample_project"
LOG_DIR = PROJECT_ROOT / "logs"
TRACE_FILE = LOG_DIR / "mcp_traces.jsonl"

# Gemini API config
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"

# MCP Server configs
MAX_RETRIES = 3
TASK_TIMEOUT = 30  # seconds
