from __future__ import annotations
import json, os
from pathlib import Path
from typing import Dict

# Editable runtime settings, layered so the UI, environment, and code defaults all
# cooperate. Precedence on read: saved settings.json value > environment variable >
# built-in default. This lets the /config page override env without forcing a restart,
# while a fresh checkout still works purely from .env / shell environment.
DEFAULTS: Dict[str, str] = {
    'ollama_url':   'http://localhost:11434/api/generate',
    'ollama_model': '',
    'wikijs_url':   '',
    'wikijs_token': '',
}
ENV_MAP: Dict[str, str] = {
    'ollama_url':   'OLLAMA_URL',
    'ollama_model': 'OLLAMA_MODEL',
    'wikijs_url':   'WIKIJS_URL',
    'wikijs_token': 'WIKIJS_TOKEN',
}
# Fields never echoed back to the browser in clear text.
SECRET_KEYS = {'wikijs_token'}


class Settings:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: Dict[str, str] = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                self._data = {k: v for k, v in json.loads(self.path.read_text('utf-8')).items() if k in DEFAULTS}
            except Exception:
                self._data = {}

    def get(self, key: str) -> str:
        val = self._data.get(key)
        if val:
            return str(val)
        env = os.getenv(ENV_MAP.get(key, ''), '')
        return env if env else DEFAULTS.get(key, '')

    def source_of(self, key: str) -> str:
        """Where the effective value is coming from — shown on the config page so the
        user understands why a field is populated."""
        if self._data.get(key):
            return 'settings.json'
        if os.getenv(ENV_MAP.get(key, ''), ''):
            return 'environment'
        return 'default'

    def all(self) -> Dict[str, str]:
        return {k: self.get(k) for k in DEFAULTS}

    def view(self) -> Dict[str, Dict[str, str]]:
        """Render-friendly snapshot for the config page: value (secrets masked),
        source, and whether a secret is set."""
        out: Dict[str, Dict[str, str]] = {}
        for k in DEFAULTS:
            v = self.get(k)
            if k in SECRET_KEYS:
                out[k] = {'value': '', 'set': bool(v), 'source': self.source_of(k)}
            else:
                out[k] = {'value': v, 'set': bool(v), 'source': self.source_of(k)}
        return out

    def save(self, updates: Dict[str, str]) -> None:
        """Persist non-empty known keys. An empty submission leaves a field unchanged
        (so a blank token box doesn't wipe a stored token); to clear a value, edit or
        delete settings.json directly."""
        for k in DEFAULTS:
            if k in updates and str(updates[k]).strip():
                self._data[k] = str(updates[k]).strip()
        self.path.write_text(json.dumps(self._data, indent=2), encoding='utf-8')
