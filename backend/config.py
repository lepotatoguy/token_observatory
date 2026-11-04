"""Runtime configuration; DATA_DIR contains daily history."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import sys


def default_data_dir() -> Path:
    if sys.platform == "darwin":
        root = Path.home() / "Library/Application Support/Token Observatory"
    elif sys.platform == "win32":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming") / "Token Observatory"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "token-observatory"
    return root / "history"


@dataclass
class Config:
    PORT: int = field(default_factory=lambda: int(os.environ.get("TOKEN_OBSERVATORY_PORT", "8765")))
    DATA_DIR: Path = field(default_factory=lambda: Path(os.environ["TOKEN_OBSERVATORY_DATA_DIR"]).expanduser()
                           if "TOKEN_OBSERVATORY_DATA_DIR" in os.environ else default_data_dir())
    CODEX_HOME: Path = field(default_factory=lambda: Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser())
    CLAUDE_HOME: Path = field(default_factory=lambda: Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser())
    LIVE_CHECKS: bool = field(default_factory=lambda: os.environ.get("TOKEN_OBSERVATORY_LIVE_CHECKS") != "0")
    UPDATE_CHECKS: bool = field(default_factory=lambda: os.environ.get("TOKEN_OBSERVATORY_UPDATE_CHECKS") != "0")
    FRONTEND_DIST: Path = field(default_factory=lambda: (
        Path(__file__).resolve().parents[1] / "frontend/dist"
        if (Path(__file__).resolve().parents[1] / "frontend/dist").is_dir()
        else Path(__file__).resolve().parent / "static"
    ))
    CLAUDE_PLAN_FILE: Path | None = None
    LMSTUDIO_FOLDER: Path | None = None

    def __post_init__(self):
        if not 1 <= self.PORT <= 65535:
            raise ValueError("PORT must be between 1 and 65535")
