import http
import json
import typing
import uuid

import circuitbreaker  # type: ignore[import-untyped]
import fastapi
import fastapi.responses
import httpx
import pydantic
import pytest

from tropass_sdk.client import (
    GatewayCallError,
    GatewayClient,
    GatewayClientConfig,
    GatewayClientConfigValidationError,
    GatewayFile,
    GatewayIdempotencyConflictError,
    GatewayResponseError,
    GatewayTaskNotFoundError,
    GatewayTaskTimeoutError,
    GatewayTransientResponseError,
    JsonDict,
)
from tropass_sdk.settings import gateway_client_settings


GATEWAY_API_TOKEN = "private-token"  # noqa: S105
DEFAULT_MAX_ATTEMPTS = 3
TWO_REQUESTS = 2
FOUR_REQUESTS = 4
THREE_REQUESTS = 3
MODEL_ID = uuid.UUID("00000000-0000-0000-0000-000000000123")
SUBMITTED_TASK_ID = uuid.UUID("00000000-0000-0000-0000-000000000456")
SUBMIT_PATH = f"/{gateway_client_settings.call_model_path}"
FETCH_PATH_TEMPLATE = f"/{gateway_client_settings.model_task_path}/{{task_id}}"


def make_gateway_client(
    monkeypatch: pytest.MonkeyPatch,
    transport: httpx.AsyncBaseTransport,
    *,
    retry_attempts: int = DEFAULT_MAX_ATTEMPTS,
    circuit_failure_threshold: int = DEFAULT_MAX_ATTEMPTS,
    circuit_recovery_seconds: int = 30,
    result_deadline_seconds: float = 1800.0,
    poll_interval_seconds: float = 2.0,
    http_timeout_seconds: float = 10.0,
) -> GatewayClient:
    client_config = GatewayClientConfig(
        retry_attempts=retry_attempts,
        retry_timeout_seconds=30.0,
        circuit_failure_threshold=circuit_failure_threshold,
        circuit_recovery_seconds=circuit_recovery_seconds,
        result_deadline_seconds=result_deadline_seconds,
        poll_interval_seconds=poll_interval_seconds,
        http_timeout_seconds=http_timeout_seconds,
    )
    original_http_client = httpx.AsyncClient

    def create_http_client(**kwargs: typing.Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_http_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", create_http_client)
    return GatewayClient(
        gateway_url="https://gateway.example.com/",
        gateway_api_token=GATEWAY_API_TOKEN,
        client_config=client_config,
    )


def make_submit_response(task_id: uuid.UUID) -> httpx.Response:
    return httpx.Response(
        http.HTTPStatus.ACCEPTED,
        json={"task_id": str(task_id), "status": "distributed"},
    )


def make_pending_response(task_id: uuid.UUID) -> httpx.Response:
    return httpx.Response(
        http.HTTPStatus.OK,
        json={"task_id": str(task_id), "status": "processing_started"},
    )


def make_completed_response(task_id: uuid.UUID, result: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        http.HTTPStatus.OK,
        json={"task_id": str(task_id), "status": "processing_completed", "result": result},
    )


def make_error_response(task_id: uuid.UUID, error_message: str = "Model execution failed.") -> httpx.Response:
    return httpx.Response(
        http.HTTPStatus.OK,
        json={"task_id": str(task_id), "status": "processing_error", "error_message": error_message},
    )


class SubmittedModelCall(pydantic.BaseModel):
    model_payload: JsonDict
    uploaded_files: list[GatewayFile]


def build_gateway_application(
    submitted_calls: list[SubmittedModelCall],
    *,
    transient_failures: int = 0,
) -> fastapi.FastAPI:
    gateway_application = fastapi.FastAPI()

    @gateway_application.post(SUBMIT_PATH)
    async def call_model(
        model_payload: typing.Annotated[str, fastapi.Form(alias=gateway_client_settings.model_payload_form_field)],
        files: typing.Annotated[
            list[fastapi.UploadFile] | None,
            fastapi.File(alias=gateway_client_settings.model_files_form_field),
        ] = None,
    ) -> fastapi.Response:
        submitted_calls.append(
            SubmittedModelCall(
                model_payload=json.loads(model_payload),
                uploaded_files=[
                    GatewayFile(
                        file_name=uploaded_file.filename or "",
                        file_content=await uploaded_file.read(),
                        content_type=uploaded_file.content_type,
                    )
                    for uploaded_file in files or []
                ],
            ),
        )
        if len(submitted_calls) <= transient_failures:
            return fastapi.responses.JSONResponse(
                status_code=http.HTTPStatus.BAD_GATEWAY,
                content={"detail": "temporary"},
            )
        return fastapi.responses.JSONResponse(
            status_code=http.HTTPStatus.ACCEPTED,
            content={"task_id": str(SUBMITTED_TASK_ID), "status": "distributed"},
        )

    @gateway_application.get(FETCH_PATH_TEMPLATE.format(task_id="{task_id}"))
    async def fetch_model_task(task_id: str) -> JsonDict:
        return {"task_id": task_id, "status": "processing_completed", "result": {"score": 10}}

    return gateway_application


def assert_submitted_call(
    submitted_call: SubmittedModelCall,
    *,
    model_request_data: JsonDict,
    expected_files: list[GatewayFile] | None = None,
) -> None:
    assert submitted_call.model_payload == {
        "model_id": str(MODEL_ID),
        "model_request_data": model_request_data,
    }
    assert submitted_call.uploaded_files == (expected_files or [])


def assert_submit_headers(request: httpx.Request, *, idempotency_key: str | None = None) -> None:
    assert request.headers[gateway_client_settings.api_token_header] == f"Bearer {GATEWAY_API_TOKEN}"
    assert (
        request.headers[gateway_client_settings.model_call_version_header]
        == gateway_client_settings.model_call_version_value
    )
    if idempotency_key is not None:
        assert request.headers[gateway_client_settings.idempotency_key_header] == idempotency_key


def assert_fetch_headers(request: httpx.Request) -> None:
    assert request.headers[gateway_client_settings.api_token_header] == f"Bearer {GATEWAY_API_TOKEN}"
    assert (
        request.headers[gateway_client_settings.model_call_version_header]
        == gateway_client_settings.model_call_version_value
    )


def test_client_validates_config() -> None:
    with pytest.raises(GatewayClientConfigValidationError):
        GatewayClient(
            gateway_url="https://gateway.example.com/",
            gateway_api_token=GATEWAY_API_TOKEN,
            client_config=GatewayClientConfig(retry_attempts=0),
        )


@pytest.mark.anyio
async def test_call_model_returns_completed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = uuid.uuid4()
    submit_request: httpx.Request | None = None
    fetch_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submit_request, fetch_request
        if request.url.path == SUBMIT_PATH:
            submit_request = request
            return make_submit_response(task_id)
        fetch_request = request
        return make_completed_response(task_id, {"score": 10})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler))

    response_payload = await client.call_model(MODEL_ID, {"feature": "value"})

    assert response_payload == {"score": 10}
    assert submit_request is not None
    assert str(submit_request.url) == f"https://gateway.example.com{SUBMIT_PATH}"
    assert gateway_client_settings.idempotency_key_header in submit_request.headers
    assert_fetch_headers_of_submit(submit_request)
    assert fetch_request is not None
    assert str(fetch_request.url) == f"https://gateway.example.com{FETCH_PATH_TEMPLATE.format(task_id=task_id)}"
    assert_fetch_headers(fetch_request)


@pytest.mark.anyio
async def test_call_model_submits_payload_readable_by_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    submitted_calls: list[SubmittedModelCall] = []
    gateway_application = build_gateway_application(submitted_calls)
    client = make_gateway_client(monkeypatch, httpx.ASGITransport(app=gateway_application))

    response_payload = await client.call_model(MODEL_ID, {"feature": "value"})

    assert response_payload == {"score": 10}
    assert len(submitted_calls) == 1
    assert_submitted_call(submitted_calls[0], model_request_data={"feature": "value"})


@pytest.mark.anyio
async def test_call_model_sends_files_readable_by_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    submitted_calls: list[SubmittedModelCall] = []
    uploaded_files = [
        GatewayFile(file_name="report.csv", file_content=b"column\nvalue\n", content_type="text/csv"),
        GatewayFile(file_name="picture.png", file_content=b"\x89PNG\r\n", content_type="image/png"),
    ]
    gateway_application = build_gateway_application(submitted_calls)
    client = make_gateway_client(monkeypatch, httpx.ASGITransport(app=gateway_application))

    response_payload = await client.call_model(MODEL_ID, {"feature": "value"}, files=uploaded_files)

    assert response_payload == {"score": 10}
    assert len(submitted_calls) == 1
    assert_submitted_call(submitted_calls[0], model_request_data={"feature": "value"}, expected_files=uploaded_files)


@pytest.mark.anyio
async def test_submit_model_task_retries_preserve_file_content(monkeypatch: pytest.MonkeyPatch) -> None:
    submitted_calls: list[SubmittedModelCall] = []
    uploaded_files = [GatewayFile(file_name="report.csv", file_content=b"column\nvalue\n", content_type="text/csv")]
    gateway_application = build_gateway_application(submitted_calls, transient_failures=1)
    client = make_gateway_client(monkeypatch, httpx.ASGITransport(app=gateway_application), retry_attempts=2)

    submission = await client.submit_model_task(MODEL_ID, {"feature": "value"}, files=uploaded_files)

    assert submission.task_id == str(SUBMITTED_TASK_ID)
    assert len(submitted_calls) == TWO_REQUESTS
    for submitted_call in submitted_calls:
        assert_submitted_call(submitted_call, model_request_data={"feature": "value"}, expected_files=uploaded_files)


def assert_fetch_headers_of_submit(request: httpx.Request) -> None:
    assert_submit_headers(request, idempotency_key=request.headers[gateway_client_settings.idempotency_key_header])


@pytest.mark.anyio
async def test_call_model_polls_until_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = uuid.uuid4()
    fetch_counter = 0

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == SUBMIT_PATH:
            return make_submit_response(task_id)
        nonlocal fetch_counter
        fetch_counter += 1
        if fetch_counter < THREE_REQUESTS:
            return make_pending_response(task_id)
        return make_completed_response(task_id, {"result": "ready"})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler), poll_interval_seconds=0.0)

    response_payload = await client.call_model(MODEL_ID, {"feature": "value"})

    assert response_payload == {"result": "ready"}
    assert fetch_counter == THREE_REQUESTS


@pytest.mark.anyio
async def test_call_model_retries_transient_submit_status(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = uuid.uuid4()
    submit_counter = 0
    captured_idempotency_keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == SUBMIT_PATH:
            nonlocal submit_counter
            submit_counter += 1
            captured_idempotency_keys.append(request.headers[gateway_client_settings.idempotency_key_header])
            if submit_counter == 1:
                return httpx.Response(http.HTTPStatus.BAD_GATEWAY, json={"detail": "temporary"})
            return make_submit_response(task_id)
        return make_completed_response(task_id, {"result": "ready"})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler), retry_attempts=2)

    response_payload = await client.call_model(MODEL_ID, {"feature": "value"})

    assert response_payload == {"result": "ready"}
    assert submit_counter == TWO_REQUESTS
    assert len(captured_idempotency_keys) == TWO_REQUESTS
    assert captured_idempotency_keys[0] == captured_idempotency_keys[1]


@pytest.mark.anyio
async def test_call_model_retries_submit_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = uuid.uuid4()
    submit_counter = 0

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == SUBMIT_PATH:
            nonlocal submit_counter
            submit_counter += 1
            if submit_counter == 1:
                raise httpx.ConnectError("connection refused")
            return make_submit_response(task_id)
        return make_completed_response(task_id, {"result": "ready"})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler), retry_attempts=2)

    response_payload = await client.call_model(MODEL_ID, {"feature": "value"})

    assert response_payload == {"result": "ready"}
    assert submit_counter == TWO_REQUESTS


@pytest.mark.parametrize(
    "status_code",
    [
        http.HTTPStatus.BAD_REQUEST,
        http.HTTPStatus.UNAUTHORIZED,
        http.HTTPStatus.FORBIDDEN,
    ],
)
@pytest.mark.anyio
async def test_call_model_does_not_retry_non_transient_submit_status(
    monkeypatch: pytest.MonkeyPatch,
    status_code: http.HTTPStatus,
) -> None:
    submit_counter = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal submit_counter
        submit_counter += 1
        return httpx.Response(status_code, json={"detail": "client error"})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler), retry_attempts=3)

    with pytest.raises(GatewayCallError):
        await client.call_model(MODEL_ID, {"feature": "value"})

    assert submit_counter == 1


@pytest.mark.anyio
async def test_call_model_raises_idempotency_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(http.HTTPStatus.CONFLICT, json={"detail": "idempotency conflict"})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler), retry_attempts=3)

    with pytest.raises(GatewayIdempotencyConflictError):
        await client.call_model(MODEL_ID, {"feature": "value"})


@pytest.mark.anyio
async def test_call_model_rejects_malformed_submit_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == SUBMIT_PATH:
            return httpx.Response(http.HTTPStatus.ACCEPTED, json=[1, 2])
        return httpx.Response(http.HTTPStatus.OK, json={})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(GatewayResponseError):
        await client.call_model(MODEL_ID, {"feature": "value"})


@pytest.mark.anyio
async def test_call_model_rejects_submit_response_without_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(http.HTTPStatus.ACCEPTED, json={"status": "distributed"})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(GatewayResponseError):
        await client.call_model(MODEL_ID, {"feature": "value"})


@pytest.mark.anyio
async def test_call_model_raises_task_not_found_on_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == SUBMIT_PATH:
            return make_submit_response(task_id)
        return httpx.Response(http.HTTPStatus.NOT_FOUND, json={"detail": "not found"})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(GatewayTaskNotFoundError):
        await client.call_model(MODEL_ID, {"feature": "value"})


@pytest.mark.anyio
async def test_call_model_raises_call_error_on_processing_error(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == SUBMIT_PATH:
            return make_submit_response(task_id)
        return make_error_response(task_id, error_message="inference crashed")

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(GatewayCallError) as exception_info:
        await client.call_model(MODEL_ID, {"feature": "value"})

    assert "inference crashed" in str(exception_info.value)


@pytest.mark.anyio
async def test_call_model_raises_task_timeout_after_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == SUBMIT_PATH:
            return make_submit_response(task_id)
        return make_pending_response(task_id)

    client = make_gateway_client(
        monkeypatch,
        httpx.MockTransport(handler),
        result_deadline_seconds=0.0,
        poll_interval_seconds=0.0,
    )

    with pytest.raises(GatewayTaskTimeoutError):
        await client.call_model(MODEL_ID, {"feature": "value"})


@pytest.mark.anyio
async def test_call_model_rejects_completed_task_without_result(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == SUBMIT_PATH:
            return make_submit_response(task_id)
        return httpx.Response(
            http.HTTPStatus.OK,
            json={"task_id": str(task_id), "status": "processing_completed"},
        )

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(GatewayResponseError):
        await client.call_model(MODEL_ID, {"feature": "value"})


@pytest.mark.anyio
async def test_call_model_opens_circuit_after_exhausted_submit_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    submit_counter = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal submit_counter
        submit_counter += 1
        return httpx.Response(http.HTTPStatus.SERVICE_UNAVAILABLE, json={"detail": "unavailable"})

    client = make_gateway_client(
        monkeypatch,
        httpx.MockTransport(handler),
        retry_attempts=2,
        circuit_failure_threshold=2,
    )

    with pytest.raises(GatewayTransientResponseError):
        await client.call_model(MODEL_ID, {"feature": "value"})
    with pytest.raises(GatewayTransientResponseError):
        await client.call_model(MODEL_ID, {"feature": "value"})
    with pytest.raises(circuitbreaker.CircuitBreakerError):
        await client.call_model(MODEL_ID, {"feature": "value"})

    assert submit_counter == FOUR_REQUESTS


@pytest.mark.anyio
async def test_circuit_recovers_after_recovery_window(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = uuid.uuid4()
    submit_counter = 0

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == SUBMIT_PATH:
            nonlocal submit_counter
            submit_counter += 1
            if submit_counter <= TWO_REQUESTS:
                return httpx.Response(http.HTTPStatus.SERVICE_UNAVAILABLE, json={"detail": "unavailable"})
            return make_submit_response(task_id)
        return make_completed_response(task_id, {"result": "recovered"})

    client = make_gateway_client(
        monkeypatch,
        httpx.MockTransport(handler),
        retry_attempts=1,
        circuit_failure_threshold=2,
        circuit_recovery_seconds=0,
        poll_interval_seconds=0.0,
    )

    with pytest.raises(GatewayTransientResponseError):
        await client.call_model(MODEL_ID, {"feature": "value"})
    with pytest.raises(GatewayTransientResponseError):
        await client.call_model(MODEL_ID, {"feature": "value"})

    response_payload = await client.call_model(MODEL_ID, {"feature": "value"})

    assert response_payload == {"result": "recovered"}


@pytest.mark.anyio
async def test_pending_status_does_not_open_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == SUBMIT_PATH:
            return make_submit_response(task_id)
        return make_pending_response(task_id)

    client = make_gateway_client(
        monkeypatch,
        httpx.MockTransport(handler),
        result_deadline_seconds=0.0,
        poll_interval_seconds=0.0,
        circuit_failure_threshold=1,
    )

    first_call_task_id = uuid.uuid4()
    monkeypatch.setattr(uuid, "uuid4", lambda: first_call_task_id)

    with pytest.raises(GatewayTaskTimeoutError):
        await client.call_model(MODEL_ID, {"feature": "value"})

    second_call_task_id = uuid.uuid4()
    monkeypatch.setattr(uuid, "uuid4", lambda: second_call_task_id)

    with pytest.raises(GatewayTaskTimeoutError):
        await client.call_model(MODEL_ID, {"feature": "value"})

    with pytest.raises(GatewayTaskTimeoutError):
        await client.call_model(MODEL_ID, {"feature": "value"})


@pytest.mark.anyio
async def test_manual_lifecycle_submit_fetch_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = uuid.uuid4()
    submit_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == SUBMIT_PATH:
            nonlocal submit_request
            submit_request = request
            return make_submit_response(task_id)
        return make_completed_response(task_id, {"score": 42})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler), poll_interval_seconds=0.0)

    idempotency_key = uuid.uuid4()
    submission = await client.submit_model_task(MODEL_ID, {"feature": "value"}, idempotency_key)

    assert submission.model_dump() == {"task_id": str(task_id), "status": "distributed"}
    assert submit_request is not None
    assert submit_request.headers[gateway_client_settings.idempotency_key_header] == str(idempotency_key)

    fetched_status = await client.fetch_model_task(task_id)
    assert fetched_status.status == "processing_completed"

    result_payload = await client.wait_for_model_task(task_id)
    assert result_payload == {"score": 42}


@pytest.mark.anyio
async def test_submit_model_task_generates_idempotency_key_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = uuid.uuid4()
    submit_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submit_request
        submit_request = request
        return make_submit_response(task_id)

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler))

    await client.submit_model_task(MODEL_ID, {"feature": "value"})

    assert submit_request is not None
    assert gateway_client_settings.idempotency_key_header in submit_request.headers


def assert_idempotency_key_header_in(request: httpx.Request) -> None:
    assert gateway_client_settings.idempotency_key_header in request.headers


@pytest.mark.anyio
async def test_fetch_model_task_retries_transient_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid.uuid4()
    fetch_counter = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal fetch_counter
        fetch_counter += 1
        if fetch_counter == 1:
            return httpx.Response(http.HTTPStatus.SERVICE_UNAVAILABLE, json={"detail": "temporary"})
        return make_completed_response(task_id, {"result": "ready"})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler), retry_attempts=2)

    fetched_status = await client.fetch_model_task(task_id)

    assert fetched_status.status == "processing_completed"
    assert fetch_counter == TWO_REQUESTS
    assert gateway_client_settings.idempotency_key_header  # sanity
