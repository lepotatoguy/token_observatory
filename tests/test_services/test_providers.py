from backend.services import providers


def test_first_run_selects_only_detected_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(providers.shutil, 'which', lambda name: None)
    detected = providers.detect(tmp_path / 'claude', tmp_path / 'codex', probe=lambda port: False,
                                data_dir=tmp_path)
    assert not any(detected.values())
    settings = providers.Settings(tmp_path / 'providers.json')
    assert settings.enabled(detected) == set()
    assert settings.enabled({'codex': 'synthetic installation'}) == {'codex'}
