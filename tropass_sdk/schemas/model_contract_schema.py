"""Contract is used from model to agent."""

import typing

from pydantic import BaseModel

from tropass_sdk.schemas.common import DescriptionTypeEnum, InputFieldTypeEnum


class ModelSeriesDataSchema(BaseModel):
    legend_name: str
    plot_values: list[float]


class ModelPlotDataSchema(BaseModel):
    x_axis_values: list[typing.Any]
    series_data: list[ModelSeriesDataSchema]


class ModelMediaItemSchema(BaseModel):
    file_name: str
    local_abs_path: str


class ModelPrimaryDataSchema(BaseModel):
    plot_data: ModelPlotDataSchema
    media: list[ModelMediaItemSchema] | None = None


class ModelDescriptionSchema(BaseModel):
    content: str
    description_type: DescriptionTypeEnum


class ModelPanelOutputSchema(BaseModel):
    panel_output_name: str
    panel_type: str
    primary_data: ModelPrimaryDataSchema

    description: ModelDescriptionSchema | None = None
    attachments: list[ModelMediaItemSchema] | None = None
    panel_show_order: int | None = None


class MLModelResponseSchema(BaseModel):
    panel_items: list[ModelPanelOutputSchema]


class MLModelRequestDataSchema(BaseModel):
    input_field_name: str
    input_field_value: list[typing.Any]
    input_field_type: InputFieldTypeEnum


class MLModelRequestSchema(BaseModel):
    data: list[MLModelRequestDataSchema]
    version: str
    person_id: str
    path_temp_folder: str
