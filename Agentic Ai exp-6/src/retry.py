"""Retry logic — retries only timeout and execution errors with exponential backoff."""

import asyncio
import time
from src.validator import classify_error, is_retryable
from src.config import MAX_RETRIES


async def retry_tool_call(call_fn, task_id: str, tool_name: str, args: dict,
                          max_retries: int = None, tracer=None):
    """
    Execute a tool call with retry logic.
    Only timeout and execution errors are retried (up to max_retries times).
    Other error types (security, input, tool) fail immediately.

    Args:
        call_fn: Async function that calls the tool, signature: (tool_name, args) -> result
        task_id: The task identifier
        tool_name: Name of the tool
        args: Tool arguments
        max_retries: Max retry attempts (defaults to config.MAX_RETRIES)
        tracer: Optional tracer for logging attempts

    Returns:
        (result, attempts, error_type, error_msg) tuple
    """
    if max_retries is None:
        max_retries = MAX_RETRIES

    attempts = 0
    last_error = ""
    last_error_type = ""

    while attempts < max_retries:
        attempts += 1
        start = time.time()

        try:
            result = await call_fn(tool_name, args)
            duration_ms = (time.time() - start) * 1000

            # Log successful attempt
            if tracer:
                tracer.log(
                    task_id=task_id,
                    tool=tool_name,
                    args=args,
                    status="success",
                    duration_ms=duration_ms,
                    attempt=attempts,
                )

            return result, attempts, None, None

        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            error_msg = str(e)
            error_type = classify_error(error_msg)

            # Log failed attempt
            if tracer:
                tracer.log(
                    task_id=task_id,
                    tool=tool_name,
                    args=args,
                    status="failed",
                    duration_ms=duration_ms,
                    error=error_msg,
                    error_type=error_type,
                    attempt=attempts,
                )

            last_error = error_msg
            last_error_type = error_type

            # Only retry timeout and execution errors
            if not is_retryable(error_type):
                return None, attempts, error_type, error_msg

            # Don't sleep after the last attempt
            if attempts < max_retries:
                backoff = min(2 ** (attempts - 1), 8)  # 1, 2, 4, max 8 seconds
                await asyncio.sleep(backoff)

    return None, attempts, last_error_type, last_error

