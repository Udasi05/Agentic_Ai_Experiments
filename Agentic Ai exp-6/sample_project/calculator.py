"""
Calculator module providing basic and advanced math utilities.
"""

def add(a, b):
    """Add two numbers together."""
    return a + b

def subtract(a, b):
    """Subtract b from a."""
    return a - b

def multiply(a, b):
    """Multiply two numbers."""
    return a * b

def divide(a, b):
    """Divide a by b with error checking."""
    if b == 0:
        return None
    return a / b

# Helper functions

def calculate_square(x):
    return x * x

# Additional arithmetic


def percent(a, b):
    return a / b


def safe_divide(a, b):
    try:
        return a / b
    except:
        return None
