import dataclasses
import inspect
import typing
from collections.abc import Callable
from typing import Any

import fastapi
from microbootstrap.bootstrappers.fastapi import FastApiBootstrapper

from tropass_sdk.schemas.model_contract_schema import MlModelResponse
from tropass_sdk.settings import ModelServerSettings


@dataclasses.dataclass(kw_only=True)
class ModelServer:
    model_func: Callable[..., Any]
    model_name: str
    model_description: str
    model_version: str
    debug: bool = dataclasses.field(default=False)

    def __post_init__(self) -> None:
        self.settings = ModelServerSettings(
            service_name=self.model_name,
            service_description=self.model_description,
            service_version=self.model_version,
            service_debug=self.debug,
            opentelemetry_container_name=self.model_name,
        )

    def _setup_routes(self) -> fastapi.APIRouter:
        router: typing.Final = fastapi.APIRouter()

        @router.post("/prediction", response_model=MlModelResponse)
        async def predict(data: dict[str, Any]) -> MlModelResponse:
            if inspect.iscoroutinefunction(self.model_func):
                result = await self.model_func(data)
            else:
                result = self.model_func(data)
            return typing.cast("MlModelResponse", result)

        return router

    def build_application(self) -> fastapi.FastAPI:
        fastapi_application: typing.Final = FastApiBootstrapper(self.settings).bootstrap()

        router = self._setup_routes()
        fastapi_application.include_router(router)
        return fastapi_application
