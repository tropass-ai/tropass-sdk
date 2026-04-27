import dataclasses
import http
import types
import typing
import uuid

import circuitbreaker  # type: ignore[import-untyped]
import httpx
import stamina

from tropass_sdk.settings import gateway_client_settings


JsonDict: typing.TypeAlias = dict[str, typing.Any]
AsyncCircuitCall: typing.TypeAlias = typing.Callable[[uuid.UUID, JsonDict], typing.Awaitable[JsonDict]]


class GatewayClientError(RuntimeError):
    """Base gateway client exception."""


class GatewayCallError(GatewayClientError):
    """Raised when the gateway model call fails."""


class GatewayCircuitOpenError(GatewayClientError):
    """Raised when the gateway circuit breaker is open."""


class GatewayClientConfigValidationError(GatewayClientError):
    """Raised when gateway client configuration is invalid."""


class GatewayResponseError(GatewayClientError):
    """Raised when the gateway returns an invalid response."""


class GatewayTransientResponseError(GatewayClientError):
    """Raised when the gateway response is retryable."""


@dataclasses.dataclass(kw_only=True, slots=True)
class GatewayClientConfig:
    timeout_seconds: float = dataclasses.field(default=180.0)
    retry_attempts: int = dataclasses.field(default=3)
    retry_timeout_seconds: float = dataclasses.field(default=1)
    retry_wait_exp_base: float = dataclasses.field(default=2.0)
    circuit_failure_threshold: int = dataclasses.field(default=3)
    circuit_recovery_seconds: int = dataclasses.field(default=30)
    circuit_success_threshold: int = dataclasses.field(default=1)


@dataclasses.dataclass(kw_only=True, slots=True)
class GatewayClient:
    gateway_url: str
    gateway_api_token: str
    client_config: GatewayClientConfig = dataclasses.field(default_factory=GatewayClientConfig)
    http_client: httpx.AsyncClient = dataclasses.field(init=False)
    _call_model_with_circuit_breaker: AsyncCircuitCall = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        self._validate_client_config()
        self.gateway_url = self.gateway_url.rstrip("/")
        circuit_breaker = circuitbreaker.CircuitBreaker(
            failure_threshold=self.client_config.circuit_failure_threshold,
            recovery_timeout=self.client_config.circuit_recovery_seconds,
            expected_exception=(
                GatewayResponseError,
                GatewayTransientResponseError,
                httpx.HTTPStatusError,
                httpx.TransportError,
            ),
        )
        circuit_breaker._recovery_timeout = self.client_config.circuit_recovery_seconds  # noqa: SLF001
        self._call_model_with_circuit_breaker = circuit_breaker(self._call_model_with_retries)
        self.http_client = httpx.AsyncClient(timeout=self.client_config.timeout_seconds)

    def _validate_client_config(self) -> None:
        if self.client_config.retry_attempts < 1:
            raise GatewayClientConfigValidationError("retry_attempts must be greater than zero")
        if self.client_config.circuit_failure_threshold < 1:
            raise GatewayClientConfigValidationError("circuit_failure_threshold must be greater than zero")
        if self.client_config.circuit_success_threshold < 1:
            raise GatewayClientConfigValidationError("circuit_success_threshold must be greater than zero")
        if self.client_config.retry_wait_exp_base <= 0:
            raise GatewayClientConfigValidationError("retry_wait_exp_base must be greater than zero")

    async def __aenter__(self) -> "GatewayClient":  # noqa: PYI034
        return self

    async def __aexit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception_value: BaseException | None,
        _traceback: types.TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        await self.http_client.aclose()

    async def call_model(self, model_id: uuid.UUID, model_request_data: JsonDict) -> JsonDict:
        try:
            return await self._call_model_with_circuit_breaker(model_id, model_request_data)
        except (
            GatewayResponseError,
            GatewayTransientResponseError,
            httpx.HTTPStatusError,
            httpx.TransportError,
            circuitbreaker.CircuitBreakerError,
        ) as exception:
            raise GatewayCallError("Gateway model call failed") from exception

    async def _call_model_with_retries(self, model_id: uuid.UUID, model_request_data: JsonDict) -> JsonDict:
        retry_decorator = stamina.retry(
            on=(GatewayTransientResponseError, httpx.TransportError),
            attempts=self.client_config.retry_attempts,
            timeout=self.client_config.retry_timeout_seconds,
            wait_exp_base=self.client_config.retry_wait_exp_base,
        )
        retryable_call = retry_decorator(self._send_call_model_request)
        return await retryable_call(model_id, model_request_data)

    async def _send_call_model_request(self, model_id: uuid.UUID, model_request_data: JsonDict) -> JsonDict:
        response = await self.http_client.post(
            self._build_call_model_url(),
            headers={gateway_client_settings.api_token_header: self.gateway_api_token},
            json={
                "model_id": str(model_id),
                "model_request_data": model_request_data,
            },
        )
        self._raise_for_gateway_status(response)

        try:
            response_payload = response.json()
        except ValueError as exception:
            raise GatewayResponseError("Gateway response is not valid JSON") from exception

        if not isinstance(response_payload, dict):
            raise GatewayResponseError("Gateway response JSON must be an object")

        return typing.cast("JsonDict", response_payload)

    def _build_call_model_url(self) -> str:
        return f"{self.gateway_url}/{gateway_client_settings.call_model_path}"

    def _raise_for_gateway_status(self, response: httpx.Response) -> None:
        if response.status_code < http.HTTPStatus.BAD_REQUEST:
            return

        if (
            response.status_code == http.HTTPStatus.TOO_MANY_REQUESTS
            or response.status_code >= http.HTTPStatus.INTERNAL_SERVER_ERROR
        ):
            raise GatewayTransientResponseError(f"Gateway returned retryable status code {response.status_code}")

        response.raise_for_status()
