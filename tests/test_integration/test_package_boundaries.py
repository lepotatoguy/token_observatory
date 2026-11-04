"""The migrated package must not depend on deleted root-level modules."""
import ast
from pathlib import Path


def test_runtime_imports_stay_inside_the_package():
    root = Path(__file__).resolve().parents[2]
    retired = set("server archive claude_context claude_limits claude_statusline codex_usage "
                  "lmstudio_chats local_proxy live_limits limit_control minimax minimax_code "
                  "pricing providers session_hooks updater update_install".split())
    failures = []
    for path in (root / "backend").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = ([node.module] if isinstance(node, ast.ImportFrom) else
                       [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            for module in modules:
                if module in retired:
                    failures.append(f"{path.relative_to(root)}:{node.lineno}: {module}")
    assert not failures, "\n".join(failures)
