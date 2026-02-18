import typing

import pydantic
from pydantic import BaseModel

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
    content: list[str] = pydantic.Field(default_factory=list)
    description_type: DescriptionTypeEnum


class ModelPanelOutputSchema(BaseModel):
    panel_output_name: str
    panel_type: str
    primary_data: ModelPrimaryDataSchema | None = None

    description: ModelDescriptionSchema | None = None
    panel_show_order: int | None = None


class MLModelResponseSchema(BaseModel):
    panel_items: list[ModelPanelOutputSchema] = pydantic.Field(default_factory=list)


class MLModelRequestSchema(BaseModel):
    input_data: dict[str, list[typing.Any]]
    files_directory_path: str
