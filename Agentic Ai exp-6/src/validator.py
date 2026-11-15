"""Validator — validates tool results and classifies errors."""

RETRYABLE = {"timeout", "execution"}


def classify_error(msg: str) -> str:
    """
    Classify an error message into a category.
    Only 'timeout' and 'execution' errors are retryable.
    """
    m = msg.lower()
    if "[security]" in m or "access denied" in m:
        return "security"
    if "[timeout]" in m:
        return "timeout"
    if "[input]" in m or "not found" in m:
        return "input"
    return "execution" if "[execution]" in m else "tool"


def is_retryable(error_type: str) -> bool:
    """Check if an error type is retryable."""
    return error_type in RETRYABLE


def validate_result(result: dict) -> tuple:
    """
    Validate a tool result.
    Returns (is_valid, error_message).
    """
    if result is None:
        return False, "Result is None"

    if isinstance(result, dict):
        if "error" in result:
            return False, result["error"]
        return True, ""

    if isinstance(result, str):
        if not result.strip():
            return False, "Empty result"
        # Check for error indicators in string results
        lower = result.lower()
        if "[security]" in lower or "access denied" in lower:
            return False, result
        if "[timeout]" in lower:
            return False, result
        if "[input]" in lower:
            return False, result
        if "[execution]" in lower:
            return False, result
        return True, ""

    # For list and other types, just check non-empty
    return bool(result), "Empty result" if not result else ""

