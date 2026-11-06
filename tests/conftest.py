import os

os.environ["RETAILCO_OFFLINE"] = "1"   # tests never call a model

import pytest

from agent import db
from agent.pipeline import SupportAgent
from agent.telemetry import Tracer


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    return c


@pytest.fixture
def agent(conn, tmp_path):
    return SupportAgent(conn, tracer=Tracer(tmp_path / "traces.jsonl"), retry_delay=0)
