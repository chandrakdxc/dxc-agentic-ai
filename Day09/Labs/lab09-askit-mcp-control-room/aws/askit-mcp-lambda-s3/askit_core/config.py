"""Lambda + S3 version of askit_core/config.py: data is read from S3 (see data.py), cached in /tmp."""
from pathlib import Path

DATA_DIR = Path("/tmp/askit_data")
REGION = "us-east-1"
SMALL_MODEL = LARGE_MODEL = ""
