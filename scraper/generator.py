import json
import logging
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)


def _format_last_updated(iso_str: str | None) -> str:
    if not iso_str or iso_str == "N/A":
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y às %H:%M")
    except (ValueError, TypeError):
        return str(iso_str)


class DashboardGenerator:
    def __init__(self, data_file: str, output_file: str, template_dir: str = "templates"):
        self.data_file = Path(data_file)
        self.output_file = Path(output_file)
        self.template_dir = template_dir

    def generate(self):
        logger.info("Generating dashboard...")

        with open(self.data_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        env = Environment(loader=FileSystemLoader(self.template_dir))
        template = env.get_template("dashboard.html.j2")

        data_json = json.dumps(data, ensure_ascii=False)

        html = template.render(
            data=data,
            data_json=data_json,
            last_updated=_format_last_updated(data.get("last_updated")),
        )

        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_file, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"Dashboard written to {self.output_file}")
