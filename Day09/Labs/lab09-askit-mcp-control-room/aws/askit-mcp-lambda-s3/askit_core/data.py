"""Load the Orbit Corp helpdesk data - from S3 (Day 9 stretch).

Set two environment variables on the function:
  ASKIT_BUCKET   the bucket that holds the data (e.g. devproacademy-askit-data)
  ASKIT_PREFIX   folder inside it (default: askit_data/)
Files are copied to /tmp and refreshed from S3 at most every 5 seconds, so editing a KB file in S3
shows up in the next tool call - no redeploy.
"""
import csv
import os
import time

import boto3

from askit_core.config import DATA_DIR

_s3 = boto3.client("s3")
_etags, _last = {}, 0.0


def _sync():
    global _last
    if time.time() - _last < 5:
        return
    bucket = os.environ.get("ASKIT_BUCKET")
    if not bucket:
        raise RuntimeError("ASKIT_BUCKET is not set on this function")
    prefix = os.environ.get("ASKIT_PREFIX", "askit_data/")
    for page in _s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            rel = o["Key"][len(prefix):]
            if not rel or rel.endswith("/") or _etags.get(rel) == o["ETag"]:
                continue
            dest = DATA_DIR / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            _s3.download_file(bucket, o["Key"], str(dest))
            _etags[rel] = o["ETag"]
    _last = time.time()


def load_tickets():
    _sync()
    with open(DATA_DIR / "tickets.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_users():
    _sync()
    with open(DATA_DIR / "users.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_kb():
    """Return {doc_id: text} for every KB article."""
    _sync()
    return {p.stem.split("_")[0]: p.read_text(encoding="utf-8") for p in sorted((DATA_DIR / "kb").glob("*.md"))}
