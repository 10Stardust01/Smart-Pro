import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as proto


@pytest.fixture(autouse=True)
def reset_demo():
    proto.init_demo(reset=True)


@pytest.fixture
def client():
    return TestClient(proto.app)
