from enum import Enum


class DescriptionTypeEnum(str, Enum):
    HTML = "html"
    MD = "md"
    PLAIN = "plain"


class InputFieldTypeEnum(str, Enum):
    TEXT = "text"
    DATE = "date"
    DROPDOWN = "dropdown"
    NUMBER = "number"
    CHECKBOX = "checkbox"
    FILE = "file"
    MULTI_SELECT = "multi-select"
