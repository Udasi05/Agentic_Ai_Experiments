import pytest
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
