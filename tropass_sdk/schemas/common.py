from enum import Enum


class DescriptionTypeEnum(str, Enum):
    HTML = "html"
    MD = "md"
    PLAIN = "plain"


USER_ID_HEADER = "X-User-ID"
USER_LOCALE_HEADER = "X-User-Locale"
