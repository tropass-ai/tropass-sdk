import http
import uuid

import httpx
import pybreaker
import pytest

from tropass_sdk.client import (
    GatewayCallError,
    GatewayClient,
    GatewayClientConfig,
    GatewayClientConfigValidationError,
    GatewayResponseError,
)


GATEWAY_API_TOKEN = "private-token"  # noqa: S105
DEFAULT_MAX_ATTEMPTS = 3
TWO_REQUESTS = 2
FOUR_REQUESTS = 4
MODEL_ID = uuid.UUID("00000000-0000-0000-0000-000000000123")


def make_gateway_client(
    monkeypatch: pytest.MonkeyPatch,
    transport: httpx.AsyncBaseTransport,
    *,
    retry_attempts: int = DEFAULT_MAX_ATTEMPTS,
    circuit_failure_threshold: int = DEFAULT_MAX_ATTEMPTS,
    circuit_recovery_seconds: int = 30,
) -> GatewayClient:
    client_config = GatewayClientConfig(
        retry_attempts=retry_attempts,
        retry_timeout_seconds=30.0,
        circuit_failure_threshold=circuit_failure_threshold,
        circuit_recovery_seconds=circuit_recovery_seconds,
    )
    original_http_client = httpx.AsyncClient

    def create_http_client(*, timeout: float) -> httpx.AsyncClient:
        return original_http_client(transport=transport, timeout=timeout)

    monkeypatch.setattr(httpx, "AsyncClient", create_http_client)
    return GatewayClient(
        gateway_url="https://gateway.example.com/",
        gateway_api_token=GATEWAY_API_TOKEN,
        client_config=client_config,
    )


def test_client_validates_config() -> None:
    with pytest.raises(GatewayClientConfigValidationError):
        GatewayClient(
            gateway_url="https://gateway.example.com/",
            gateway_api_token=GATEWAY_API_TOKEN,
            client_config=GatewayClientConfig(retry_attempts=0),
        )


@pytest.mark.anyio
async def test_call_model_returns_gateway_response(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(http.HTTPStatus.OK, json={"result": {"score": 10}})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler))

    response_payload = await client.call_model(MODEL_ID, {"feature": "value"})

    assert response_payload == {"result": {"score": 10}}
    assert captured_request is not None
    assert str(captured_request.url) == "https://gateway.example.com/api/rpc/call-model"
    assert captured_request.headers["X-API-TOKEN"] == GATEWAY_API_TOKEN
    assert captured_request.read() == (
        b'{"model_id":"00000000-0000-0000-0000-000000000123","model_request_data":{"feature":"value"}}'
    )


@pytest.mark.anyio
async def test_call_model_retries_transient_gateway_status(monkeypatch: pytest.MonkeyPatch) -> None:
    request_counter = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_counter
        request_counter += 1
        if request_counter == 1:
            return httpx.Response(http.HTTPStatus.BAD_GATEWAY, json={"detail": "temporary"})

        return httpx.Response(http.HTTPStatus.OK, json={"result": "ready"})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler), retry_attempts=2)

    response_payload = await client.call_model(MODEL_ID, {"feature": "value"})

    assert response_payload == {"result": "ready"}
    assert request_counter == TWO_REQUESTS


@pytest.mark.anyio
async def test_call_model_retries_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    request_counter = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_counter
        request_counter += 1
        if request_counter == 1:
            raise httpx.ConnectError("connection refused")

        return httpx.Response(http.HTTPStatus.OK, json={"result": "ready"})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler), retry_attempts=2)

    response_payload = await client.call_model(MODEL_ID, {"feature": "value"})

    assert response_payload == {"result": "ready"}
    assert request_counter == TWO_REQUESTS


@pytest.mark.parametrize(
    "status_code",
    [
        http.HTTPStatus.BAD_REQUEST,
        http.HTTPStatus.UNAUTHORIZED,
        http.HTTPStatus.FORBIDDEN,
        http.HTTPStatus.NOT_FOUND,
    ],
)
@pytest.mark.anyio
async def test_call_model_does_not_retry_non_transient_gateway_status(
    monkeypatch: pytest.MonkeyPatch,
    status_code: http.HTTPStatus,
) -> None:
    request_counter = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_counter
        request_counter += 1
        return httpx.Response(status_code, json={"detail": "client error"})

    client = make_gateway_client(monkeypatch, httpx.MockTransport(handler), retry_attempts=3)

    with pytest.raises(GatewayCallError) as exception_info:
        await client.call_model(MODEL_ID, {"feature": "value"})

    assert isinstance(exception_info.value.__cause__, httpx.HTTPStatusError)
    assert request_counter == 1


@pytest.mark.anyio
async def test_call_model_opens_circuit_after_exhausted_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    request_counter = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_counter
        request_counter += 1
        return httpx.Response(http.HTTPStatus.SERVICE_UNAVAILABLE, json={"detail": "unavailable"})

    client = make_gateway_client(
        monkeypatch,
        httpx.MockTransport(handler),
        retry_attempts=2,
        circuit_failure_threshold=2,
    )

    with pytest.raises(GatewayCallError):
        await client.call_model(MODEL_ID, {"feature": "value"})
    with pytest.raises(GatewayCallError):
        await client.call_model(MODEL_ID, {"feature": "value"})
    with pytest.raises(GatewayCallError) as exception_info:
        await client.call_model(MODEL_ID, {"feature": "value"})

    assert isinstance(exception_info.value.__cause__, pybreaker.CircuitBreakerError)
    assert request_counter == FOUR_REQUESTS


@pytest.mark.anyio
async def test_call_model_closes_circuit_after_recovery_success(monkeypatch: pytest.MonkeyPatch) -> None:
    request_counter = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_counter
        request_counter += 1
        if request_counter <= TWO_REQUESTS:
            return httpx.Response(http.HTTPStatus.SERVICE_UNAVAILABLE, json={"detail": "unavailable"})

        return httpx.Response(http.HTTPStatus.OK, json={"result": "recovered"})

    client = make_gateway_client(
        monkeypatch,
        httpx.MockTransport(handler),
        retry_attempts=1,
        circuit_failure_threshold=2,
        circuit_recovery_seconds=0,
    )

    with pytest.raises(GatewayCallError):
        await client.call_model(MODEL_ID, {"feature": "value"})
    with pytest.raises(GatewayCallError):
        await client.call_model(MODEL_ID, {"feature": "value"})

    response_payload = await client.call_model(MODEL_ID, {"feature": "value"})
    next_response_payload = await client.call_model(MODEL_ID, {"feature": "value"})

    assert response_payload == {"result": "recovered"}
    assert next_response_payload == {"result": "recovered"}
    assert request_counter == FOUR_REQUESTS


@pytest.mark.anyio
async def test_call_model_rejects_non_object_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_gateway_client(
        monkeypatch,
        httpx.MockTransport(lambda _request: httpx.Response(http.HTTPStatus.OK, json=[1, 2])),
    )

    with pytest.raises(GatewayCallError) as exception_info:
        await client.call_model(MODEL_ID, {"feature": "value"})

    assert isinstance(exception_info.value.__cause__, GatewayResponseError)
