"""Runs before the tests. db.py and ai.py create AWS clients when imported,
so we give them a fake region and fake credentials. That keeps the tests
from ever using (or needing) your real AWS login."""
import os

os.environ.pop("AWS_PROFILE", None)  # ignore your real `aws login` profile
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-2")
os.environ.setdefault("TABLE_NAME", "test-table")