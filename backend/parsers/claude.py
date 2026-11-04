from ._log import Log


class ClaudeLog(Log):
    def __init__(self, path, provider="claude"):
        super().__init__(path, provider)
