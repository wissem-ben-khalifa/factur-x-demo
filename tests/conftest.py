import pytest

from facturx_demo.validators import docker_available


def pytest_collection_modifyitems(config, items):
    """Skip tests marked `validators` when Docker or the validator image is missing."""
    if docker_available():
        return
    skip = pytest.mark.skip(reason="Docker or image facturx-validators:1 not available")
    for item in items:
        if "validators" in item.keywords:
            item.add_marker(skip)
