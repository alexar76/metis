"""Restricted Python code execution for the code interpreter tool."""

from __future__ import annotations

import ast
import builtins
import io
import sys
from typing import Any, Dict, Tuple

_BLOCKED_MODULES = frozenset({
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "pathlib",
    "importlib",
    "ctypes",
    "multiprocessing",
    "threading",
    "signal",
    "resource",
    "pty",
    "fcntl",
    "pickle",
    "shelve",
    "code",
    "codeop",
    "webbrowser",
    "http",
    "urllib",
    "ftplib",
    "smtplib",
    "tempfile",
    "glob",
    "mmap",
    "select",
    "pwd",
    "grp",
    "builtins",
    "__builtin__",
})

_ALLOWED_MODULES = frozenset({
    "math",
    "json",
    "re",
    "datetime",
    "collections",
    "itertools",
    "functools",
    "statistics",
    "decimal",
    "fractions",
    "random",
    "typing",
    "copy",
    "string",
    "hashlib",
    "base64",
    "textwrap",
    "numbers",
    "enum",
    "dataclasses",
    "operator",
    "bisect",
    "heapq",
    "array",
    "csv",
    "io",
})


def _safe_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
    base = name.split(".")[0]
    if base in _BLOCKED_MODULES:
        raise ImportError(f"Import of '{name}' is not allowed in sandbox")
    if base not in _ALLOWED_MODULES:
        raise ImportError(f"Import of '{name}' is not allowed in sandbox")
    return builtins.__import__(name, globals, locals, fromlist, level)


_SAFE_BUILTINS: Dict[str, Any] = {
    name: getattr(builtins, name)
    for name in (
        "abs",
        "all",
        "any",
        "bool",
        "bytes",
        "chr",
        "dict",
        "divmod",
        "enumerate",
        "filter",
        "float",
        "format",
        "frozenset",
        "hex",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "map",
        "max",
        "min",
        "next",
        "oct",
        "ord",
        "pow",
        "print",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "slice",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
        "True",
        "False",
        "None",
        "Exception",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "StopIteration",
        "RuntimeError",
        "ArithmeticError",
        "ZeroDivisionError",
    )
}
# SECURITY: do NOT include 'type' — it enables __subclasses__() jailbreak.
# SECURITY: do NOT include 'object', 'super', 'getattr', 'setattr', 'hasattr',
# 'classmethod', 'staticmethod', 'property' — introspection → escape.
_SAFE_BUILTINS["__import__"] = _safe_import


# SECURITY: non-dunder introspection attributes that reach frames/traceback/globals.
# A blacklist substring scan alone is whack-a-mole (it missed the frame-walk escape
# `e.__traceback__.tb_frame.f_back.f_globals["sys"]`), so these are ALSO enforced
# structurally in _screen_code() via the AST.
_FORBIDDEN_ATTRS = frozenset({
    "f_back", "f_globals", "f_locals", "f_builtins", "f_code", "f_frame", "f_trace",
    "tb_frame", "tb_next", "gi_frame", "gi_code", "cr_frame", "cr_code", "ag_frame",
    "ag_code", "gi_yieldfrom", "cr_await", "func_globals", "func_code",
})
# Builtin-ish names that enable escape/introspection even though most are already
# absent from _SAFE_BUILTINS (defense-in-depth + a clear error).
_FORBIDDEN_NAMES = frozenset({
    "eval", "exec", "compile", "globals", "locals", "vars", "getattr", "setattr",
    "delattr", "open", "input", "breakpoint", "__import__", "memoryview", "object",
    "type", "super", "classmethod", "staticmethod", "property", "help", "exit", "quit",
})
# Substring scan — complements the AST screen by catching dunders/frame attrs hidden
# inside string literals (e.g. the str.format "{0.__class__}" attribute-access trick,
# which the AST sees only as a constant string).
_DANGER_SUBSTRINGS = (
    "__subclasses__", "__bases__", "__mro__", "__class__", "__base__", "__globals__",
    "__code__", "__func__", "__self__", "__dict__", "__builtins__", "__import__",
    "__traceback__", "__getattribute__", "__reduce__", "__subclasshook__",
    "__init_subclass__", "tb_frame", "f_back", "f_globals", "f_locals", "f_builtins",
    "gi_frame", "cr_frame", "ag_frame", "getattr(", "eval(", "exec(", "open(", "compile(",
)


def _screen_code(code: str) -> str | None:
    """Structural (AST) + substring screen. Returns an error string, or None if allowed."""
    code_lower = code.lower()
    for pat in _DANGER_SUBSTRINGS:
        if pat in code_lower:
            return f"SecurityError: forbidden pattern '{pat}'"
    try:
        tree = ast.parse(code, "<user_code>", "exec")
    except SyntaxError as exc:
        return f"SyntaxError: {exc}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attr = node.attr
            if (attr.startswith("__") and attr.endswith("__")) or attr in _FORBIDDEN_ATTRS:
                return f"SecurityError: forbidden attribute access '{attr}'"
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            return f"SecurityError: forbidden name '{node.id}'"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[0]
                if base not in _ALLOWED_MODULES:
                    return f"SecurityError: import of '{alias.name}' is not allowed"
        elif isinstance(node, ast.ImportFrom):
            base = (node.module or "").split(".")[0]
            if base not in _ALLOWED_MODULES:
                return f"SecurityError: import of '{node.module}' is not allowed"
    return None


def execute_sandboxed(code: str) -> Tuple[bool, str, str]:
    """
    Execute Python code in a restricted namespace.

    Returns (success, stdout, stderr).
    """
    # SECURITY: structural + substring pre-screen for sandbox-escape patterns.
    screen_error = _screen_code(code)
    if screen_error is not None:
        return False, "", screen_error
    namespace: Dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
    stdout = io.StringIO()
    stderr = io.StringIO()

    try:
        compiled = compile(code, "<user_code>", "exec")
    except SyntaxError as exc:
        return False, "", f"SyntaxError: {exc}"

    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stdout, stderr
    try:
        exec(compiled, namespace, namespace)  # noqa: S102 — intentional sandboxed exec
        return True, stdout.getvalue(), stderr.getvalue()
    except Exception as exc:
        stderr.write(f"{type(exc).__name__}: {exc}\n")
        return False, stdout.getvalue(), stderr.getvalue()
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr


def main() -> None:
    """CLI entry: read code from stdin and run in sandbox (used by subprocess isolation)."""
    code = sys.stdin.read()
    ok, out, err = execute_sandboxed(code)
    if out:
        sys.stdout.write(out)
    if err:
        sys.stderr.write(err)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
