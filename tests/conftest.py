import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from predicate_chain.config import load_config  # noqa: E402
from predicate_chain.db import connect, init_schema  # noqa: E402


@pytest.fixture
def cfg(tmp_path):
    c = load_config(ROOT / "config.ini")
    c.project_dir = tmp_path
    for key, val in {"DATA_DIR": "data", "OUTPUT_DIR": "outputs", "LOG_DIR": "logs", "CACHE_DIR": "cache/pdfs",
                     "DETAIL_CACHE_DIR": "cache/detail_pages", "DB_FILE": "data/test.db",
                     "OLD_PROJECT_DIR": "old"}.items():
        c.raw.set("paths", key, val)
    c.raw.set("ocr", "USE_OCR", "no")
    return c


@pytest.fixture
def con(cfg):
    db = connect(cfg.db_path)
    init_schema(db)
    yield db
    db.close()


def identity_from(table: dict):
    """Fake FDA identity lookup for tests: {number: (applicant, device_name)}."""
    def fn(number):
        if number in table:
            a, d = table[number]
            return {"found": True, "source": "FDA master", "applicant": a, "device_name": d}
        return {"found": False, "source": "not found", "applicant": None, "device_name": None}
    return fn
