"""Whitelist of safe names available to M16 script skills."""
import json
import math
import re
import datetime
import typing


SAFE_BUILTINS = {
    "len", "str", "int", "float", "bool", "list", "dict", "tuple", "set",
    "range", "enumerate", "zip", "map", "filter", "sorted", "sum", "min", "max",
    "abs", "round", "isinstance", "type", "print",
    "True", "False", "None",
    "__import__",  # for whitelisted stdlib modules; AST check blocks os/subprocess/etc.
}


SAFE_GLOBALS = {
    "__builtins__": SAFE_BUILTINS,
    "json": json,
    "re": re,
    "math": math,
    "datetime": datetime,
    "typing": typing,
}


# Names that must NEVER appear in user code (security policy)
FORBIDDEN_NAMES = frozenset({
    "os", "subprocess", "socket", "sys", "shutil", "pathlib",
    "open", "eval", "exec", "compile", "__import__",
    "globals", "locals", "breakpoint", "input", "memoryview",
    "getattr", "setattr", "delattr",  # attribute access is dangerous
    "importlib",
})
