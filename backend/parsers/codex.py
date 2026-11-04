from ._log import Log
from ._codex_usage import merge_threads


class CodexLog(Log):
    def __init__(self, path, provider="codex"):
        super().__init__(path, provider)
