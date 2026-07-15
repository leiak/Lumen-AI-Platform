import copy

from lumen_scripts.migrate_workflow_to_v2 import migrate_definition, _parse_simple_condition


def test_adds_version_and_outputs_to_llm_node():
    old = {
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "config": {"title": "LLM", "prompt": "hi"},
            }
        ],
        "edges": [],
    }
    new = migrate_definition(copy.deepcopy(old))
    node = new["nodes"][0]
    assert node["config"]["version"] == "1"
    out_names = [o["name"] for o in node["config"]["outputs"]]
    assert "response" in out_names
    assert "model" in out_names


def test_migrates_condition_string_to_cases():
    old = {
        "nodes": [
            {
                "id": "c1",
                "type": "condition",
                "config": {"title": "C", "condition": "x == 'yes'"},
            }
        ],
        "edges": [
            {"id": "e1", "source": "c1", "target": "n1", "condition": "True"},
            {"id": "e2", "source": "c1", "target": "n2", "condition": "False"},
        ],
    }
    new = migrate_definition(copy.deepcopy(old))
    cond_node = next(n for n in new["nodes"] if n["id"] == "c1")
    assert "cases" in cond_node["config"]
    assert len(cond_node["config"]["cases"]) == 1
    case = cond_node["config"]["cases"][0]
    assert case["conditions"][0]["comparison_operator"] == "="
    assert case["conditions"][0]["value"] == "yes"
    # legacy field preserved for audit
    assert cond_node["config"].get("condition") == "x == 'yes'"
    # edges: first one gets the case's case_id; second gets "false"
    assert new["edges"][0]["sourceHandle"] == case["case_id"]
    assert new["edges"][1]["sourceHandle"] == "false"


def test_complex_condition_string_kept_verbatim():
    """Multi-token expressions (with 'and' / function calls) should be left for runtime safe_eval."""
    old = {
        "nodes": [
            {
                "id": "c1",
                "type": "condition",
                "config": {"title": "C", "condition": "a > 1 and b < 2"},
            }
        ],
        "edges": [{"id": "e1", "source": "c1", "target": "n1", "condition": "True"}],
    }
    new = migrate_definition(copy.deepcopy(old))
    cond_node = next(n for n in new["nodes"] if n["id"] == "c1")
    # Complex → no cases synthesized, but still add version + outputs
    assert cond_node["config"].get("version") == "1"
    assert "cases" not in cond_node["config"] or not cond_node["config"]["cases"]
    assert cond_node["config"]["condition"] == "a > 1 and b < 2"


def test_output_field_renamed():
    old = {
        "nodes": [
            {
                "id": "o1",
                "type": "output",
                "config": {"title": "O", "output": {"field": "current"}},
            }
        ],
        "edges": [],
    }
    new = migrate_definition(copy.deepcopy(old))
    out = next(n for n in new["nodes"] if n["id"] == "o1")
    assert out["config"]["field"] == "current"


def test_migration_is_idempotent():
    old = {
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "config": {
                    "title": "L",
                    "version": "1",
                    "outputs": [{"name": "response", "type": "string"}],
                },
            }
        ],
        "edges": [],
    }
    new1 = migrate_definition(copy.deepcopy(old))
    new2 = migrate_definition(copy.deepcopy(new1))
    # If we strip the timestamp, the structures are byte-equal
    assert new1 == new2


def test_input_node_gets_default_variable():
    old = {"nodes": [{"id": "i1", "type": "input", "config": {}}], "edges": []}
    new = migrate_definition(copy.deepcopy(old))
    inp = next(n for n in new["nodes"] if n["id"] == "i1")
    assert inp["config"]["version"] == "1"
    assert "variables" in inp["config"]
    assert any(v["name"] == "value" for v in inp["config"]["variables"])
