import os

import pytest

# No paid or external calls in tests: rule-based assistant, haversine ETAs. Set before app.config loads .env.
os.environ["LLM_ENABLED"] = "0"
os.environ["NESHAN_API_KEY"] = ""

from app.config import settings  # noqa: E402

needs_db = pytest.mark.skipif(not settings.db_path.exists(), reason="data/torob.db not built (etl/build_db.py)")
