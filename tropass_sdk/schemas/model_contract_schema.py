"""Contract is used from model to agent."""

import typing

from pydantic import BaseModel

from tropass_sdk.schemas.common import DescriptionType


class ModelSeriesData(BaseModel):
    legend_name: str
    plot_values: list[float]


class ModelPlotData(BaseModel):
    x_axis_values: list[typing.Any]
    series_data: list[ModelSeriesData]


class ModelMediaItem(BaseModel):
    file_name: str
    local_abs_path: str


class ModelPrimaryData(BaseModel):
    plot_data: ModelPlotData
    media: list[ModelMediaItem] | None = None


class ModelDescription(BaseModel):
    content: str
    description_type: DescriptionType


class ModelPanelOutput(BaseModel):
    panel_output_name: str
    panel_type: str
    primary_data: ModelPrimaryData

    description: ModelDescription | None = None
    attachments: list[ModelMediaItem] | None = None
    panel_show_order: int | None = None


class MlModelResponse(BaseModel):
    panel_items: list[ModelPanelOutput]
