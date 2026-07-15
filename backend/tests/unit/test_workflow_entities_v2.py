import pytest
from pydantic import ValidationError

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.retry import RetryConfig
from lumen_core.workflow.types import SegmentType


def test_base_node_data_default_timeout_none():
    d = BaseNodeData()
    assert d.timeout is None
    assert d.default_value is None
    assert d.error_strategy is None
    assert d.retry_config.max_retries == 0


def test_base_node_data_timeout_set():
    d = BaseNodeData(timeout=10.5, default_value={"x": 1}, error_strategy="default_value")
    assert d.timeout == 10.5
    assert d.default_value == {"x": 1}
    assert d.error_strategy == "default_value"


def test_base_node_data_error_strategy_literal_validates():
    d = BaseNodeData(error_strategy="fail_branch")
    assert d.error_strategy == "fail_branch"
    d = BaseNodeData(error_strategy="ignore")
    assert d.error_strategy == "ignore"
    with pytest.raises(ValidationError):
        BaseNodeData(error_strategy="bogus")


def test_base_node_data_retry_config_default():
    d = BaseNodeData()
    assert isinstance(d.retry_config, RetryConfig)
    assert d.retry_config.max_retries == 0
    assert d.retry_config.retry_interval == 1.0


def test_base_node_data_extra_ignored_still_works():
    d = BaseNodeData.model_validate({
        "title": "X",
        "label": "old field",
        "timeout": 5.0,
    })
    assert d.timeout == 5.0
    assert not hasattr(d, "label")


def test_retry_config_importable_from_retry_module():
    rc = RetryConfig(max_retries=3, retry_interval=0.5)
    assert rc.max_retries == 3
    assert rc.retry_interval == 0.5


def test_retry_config_validates_negative():
    with pytest.raises(ValidationError):
        RetryConfig(max_retries=-1)
    with pytest.raises(ValidationError):
        RetryConfig(retry_interval=-1.0)
