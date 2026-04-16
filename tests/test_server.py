import http
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from tropass_sdk.schemas import MLModelResponseSchema
from tropass_sdk.schemas import model_contract_schema as schemas
from tropass_sdk.server import ModelServer


def sync_model(
    _model_input: schemas.MODEL_INPUT_TYPE,
    _common_resources: schemas.COMMON_RESOURCES_TYPE,
    _request_metadata: schemas.MLModelRequestMetadataSchema | None = None,
) -> MLModelResponseSchema:
    return MLModelResponseSchema(panel_items=[])


async def async_model(
    _model_input: schemas.MODEL_INPUT_TYPE,
    _common_resources: schemas.COMMON_RESOURCES_TYPE,
    _request_metadata: schemas.MLModelRequestMetadataSchema | None = None,
) -> MLModelResponseSchema:
    return MLModelResponseSchema(panel_items=[])


def sync_model_with_metadata(
    _model_input: schemas.MODEL_INPUT_TYPE,
    _common_resources: schemas.COMMON_RESOURCES_TYPE,
    request_metadata: schemas.MLModelRequestMetadataSchema | None = None,
) -> MLModelResponseSchema:
    panel_name = "missing"
    if request_metadata is not None and request_metadata.user_id is not None:
        panel_name = request_metadata.user_id

    return MLModelResponseSchema(
        panel_items=[
            schemas.ModelPanelOutputSchema(
                panel_output_name=panel_name,
                panel_type="test-panel",
            ),
        ],
    )


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


def test_sync_server_passes_metadata_from_headers() -> None:
    app = ModelServer(
        model_func=sync_model_with_metadata,
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

    response = client.post(
        "/prediction",
        json=request_data,
        headers={"X-User-ID": "user-123"},
    )

    assert response.status_code == http.HTTPStatus.OK
    assert response.json() == {
        "panel_items": [
            {
                "panel_output_name": "user-123",
                "panel_type": "test-panel",
                "primary_data": None,
                "descriptions": [],
                "attachments": [],
                "panel_show_order": None,
            },
        ],
    }


def test_sync_server_passes_empty_metadata_when_headers_are_missing() -> None:
    app = ModelServer(
        model_func=sync_model_with_metadata,
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
    assert response.json() == {
        "panel_items": [
            {
                "panel_output_name": "missing",
                "panel_type": "test-panel",
                "primary_data": None,
                "descriptions": [],
                "attachments": [],
                "panel_show_order": None,
            },
        ],
    }


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


def test_prediction_openapi_contains_metadata_headers() -> None:
    app = ModelServer(
        model_func=sync_model,
        model_name="test-model",
        model_description="test-description",
        model_version="1.0.0",
    ).build_application()

    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == http.HTTPStatus.OK

    parameters = response.json()["paths"]["/prediction"]["post"]["parameters"]
    assert {
        parameter_item["name"]: parameter_item["schema"].get("default")
        for parameter_item in parameters
        if parameter_item["in"] == "header"
    } == {
        "X-User-ID": None,
        "X-User-Locale": "ru",
    }


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
