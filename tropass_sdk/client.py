import asyncio
import dataclasses
import enum
import http
import types
import typing
import uuid

import cantok
import circuitbreaker  # type: ignore[import-untyped]
import httpx
import pydantic
import stamina

from tropass_sdk.settings import gateway_client_settings


JsonDict: typing.TypeAlias = dict[str, typing.Any]
MultipartPart: typing.TypeAlias = tuple[str | None, bytes] | tuple[str | None, bytes, str | None]
MultipartFiles: typing.TypeAlias = list[tuple[str, MultipartPart]]

T = typing.TypeVar("T", "ModelTaskSubmission", "ModelTask")


class GatewayClientError(RuntimeError):
    """Base gateway client exception."""


class GatewayClientConfigValidationError(GatewayClientError):
    """Raised when gateway client configuration is invalid."""


class GatewayCallError(GatewayClientError):
    """Raised when the gateway model call fails."""


class GatewayCircuitOpenError(GatewayCallError):
    """Raised when the submit circuit breaker is open."""


class GatewayTaskTimeoutError(GatewayCallError):
    """Raised when the model task does not complete within deadline."""


class GatewayTaskNotFoundError(GatewayCallError):
    """Raised when the model task is missing or belongs to another user."""


class GatewayIdempotencyConflictError(GatewayCallError):
    """Raised when an idempotency key is reused with a different payload."""


class GatewayResponseError(GatewayClientError):
    """Raised when the gateway returns a malformed response."""


class GatewayTransientResponseError(GatewayClientError):
    """Raised when the gateway response is retryable."""


class TaskStatus(str, enum.Enum):
    DISTRIBUTED = "distributed"
    PROCESSING_STARTED = "processing_started"
    PROCESSING_COMPLETED = "processing_completed"
    PROCESSING_ERROR = "processing_error"


class ModelTaskSubmission(pydantic.BaseModel):
    task_id: str
    status: str


class ModelTaskSubmitRequest(pydantic.BaseModel):
    model_id: uuid.UUID
    model_request_data: JsonDict


class ModelTask(pydantic.BaseModel):
    task_id: str
    status: TaskStatus
    result: JsonDict | None = None
    error_message: str | None = None


class GatewayFile(pydantic.BaseModel):
    file_name: str
    file_content: bytes
    content_type: str | None = None

    def build_multipart_part(self) -> MultipartPart:
        return self.file_name, self.file_content, self.content_type


@dataclasses.dataclass(kw_only=True, slots=True)
class GatewayClientConfig:
    http_timeout_seconds: float = dataclasses.field(default=10.0)
    result_deadline_seconds: float = dataclasses.field(default=1800.0)
    poll_interval_seconds: float = dataclasses.field(default=5.0)
    retry_attempts: int = dataclasses.field(default=3)
    retry_timeout_seconds: float = dataclasses.field(default=30.0)
    retry_wait_exp_base: float = dataclasses.field(default=2.0)
    circuit_failure_threshold: int = dataclasses.field(default=3)
    circuit_recovery_seconds: int = dataclasses.field(default=30)
    circuit_success_threshold: int = dataclasses.field(default=1)


@typing.final
@dataclasses.dataclass(kw_only=True, slots=True)
class GatewayClient:
    gateway_url: str
    gateway_api_token: str
    client_config: GatewayClientConfig = dataclasses.field(default_factory=GatewayClientConfig)
    http_client: httpx.AsyncClient = dataclasses.field(init=False)
    _breaker: circuitbreaker.CircuitBreaker = dataclasses.field(init=False, repr=False)
    _submit_request: typing.Callable[..., typing.Awaitable[ModelTaskSubmission]] = dataclasses.field(
        init=False,
        repr=False,
    )
    _fetch_request: typing.Callable[..., typing.Awaitable[ModelTask]] = dataclasses.field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validate_client_config()
        self.gateway_url = self.gateway_url.rstrip("/")
        self._breaker = circuitbreaker.CircuitBreaker(
            failure_threshold=self.client_config.circuit_failure_threshold,
            recovery_timeout=self.client_config.circuit_recovery_seconds,
            expected_exception=(GatewayResponseError, GatewayTransientResponseError, httpx.TransportError),
        )
        self._breaker._recovery_timeout = self.client_config.circuit_recovery_seconds  # noqa: SLF001
        retry_decorator = stamina.retry(
            on=(GatewayTransientResponseError, httpx.TransportError),
            attempts=self.client_config.retry_attempts,
            timeout=self.client_config.retry_timeout_seconds,
            wait_exp_base=self.client_config.retry_wait_exp_base,
        )
        self._submit_request = self._breaker(retry_decorator(self._make_request))
        self._fetch_request = retry_decorator(self._make_request)
        self.http_client = httpx.AsyncClient(
            base_url=self.gateway_url,
            timeout=self.client_config.http_timeout_seconds,
        )

    def _validate_client_config(self) -> None:
        if self.client_config.retry_attempts < 1:
            raise GatewayClientConfigValidationError("retry_attempts must be greater than zero")
        if self.client_config.circuit_failure_threshold < 1:
            raise GatewayClientConfigValidationError("circuit_failure_threshold must be greater than zero")
        if self.client_config.circuit_success_threshold < 1:
            raise GatewayClientConfigValidationError("circuit_success_threshold must be greater than zero")
        if self.client_config.retry_wait_exp_base <= 0:
            raise GatewayClientConfigValidationError("retry_wait_exp_base must be greater than zero")
        if self.client_config.http_timeout_seconds <= 0:
            raise GatewayClientConfigValidationError("http_timeout_seconds must be greater than zero")
        if self.client_config.result_deadline_seconds < 0:
            raise GatewayClientConfigValidationError("result_deadline_seconds must be non-negative")
        if self.client_config.poll_interval_seconds < 0:
            raise GatewayClientConfigValidationError("poll_interval_seconds must be non-negative")

    async def __aenter__(self) -> "GatewayClient":
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

    async def call_model(
        self,
        model_id: uuid.UUID,
        model_request_data: JsonDict,
        *,
        files: list[GatewayFile] | None = None,
    ) -> JsonDict:
        submission = await self.submit_model_task(model_id, model_request_data, uuid.uuid4(), files=files)
        return await self.wait_for_model_task(uuid.UUID(submission.task_id))

    async def submit_model_task(
        self,
        model_id: uuid.UUID,
        model_request_data: JsonDict,
        idempotency_key: uuid.UUID | None = None,
        *,
        files: list[GatewayFile] | None = None,
    ) -> ModelTaskSubmission:
        return await self._submit_request(
            "POST",
            gateway_client_settings.call_model_path,
            ModelTaskSubmission,
            is_submit=True,
            data={
                gateway_client_settings.model_payload_form_field: ModelTaskSubmitRequest(
                    model_id=model_id,
                    model_request_data=model_request_data,
                ).model_dump_json(),
            },
            files=_build_multipart_files(files),
            idempotency_key=idempotency_key or uuid.uuid4(),
        )

    async def fetch_model_task(self, task_id: uuid.UUID) -> ModelTask:
        return await self._fetch_request(
            "GET",
            f"{gateway_client_settings.model_task_path}/{task_id}",
            ModelTask,
            is_submit=False,
        )

    async def _make_request(  # noqa: PLR0913
        self,
        method: str,
        path: str,
        model_cls: type[T],
        *,
        is_submit: bool,
        data: dict[str, str] | None = None,
        files: MultipartFiles | None = None,
        idempotency_key: uuid.UUID | None = None,
    ) -> T:
        response = await self.http_client.request(
            method,
            path,
            headers=self._build_headers(idempotency_key),
            data=data,
            files=files,
        )
        self._raise_for_status(response, is_submit=is_submit)
        return _parse_response(response, model_cls)

    async def wait_for_model_task(self, task_id: uuid.UUID) -> JsonDict:
        cancellation_token = cantok.TimeoutToken(self.client_config.result_deadline_seconds)
        while not cancellation_token.cancelled:
            task_status = await self.fetch_model_task(task_id)
            if task_status.status is TaskStatus.PROCESSING_COMPLETED:
                if task_status.result is None:
                    raise GatewayResponseError(f"Completed model task {task_id} missing result payload")
                return task_status.result
            if task_status.status is TaskStatus.PROCESSING_ERROR:
                error_message = task_status.error_message or "Model execution failed."
                raise GatewayCallError(f"Model task {task_id} failed: {error_message}")
            await asyncio.sleep(self.client_config.poll_interval_seconds)
        deadline_seconds = self.client_config.result_deadline_seconds
        raise GatewayTaskTimeoutError(f"Model task {task_id} did not complete within {deadline_seconds}s deadline")

    def _build_headers(self, idempotency_key: uuid.UUID | None = None) -> dict[str, str]:
        headers = {
            gateway_client_settings.api_token_header: f"Bearer {self.gateway_api_token}",
            gateway_client_settings.model_call_version_header: gateway_client_settings.model_call_version_value,
        }
        if idempotency_key is not None:
            headers[gateway_client_settings.idempotency_key_header] = str(idempotency_key)
        return headers

    def _raise_for_status(self, response: httpx.Response, *, is_submit: bool) -> None:
        if response.status_code < http.HTTPStatus.BAD_REQUEST:
            return
        if is_submit and response.status_code == http.HTTPStatus.CONFLICT:
            raise GatewayIdempotencyConflictError("Gateway rejected idempotency key reuse with a different payload")
        if not is_submit and response.status_code == http.HTTPStatus.NOT_FOUND:
            raise GatewayTaskNotFoundError("Gateway model task not found or belongs to another user")
        if _is_transient_status(response.status_code):
            raise GatewayTransientResponseError(f"Gateway returned retryable status {response.status_code}")
        raise GatewayCallError(f"Gateway rejected with status {response.status_code}")


def _build_multipart_files(files: list[GatewayFile] | None) -> MultipartFiles:
    return [
        (gateway_client_settings.model_files_form_field, gateway_file.build_multipart_part())
        for gateway_file in files or []
    ]


def _is_transient_status(status_code: int) -> bool:
    return status_code == http.HTTPStatus.TOO_MANY_REQUESTS or status_code >= http.HTTPStatus.INTERNAL_SERVER_ERROR


def _parse_response(response: httpx.Response, model_cls: type[T]) -> T:
    try:
        return model_cls.model_validate(response.json())
    except Exception as exception:
        raise GatewayResponseError("Gateway response is invalid") from exception
