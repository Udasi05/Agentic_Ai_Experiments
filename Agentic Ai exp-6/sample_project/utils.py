def format_output(data):
    """Format data for display"""
    if isinstance(data, dict):
        return "\n".join(f"{k}: {v}" for k, v in data.items())
    return str(data)

def validate_input(value, expected_type):
    """Validate input type"""
    if not isinstance(value, expected_type):
        raise TypeError(f"Expected {expected_type.__name__}, got {type(value).__name__}")
    return value
