import os, tempfile
from pathlib import Path

# Point the app at an isolated data dir BEFORE refinery.app is imported anywhere,
# so the test suite never touches a real ./data store. conftest is imported by
# pytest before collecting test modules, making this the right place.
_TMP = tempfile.mkdtemp(prefix='refinery-tests-')
os.environ['REFINERY_DATA'] = _TMP
# Make sure no stray env config leaks model/token state into the settings tests.
for _k in ('OLLAMA_MODEL', 'OLLAMA_URL', 'WIKIJS_URL', 'WIKIJS_TOKEN'):
    os.environ.pop(_k, None)

import pytest
from refinery.core import load_taxonomy


@pytest.fixture(scope='session')
def taxonomy():
    root = Path(__file__).resolve().parent.parent
    return load_taxonomy(str(root / 'taxonomy.yml'))


@pytest.fixture
def store(tmp_path):
    from refinery.db import Store
    return Store(str(tmp_path / 'test.sqlite3'))


@pytest.fixture(scope='session')
def client():
    from fastapi.testclient import TestClient
    import refinery.app as app_mod
    return TestClient(app_mod.app)
