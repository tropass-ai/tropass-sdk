from enum import Enum


class DescriptionType(str, Enum):
    HTML = "html"
    MD = "md"
    PLAIN = "plain"
