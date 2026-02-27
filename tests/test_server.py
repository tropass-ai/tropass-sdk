import http
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from tropass_sdk.schemas import MLModelResponseSchema
from tropass_sdk.server import ModelServer


def sync_model(_model_input: dict[str, list[Any]], _common_resources: dict[str, Any]) -> dict[str, Any]:
    return {"panel_items": []}


async def async_model(_model_input: dict[str, list[Any]], _common_resources: dict[str, Any]) -> MLModelResponseSchema:
    return MLModelResponseSchema(panel_items=[])


@pytest.mark.anyio
async def test_async_server() -> None:
    app = ModelServer(
        model_func=async_model,
        model_name="test-model",
        model_description="test-description",
        model_version="1.0.0",
    ).build_application()

    client = TestClient(app)

    request_data = {
        "model_input": {
            "test_field": ["test_value"],
        },
        "common_resources": {
            "files_directory_path": "/tmp/test",  # noqa: S108
        },
    }

    response = client.post("/prediction", json=request_data)

    assert response.status_code == http.HTTPStatus.OK

    assert response.json() == {"panel_items": []}


def test_sync_server() -> None:
    app = ModelServer(
        model_func=sync_model,
        model_name="test-model",
        model_description="test-description",
        model_version="1.0.0",
    ).build_application()

    client = TestClient(app)

    request_data = {
        "model_input": {
            "test_field": ["test_value"],
        },
        "common_resources": {
            "files_directory_path": "/tmp/test",  # noqa: S108
        },
    }

    response = client.post("/prediction", json=request_data)

    assert response.status_code == http.HTTPStatus.OK

    assert response.json() == {"panel_items": []}


def test_invalid_body() -> None:
    app = ModelServer(
        model_func=sync_model,
        model_name="test-model",
        model_description="test-description",
        model_version="1.0.0",
    ).build_application()

    client = TestClient(app)

    response = client.post("/prediction", json=[1, 2, 3])

    assert response.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY


def test_prediction_returns_traceback_in_debug_mode() -> None:
    app = ModelServer(
        model_func=Mock(side_effect=ValueError),
        model_name="test-model",
        model_description="test-description",
        model_version="1.0.0",
        debug=True,
    ).build_application()

    client = TestClient(app)

    request_data = {
        "model_input": {
            "test_field": ["test_value"],
        },
        "common_resources": {
            "files_directory_path": "/tmp/test",  # noqa: S108
        },
    }

    response = client.post("/prediction", json=request_data)

    assert response.status_code == http.HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.text == ""
