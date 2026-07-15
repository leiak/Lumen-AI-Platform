import re

from lumen_core.workflow.variables import NoneVariable
from lumen_core.workflow.variable_pool import VariablePool

NEW_SYNTAX_REGEX = re.compile(r"\{\{#([a-zA-Z0-9_.\-]+)#\}\}")
LEGACY_SYNTAX_REGEX = re.compile(r"\{\{([a-zA-Z0-9_.\-]+)\}\}")


class VariableTemplateParser:
    """模板解析器:支持新 {{#...#}} 与老 {{...}} 双语法。"""

    def __init__(self, template: str) -> None:
        self.template = template
        self.variable_keys: list[str] = NEW_SYNTAX_REGEX.findall(template)

    def format(self, pool: VariablePool) -> str:
        def new_repl(m: re.Match) -> str:
            parts = m.group(1).split(".")
            if len(parts) < 2:
                return ""  # Malformed single-part selector — treat as missing
            var = pool.get(parts)
            if isinstance(var, NoneVariable):
                return ""
            return str(var.value)

        def legacy_repl(m: re.Match) -> str:
            parts = m.group(1).split(".")
            if len(parts) < 2:
                return ""  # Malformed single-part selector — treat as missing
            var = pool.get(parts)
            if isinstance(var, NoneVariable):
                return ""
            return str(var.value)

        result = NEW_SYNTAX_REGEX.sub(new_repl, self.template)
        result = LEGACY_SYNTAX_REGEX.sub(legacy_repl, result)
        return result

    def extract_variable_selectors(self) -> list[list[str]]:
        """Return the [node_id, var_name, ...sub_path] selectors from the new syntax {{#...#}} only.

        Legacy {{path}} syntax selectors are NOT extracted (intentional asymmetry — new syntax is
        the canonical, machine-readable form; legacy is for backward compatibility only).
        """
        return [k.split(".") for k in self.variable_keys]
