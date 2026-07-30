import typing

from microbootstrap.settings import FastApiSettings
from pydantic_settings import BaseSettings


class ModelServerSettings(FastApiSettings):
    service_name: str = "model-server"
    service_version: str = "1.0.0"
    service_description: str = "Model server"

    environment_name: str = "local"

    prometheus_metrics_path: str = "/metrics"

    opentelemetry_container_name: str = "model-server"
    opentelemetry_endpoint: str | None = None

    server_host: str = "0.0.0.0"  # noqa: S104
    server_port: int = 8000


class GatewayClientSettings(BaseSettings):
    api_token_header: str = "Authorization"  # noqa: S105
    call_model_path: str = "api/rpc/call-model"
    model_task_path: str = "api/rest/model-tasks"
    model_call_version_header: str = "Tropass-Model-Call-Version"
    model_call_version_value: str = "2"
    idempotency_key_header: str = "Idempotency-Key"


gateway_client_settings: typing.Final = GatewayClientSettings()
