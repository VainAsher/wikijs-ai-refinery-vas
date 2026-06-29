import os
from refinery.settings import Settings


def test_default_precedence(tmp_path):
    s = Settings(tmp_path / 'settings.json')
    assert s.get('ollama_url') == 'http://localhost:11434/api/generate'
    assert s.get('ollama_model') == ''


def test_env_overrides_default(tmp_path, monkeypatch):
    monkeypatch.setenv('OLLAMA_MODEL', 'mistral:latest')
    s = Settings(tmp_path / 'settings.json')
    assert s.get('ollama_model') == 'mistral:latest'
    assert s.source_of('ollama_model') == 'environment'


def test_saved_overrides_env(tmp_path, monkeypatch):
    monkeypatch.setenv('OLLAMA_MODEL', 'env-model')
    s = Settings(tmp_path / 'settings.json')
    s.save({'ollama_model': 'file-model'})
    s2 = Settings(tmp_path / 'settings.json')   # reload from disk
    assert s2.get('ollama_model') == 'file-model'
    assert s2.source_of('ollama_model') == 'settings.json'


def test_empty_save_keeps_existing(tmp_path):
    s = Settings(tmp_path / 'settings.json')
    s.save({'wikijs_token': 'secret123'})
    s.save({'wikijs_token': ''})   # blank submission must not wipe it
    assert s.get('wikijs_token') == 'secret123'


def test_view_masks_secret(tmp_path):
    s = Settings(tmp_path / 'settings.json')
    s.save({'wikijs_token': 'secret123'})
    view = s.view()
    assert view['wikijs_token']['value'] == ''      # never echoed
    assert view['wikijs_token']['set'] is True


def test_unknown_keys_ignored(tmp_path):
    s = Settings(tmp_path / 'settings.json')
    s.save({'evil': 'x', 'ollama_model': 'm'})
    assert 'evil' not in s.all()


def test_secret_encrypted_at_rest_but_readable(tmp_path):
    s = Settings(tmp_path / 'settings.json')
    s.save({'wikijs_token': 'super-secret-token'})
    # On disk the token must NOT appear in plaintext (it's Fernet-encrypted)...
    raw = (tmp_path / 'settings.json').read_text('utf-8')
    assert 'super-secret-token' not in raw
    assert 'enc::' in raw
    # ...but a fresh load (same key file) still decrypts it transparently.
    assert Settings(tmp_path / 'settings.json').get('wikijs_token') == 'super-secret-token'


def test_legacy_plaintext_secret_still_readable(tmp_path):
    # A settings.json written before encryption (plain value, no enc:: prefix) keeps working.
    (tmp_path / 'settings.json').write_text('{"wikijs_token": "legacy-plain"}', encoding='utf-8')
    assert Settings(tmp_path / 'settings.json').get('wikijs_token') == 'legacy-plain'
