"""Entry point to run the PR Review Assistant Streamlit app."""

import subprocess
import sys

if __name__ == "__main__":
    subprocess.run([sys.executable, "-m", "streamlit", "run", "app/streamlit_app.py"])
