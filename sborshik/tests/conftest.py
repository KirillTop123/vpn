import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SBORSHIK_HOME"] = tempfile.mkdtemp(prefix="sborshik-test-")

import pytest  # noqa: E402


@pytest.fixture()
def fresh_db(tmp_path):
    import db
    db.connect(tmp_path / "test.db")
    yield db
