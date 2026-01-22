from microbootstrap.settings import FastApiSettings


class ModelServerSettings(FastApiSettings):
    service_name: str = "model-server"
    service_version: str = "1.0.0"
    service_description: str = "Model server"

    environment_name: str = "local"

    prometheus_metrics_path: str = "/metrics"
    opentelemetry_container_name: str = "model-server"
    server_host: str = "0.0.0.0"  # noqa: S104
    server_port: int = 8000
