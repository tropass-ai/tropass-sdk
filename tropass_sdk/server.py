import dataclasses
import inspect
import typing

import fastapi
import structlog
from microbootstrap.bootstrappers.fastapi import FastApiBootstrapper
from starlette.concurrency import run_in_threadpool

from tropass_sdk.schemas import USER_API_TOKEN_HEADER
from tropass_sdk.schemas import model_contract_schema as schemas
from tropass_sdk.schemas.common import TRAIL_ID_HEADER, USER_ID_HEADER, USER_LOCALE_HEADER
from tropass_sdk.settings import ModelServerSettings


logger = structlog.get_logger(__name__)


SyncModelFuncType = typing.Callable[
    [
        schemas.MODEL_INPUT_TYPE,
        schemas.COMMON_RESOURCES_TYPE,
    ],
    schemas.MLModelResponseSchema,
]
AsyncModelFuncType = typing.Callable[
    [
        schemas.MODEL_INPUT_TYPE,
        schemas.COMMON_RESOURCES_TYPE,
    ],
    typing.Awaitable[schemas.MLModelResponseSchema],
]
ModelFuncType = SyncModelFuncType | AsyncModelFuncType


REQUEST_METADATA_INPUT_KEY = "request_metadata"


def _extract_request_metadata(
    user_identifier: typing.Annotated[
        str | None,
        fastapi.Header(alias=USER_ID_HEADER),
    ] = None,
    user_locale: typing.Annotated[
        str,
        fastapi.Header(alias=USER_LOCALE_HEADER),
    ] = "ru",
    user_api_token: typing.Annotated[
        str | None,
        fastapi.Header(alias=USER_API_TOKEN_HEADER),
    ] = None,
    trail_id: typing.Annotated[
        str | None,
        fastapi.Header(alias=TRAIL_ID_HEADER),
    ] = None,
) -> schemas.MLModelRequestMetadataSchema:
    return schemas.MLModelRequestMetadataSchema.model_validate(
        {
            USER_ID_HEADER: user_identifier,
            USER_LOCALE_HEADER: user_locale,
            USER_API_TOKEN_HEADER: user_api_token,
            TRAIL_ID_HEADER: trail_id,
        },
    )


def _build_model_input_with_request_metadata(
    model_input: schemas.MODEL_INPUT_TYPE,
    request_metadata: schemas.MLModelRequestMetadataSchema,
) -> schemas.MODEL_INPUT_TYPE:
    return {
        **model_input,
        REQUEST_METADATA_INPUT_KEY: request_metadata.model_dump(),
    }


@dataclasses.dataclass(kw_only=True)
class ModelServer:
    model_func: ModelFuncType
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
        async def predict(
            data: schemas.MLModelRequestSchema,
            request_metadata: typing.Annotated[
                schemas.MLModelRequestMetadataSchema,
                fastapi.Depends(_extract_request_metadata),
            ],
        ) -> schemas.MLModelResponseSchema:
            try:
                model_input = _build_model_input_with_request_metadata(data.model_input, request_metadata)
                if self._model_func_is_async:
                    async_model_func = typing.cast("AsyncModelFuncType", self.model_func)
                    return await async_model_func(
                        model_input,
                        data.common_resources,
                    )

                sync_model_func = typing.cast("SyncModelFuncType", self.model_func)
                return await run_in_threadpool(
                    sync_model_func,
                    model_input,
                    data.common_resources,
                )

            except Exception:
                logger.exception("Unhandled exception during /prediction")
                raise

        return router

    def build_application(self) -> fastapi.FastAPI:
        fastapi_application: typing.Final = FastApiBootstrapper(self.settings).bootstrap()

        router = self._setup_routes()
        fastapi_application.include_router(router)
        return fastapi_application
