from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def build_templates(display_timezone: str) -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    tz = ZoneInfo(display_timezone)
    templates.env.globals["asset_version"] = lambda: str(
        (STATIC_DIR / "focus.css").stat().st_mtime_ns
    )

    def localtime(value: datetime | None) -> str:
        if value is None:
            return "never"
        return value.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")

    from careeros.modules.agents.contracts import ArtifactRef
    from careeros.modules.agents.service import mission_label

    templates.env.globals["mission_label"] = mission_label
    templates.env.globals["artifact_href"] = lambda item: ArtifactRef.model_validate(item).href
    templates.env.filters["localtime"] = localtime
    return templates
