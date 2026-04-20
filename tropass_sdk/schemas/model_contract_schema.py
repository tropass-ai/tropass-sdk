import typing

import pydantic
from pydantic import BaseModel

from tropass_sdk import schemas as tropass_sdk_schemas
from tropass_sdk.schemas.common import DescriptionTypeEnum


class ModelSeriesDataSchema(BaseModel):
    legend_name: str
    plot_values: list[float] = pydantic.Field(default_factory=list)


class ModelPlotDataSchema(BaseModel):
    x_axis_values: list[typing.Any] = pydantic.Field(default_factory=list)
    series_data: list[ModelSeriesDataSchema] = pydantic.Field(default_factory=list)
    x_axis_split_value: str | None = None


class ModelMediaItemSchema(BaseModel):
    file_name: str
    local_abs_path: str


class ModelPrimaryDataSchema(BaseModel):
    plot_data: ModelPlotDataSchema
    media: list[ModelMediaItemSchema] = pydantic.Field(default_factory=list)


class ModelDescriptionSchema(BaseModel):
    content: str
    description_type: DescriptionTypeEnum


class ModelPanelOutputSchema(BaseModel):
    panel_output_name: str
    panel_type: str
    primary_data: ModelPrimaryDataSchema | None = None

    descriptions: list[ModelDescriptionSchema] = pydantic.Field(default_factory=list)
    attachments: list[ModelMediaItemSchema] = pydantic.Field(default_factory=list)
    panel_show_order: int | None = None


class MLModelResponseSchema(BaseModel):
    panel_items: list[ModelPanelOutputSchema] = pydantic.Field(default_factory=list)


MODEL_INPUT_TYPE: typing.TypeAlias = dict[str, list[typing.Any]]
COMMON_RESOURCES_TYPE: typing.TypeAlias = dict[str, str | dict[str, typing.Any]]


class MLModelRequestSchema(BaseModel):
    model_input: MODEL_INPUT_TYPE
    common_resources: COMMON_RESOURCES_TYPE


class MLModelRequestMetadataSchema(BaseModel):
    user_id: str | None = pydantic.Field(default=None, alias=tropass_sdk_schemas.USER_ID_HEADER)
    locale: str = pydantic.Field(default="ru", alias=tropass_sdk_schemas.USER_LOCALE_HEADER)
    user_api_token: str | None = pydantic.Field(default=None, alias=tropass_sdk_schemas.USER_API_TOKEN_HEADER)
