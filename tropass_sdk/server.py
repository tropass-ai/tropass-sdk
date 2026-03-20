import dataclasses
import inspect
import typing
from collections.abc import Callable

import fastapi
import structlog
from microbootstrap.bootstrappers.fastapi import FastApiBootstrapper
from starlette.concurrency import run_in_threadpool

from tropass_sdk.schemas import model_contract_schema as schemas
from tropass_sdk.settings import ModelServerSettings


logger = structlog.get_logger(__name__)


@dataclasses.dataclass(kw_only=True)
class ModelServer:
    model_func: Callable[
        [schemas.MODEL_INPUT_TYPE, schemas.COMMON_RESOURCES_TYPE],
        typing.Any,
    ]
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
        self._model_func_is_async = inspect.iscoroutinefunction(self.model_func)

    def _setup_routes(self) -> fastapi.APIRouter:
        router: typing.Final = fastapi.APIRouter()

        @router.post("/prediction", response_model=schemas.MLModelResponseSchema)
        async def predict(data: schemas.MLModelRequestSchema) -> schemas.MLModelResponseSchema:
            try:
                if self._model_func_is_async:
                    result = await self.model_func(data.model_input, data.common_resources)
                else:
                    result = await run_in_threadpool(
                        self.model_func,
                        data.model_input,
                        data.common_resources,
                    )

                return typing.cast("schemas.MLModelResponseSchema", result)
            except Exception:
                logger.exception("Unhandled exception during /prediction")
                raise

        return router

    def build_application(self) -> fastapi.FastAPI:
        fastapi_application: typing.Final = FastApiBootstrapper(self.settings).bootstrap()

        router = self._setup_routes()
        fastapi_application.include_router(router)
        return fastapi_application
