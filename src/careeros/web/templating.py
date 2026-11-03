from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def build_templates(display_timezone: str) -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    tz = ZoneInfo(display_timezone)

    def localtime(value: datetime | None) -> str:
        if value is None:
            return "never"
        return value.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")

    templates.env.filters["localtime"] = localtime
    return templates
