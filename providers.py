"""Which AI tools the user tracks: saved choices, detection of what is installed, and first-run state.

Saved in providers.json in the data folder:
{"setup_done": true, "enabled": {"claude": true, "codex": false, "ollama": true, ...},
 "ports": {"ollama": {"listen": 11435, "target": 11434}, ...}}
"""
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading

from local_proxy import TOOLS, reachable

CLOUD = ('claude', 'codex')
ALL = CLOUD + tuple(TOOLS)
NAMES = dict(claude='Claude Code', codex='Codex', **{k: v['name'] for k, v in TOOLS.items()})
LOCAL_FOLDERS = dict(ollama=['~/.ollama'], lmstudio=['~/.lmstudio', '~/.cache/lm-studio'], llamacpp=[])
COMMANDS = dict(ollama='ollama', lmstudio='lms', llamacpp='llama-server')


def detect(claude_home, codex_home, probe=reachable):
    """What looks installed on this computer, with the reason, so the setup prompt can preselect it."""
    found = dict(claude=(Path(claude_home) / 'projects').is_dir() and 'Claude Code logs found',
                 codex=(Path(codex_home) / 'sessions').is_dir() and 'Codex logs found')
    for tool, info in TOOLS.items():
        if probe(info['target']):
            found[tool] = f'server answering on port {info["target"]}'
        elif shutil.which(COMMANDS[tool]):
            found[tool] = f'`{COMMANDS[tool]}` command installed'
        elif any(Path(folder).expanduser().is_dir() for folder in LOCAL_FOLDERS[tool]):
            found[tool] = 'app folder found'
        else:
            found[tool] = False
    return {k: v or None for k, v in found.items()}


def valid_port(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65535


class Settings:
    def __init__(self, path):
        self.path = Path(path) if path else None
        self.lock = threading.Lock()
        self.data = self.load()

    def load(self):
        try:
            data = json.loads(self.path.read_text()) if self.path else {}
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        enabled = data.get('enabled') if isinstance(data.get('enabled'), dict) else {}
        ports = data.get('ports') if isinstance(data.get('ports'), dict) else {}
        return dict(setup_done=data.get('setup_done') is True,
                    enabled={p: enabled[p] for p in ALL if isinstance(enabled.get(p), bool)},
                    ports={t: dict(listen=ports[t].get('listen', TOOLS[t]['listen']), target=ports[t].get('target', TOOLS[t]['target']))
                           for t in TOOLS if isinstance(ports.get(t), dict)})

    def enabled(self, detected=None):
        """Providers to track. Until the user chooses, Claude Code and Codex stay on, as before this setting existed."""
        with self.lock:
            saved = self.data['enabled']
        return {p for p in ALL if saved.get(p, p in CLOUD)}

    def ports(self, tool):
        with self.lock:
            saved = self.data['ports'].get(tool, {})
        return saved.get('listen', TOOLS[tool]['listen']), saved.get('target', TOOLS[tool]['target'])

    def update(self, payload):
        """Apply a change from the dashboard; raises ValueError for anything malformed."""
        with self.lock:
            data = json.loads(json.dumps(self.data))
        enabled = payload.get('enabled', {})
        if not isinstance(enabled, dict) or any(k not in ALL or not isinstance(v, bool) for k, v in enabled.items()):
            raise ValueError('enabled must map provider names to true or false')
        data['enabled'].update(enabled)
        ports = payload.get('ports', {})
        if not isinstance(ports, dict) or any(k not in TOOLS or not isinstance(v, dict) for k, v in ports.items()):
            raise ValueError('ports must map local tools to {listen, target}')
        for tool, change in ports.items():
            merged = dict(zip(('listen', 'target'), self.ports(tool)), **change)
            if set(merged) != {'listen', 'target'} or not all(valid_port(merged[k]) for k in merged) or merged['listen'] == merged['target']:
                raise ValueError(f'{tool}: listen and target must be two different ports from 1 to 65535')
            data['ports'][tool] = merged
        if 'setup_done' in payload:
            if not isinstance(payload['setup_done'], bool):
                raise ValueError('setup_done must be true or false')
            data['setup_done'] = payload['setup_done']
        with self.lock:
            self.save(data)
            self.data = data

    def save(self, data):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.providers-', suffix='.tmp', dir=self.path.parent)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, indent=2)
        os.replace(temporary, self.path)

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.data))
