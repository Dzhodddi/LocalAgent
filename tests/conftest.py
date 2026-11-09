import pytest

from localagents.config import Settings
from localagents.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path)


@pytest.fixture
def settings():
    return Settings(command_timeout=5.0, max_steps=10)
