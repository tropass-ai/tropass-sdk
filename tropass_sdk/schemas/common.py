from enum import Enum


class DescriptionTypeEnum(str, Enum):
    HTML = "html"
    MD = "md"
    PLAIN = "plain"


USER_ID_HEADER = "X-User-ID"
USER_LOCALE_HEADER = "X-User-Locale"
USER_API_TOKEN_HEADER = "X-User-Api-Token"  # noqa: S105
TRAIL_ID_HEADER = "X-Trail-ID"
