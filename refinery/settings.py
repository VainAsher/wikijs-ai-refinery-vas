from __future__ import annotations
import json, os
from pathlib import Path
from typing import Dict, Optional

# Symmetric encryption for secret fields at rest (so wikijs_token isn't stored in
# plaintext in settings.json). Degrades gracefully: if the `cryptography` library is
# unavailable we fall back to plaintext rather than break the app. The key comes from
# REFINERY_SECRET_KEY if set, else an auto-generated, git-ignored key file next to
# settings.json — so encryption works out of the box without manual key management.
try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAVE_CRYPTO = True
except Exception:  # pragma: no cover - library missing
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore
    _HAVE_CRYPTO = False

ENC_PREFIX = 'enc::'  # marks an encrypted value so we can tell it from legacy plaintext


def _load_cipher(key_path: Path):
    """Return a Fernet cipher, or None if encryption is unavailable. The key is taken
    from REFINERY_SECRET_KEY (must be a valid Fernet key) or persisted to key_path."""
    if not _HAVE_CRYPTO:
        return None
    env_key = os.getenv('REFINERY_SECRET_KEY', '').strip()
    try:
        if env_key:
            return Fernet(env_key.encode())
        if key_path.exists():
            return Fernet(key_path.read_text('utf-8').strip().encode())
        key = Fernet.generate_key()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(key.decode(), encoding='utf-8')
        return Fernet(key)
    except Exception:  # malformed key etc. -> no encryption rather than a hard failure
        return None

# Editable runtime settings, layered so the UI, environment, and code defaults all
# cooperate. Precedence on read: saved settings.json value > environment variable >
# built-in default. This lets the /config page override env without forcing a restart,
# while a fresh checkout still works purely from .env / shell environment.
DEFAULTS: Dict[str, str] = {
    'ollama_url':   'http://localhost:11434/api/generate',
    'ollama_model': '',
    'wikijs_url':   '',
    'wikijs_token': '',
    'anthropic_api_key': '',
}
ENV_MAP: Dict[str, str] = {
    'ollama_url':   'OLLAMA_URL',
    'ollama_model': 'OLLAMA_MODEL',
    'wikijs_url':   'WIKIJS_URL',
    'wikijs_token': 'WIKIJS_TOKEN',
    'anthropic_api_key': 'ANTHROPIC_API_KEY',
}
# Fields never echoed back to the browser in clear text (and encrypted at rest).
SECRET_KEYS = {'wikijs_token', 'anthropic_api_key'}


class Settings:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: Dict[str, str] = {}
        self._cipher = _load_cipher(self.path.parent / '.secret_key')
        self.load()

    def _decrypt(self, key: str, raw: str) -> str:
        """Decrypt a stored secret. Values written before encryption (no ENC_PREFIX)
        are returned as-is, so existing settings.json files keep working."""
        if key in SECRET_KEYS and isinstance(raw, str) and raw.startswith(ENC_PREFIX):
            if not self._cipher:
                return ''  # can't decrypt without the key; treat as unset rather than leak ciphertext
            try:
                return self._cipher.decrypt(raw[len(ENC_PREFIX):].encode()).decode()
            except InvalidToken:
                return ''
        return raw

    def load(self) -> None:
        if self.path.exists():
            try:
                self._data = {k: v for k, v in json.loads(self.path.read_text('utf-8')).items() if k in DEFAULTS}
            except Exception:
                self._data = {}

    def get(self, key: str) -> str:
        val = self._data.get(key)
        if val:
            return str(self._decrypt(key, val))
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
        delete settings.json directly. Secret fields are encrypted at rest when a
        cipher is available."""
        for k in DEFAULTS:
            if k in updates and str(updates[k]).strip():
                val = str(updates[k]).strip()
                if k in SECRET_KEYS and self._cipher:
                    val = ENC_PREFIX + self._cipher.encrypt(val.encode()).decode()
                self._data[k] = val
        self.path.write_text(json.dumps(self._data, indent=2), encoding='utf-8')
