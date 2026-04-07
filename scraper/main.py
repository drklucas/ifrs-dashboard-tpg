import os
import sys
import logging
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from session_manager import SessionManager
from scraper import MoodleScraper
from generator import DashboardGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def _was_updated_today(data_file: Path) -> bool:
    if not data_file.exists():
        return False
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        last_updated = data.get("last_updated")
        if not last_updated:
            return False
        updated_date = datetime.fromisoformat(last_updated).date()
        return updated_date == datetime.now().date()
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        return False


def main():
    load_dotenv()

    moodle_url = os.getenv("MOODLE_URL", "https://moodle.osorio.ifrs.edu.br")
    username = os.getenv("MOODLE_USER")
    password = os.getenv("MOODLE_PASS")
    course_ids = os.getenv("COURSE_IDS", "").split(",")
    session_file = os.getenv("SESSION_FILE", "data/session.json")
    data_file = os.getenv("DATA_FILE", "data/courses.json")
    output_file = os.getenv("OUTPUT_FILE", "output/dashboard.html")
    force_scrape = os.getenv("FORCE_SCRAPE", "0") == "1"

    if not username or not password:
        logger.error("MOODLE_USER and MOODLE_PASS must be set.")
        sys.exit(1)

    course_ids = [cid.strip() for cid in course_ids if cid.strip()]
    if not course_ids:
        logger.error("COURSE_IDS must contain at least one course ID.")
        sys.exit(1)

    logger.info(f"Moodle URL: {moodle_url}")
    logger.info(f"Courses: {course_ids}")

    data_path = Path(data_file)
    should_scrape = force_scrape or not _was_updated_today(data_path)

    if should_scrape:
        if force_scrape:
            logger.info("FORCE_SCRAPE=1, running a fresh scrape.")
        else:
            logger.info("No scrape found for today, running scrape.")

        with SessionManager(moodle_url, username, password, session_file) as session:
            scraper = MoodleScraper(session.context, moodle_url, course_ids, data_file)
            scraper.scrape_all()
    else:
        logger.info("Data already scraped today. Skipping scrape and regenerating dashboard only.")

    generator = DashboardGenerator(data_file, output_file)
    generator.generate()

    logger.info("Done! Dashboard is ready.")


if __name__ == "__main__":
    main()
