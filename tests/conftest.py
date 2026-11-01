import os
import sys

# run against the source tree without installing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# a fixed fingerprint key: tests must never create ~/.config/proxy2model
os.environ.setdefault("PROXY2MODEL_FP_KEY", "test-key")

# builds run OSINT by default; tests must never touch the network
os.environ["PROXY2MODEL_OFFLINE"] = "1"
