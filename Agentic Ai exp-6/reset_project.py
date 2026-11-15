"""
Script to reset sample_project back to the original Experiment 6 defective state:
- Restores 2 hardcoded credentials in config.py
- Restores bare except and missing docstrings in calculator.py
- Restores failing test in test_calculator.py
"""

from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_project"

CALCULATOR_ORIG = '''"""
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
'''

CONFIG_ORIG = '''# Configuration settings for the project
DEBUG = True
API_KEY = "API_KEY_9876543210"
DB_PASSWORD = "DB_PASSWORD_SUPER_SECRET"
DATABASE_URL = "postgresql://user:password@localhost/db"
'''

TEST_CALCULATOR_ORIG = '''import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from calculator import add, subtract, multiply, divide, percent, calculate_square

def test_add():
    assert add(2, 3) == 5

def test_subtract():
    assert subtract(5, 3) == 2

def test_multiply():
    assert multiply(3, 4) == 12

def test_divide():
    assert divide(10, 2) == 5.0

def test_divide_by_zero():
    assert divide(10, 0) is None

def test_percent():
    # Expects 5 as a percentage of 20 to be 25% (or 5 / 2 = 25% expectation)
    assert percent(5, 2) == 25
'''


def reset_project():
    print("Resetting sample_project back to Experiment 6 defect state...")
    (SAMPLE_DIR / "calculator.py").write_text(CALCULATOR_ORIG, encoding="utf-8")
    (SAMPLE_DIR / "config.py").write_text(CONFIG_ORIG, encoding="utf-8")
    (SAMPLE_DIR / "tests" / "test_calculator.py").write_text(TEST_CALCULATOR_ORIG, encoding="utf-8")
    print("✓ Restored calculator.py (bare except at line 38, missing docstrings at lines 25, 31, 35)")
    print("✓ Restored config.py (hardcoded API key at line 3, DB password at line 4)")
    print("✓ Restored test_calculator.py (failing test_percent with assert 2.5 == 25)")
    print("\nRun 'python demo.py' or check Streamlit to see the 'NEEDS WORK' verdict!")


if __name__ == "__main__":
    reset_project()

