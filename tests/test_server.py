import http
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tropass_sdk.schemas.model_contract_schema import MLModelRequestSchema, MLModelResponseSchema
from tropass_sdk.server import ModelServer


def sync_model(_data: MLModelRequestSchema) -> dict[str, Any]:
    return {"panel_items": []}


async def async_model(_data: MLModelRequestSchema) -> MLModelResponseSchema:
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
        "data": [
            {
                "input_field_name": "test_field",
                "input_field_value": ["test_value"],
                "input_field_type": "text",
            }
        ],
        "version": "1.0.0",
        "person_id": "test-person-id",
        "path_temp_folder": "/tmp/test",  # noqa: S108
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
        "data": [
            {
                "input_field_name": "test_field",
                "input_field_value": ["test_value"],
                "input_field_type": "text",
            }
        ],
        "version": "1.0.0",
        "person_id": "test-person-id",
        "path_temp_folder": "/tmp/test",  # noqa: S108
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
