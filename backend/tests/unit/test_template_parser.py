from lumen_core.workflow.template_parser import VariableTemplateParser
from lumen_core.workflow.variable_pool import VariablePool


def test_format_new_syntax_basic():
    pool = VariablePool()
    pool.add(["n1", "text"], "hello")
    parser = VariableTemplateParser("{{#n1.text#}} world")
    assert parser.format(pool) == "hello world"


def test_format_new_syntax_nested():
    pool = VariablePool()
    pool.add(["n1", "user"], {"name": "Alice", "age": 30})
    parser = VariableTemplateParser("Hi {{#n1.user.name#}}, age {{#n1.user.age#}}")
    assert parser.format(pool) == "Hi Alice, age 30"


def test_format_missing_variable_returns_empty_string():
    pool = VariablePool()
    parser = VariableTemplateParser("Hi {{#nope.nothing#}}!")
    assert parser.format(pool) == "Hi !"


def test_format_legacy_syntax_falls_back():
    pool = VariablePool()
    pool.add(["input", "message"], "legacy hi")
    parser = VariableTemplateParser("{{input.message}}")
    assert parser.format(pool) == "legacy hi"


def test_format_mixed_syntax_priority():
    pool = VariablePool()
    pool.add(["n1", "x"], "new")
    pool.add(["input", "x"], "old")
    parser = VariableTemplateParser("{{#n1.x#}} | {{input.x}}")
    assert parser.format(pool) == "new | old"


def test_extract_variable_selectors():
    parser = VariableTemplateParser("{{#n1.text#}} and {{#n2.response#}}")
    assert parser.extract_variable_selectors() == [["n1", "text"], ["n2", "response"]]


def test_no_variables_passthrough():
    pool = VariablePool()
    parser = VariableTemplateParser("plain text only")
    assert parser.format(pool) == "plain text only"


def test_format_malformed_single_part_new_syntax_does_not_crash():
    """`{{#x#}}` (single-part, no node_id) should not raise — returns empty string."""
    pool = VariablePool()
    parser = VariableTemplateParser("before {{#x#}} after")
    assert parser.format(pool) == "before  after"


def test_format_malformed_single_part_legacy_does_not_crash():
    """`{{x}}` (single-part) should not raise — returns empty string."""
    pool = VariablePool()
    parser = VariableTemplateParser("before {{x}} after")
    assert parser.format(pool) == "before  after"


def test_format_malformed_unclosed_passthrough():
    """Unclosed `{{` is left as-is in the output (regex doesn't match)."""
    pool = VariablePool()
    parser = VariableTemplateParser("hello {{broken world")
    assert parser.format(pool) == "hello {{broken world"


def test_format_same_selector_referenced_twice():
    """Same selector referenced twice should resolve twice (independent lookups)."""
    pool = VariablePool()
    pool.add(["n1", "x"], "VALUE")
    parser = VariableTemplateParser("{{#n1.x#}}-{{#n1.x#}}")
    assert parser.format(pool) == "VALUE-VALUE"


def test_format_hyphen_containing_selector():
    """Hyphens in selector names are allowed by the regex."""
    pool = VariablePool()
    pool.add(["n1", "my-var"], "ok")
    parser = VariableTemplateParser("{{#n1.my-var#}}")
    assert parser.format(pool) == "ok"
