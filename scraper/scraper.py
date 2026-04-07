import json
import re
import logging
from datetime import datetime
from pathlib import Path
from playwright.sync_api import BrowserContext, Page

logger = logging.getLogger(__name__)

ACTIVITY_TYPES = {
    "mod/assign": "assignment",
    "mod/quiz": "quiz",
    "mod/forum": "forum",
    "mod/resource": "resource",
    "mod/url": "link",
    "mod/page": "page",
    "mod/folder": "folder",
    "mod/choice": "choice",
    "mod/feedback": "feedback",
    "mod/workshop": "workshop",
    "mod/lesson": "lesson",
    "mod/data": "database",
    "mod/glossary": "glossary",
    "mod/wiki": "wiki",
    "mod/chat": "chat",
    "mod/lti": "external_tool",
}

TIMED_TYPES = {"assignment", "quiz", "forum", "choice", "feedback", "workshop", "lesson"}

TYPE_SUFFIXES_PT = {
    "Tarefa": "assignment",
    "Arquivo": "resource",
    "URL": "link",
    "Fórum": "forum",
    "Questionário": "quiz",
    "Página": "page",
    "Pasta": "folder",
    "Escolha": "choice",
    "Feedback": "feedback",
    "Workshop": "workshop",
    "Lição": "lesson",
    "Base de dados": "database",
    "Glossário": "glossary",
    "Wiki": "wiki",
    "Chat": "chat",
    "Ferramenta externa": "external_tool",
    "Rótulo": "label",
}


def classify_activity(url: str) -> str:
    for pattern, atype in ACTIVITY_TYPES.items():
        if pattern in url:
            return atype
    return "other"


def strip_type_suffix(name: str) -> tuple[str, str | None]:
    """Strip Moodle's type suffix from activity name (e.g. 'My Task Tarefa' -> 'My Task')."""
    for suffix in TYPE_SUFFIXES_PT:
        if name.endswith(f" {suffix}"):
            return name[: -(len(suffix) + 1)].strip(), suffix
    return name, None


MONTHS_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
    "jan": 1, "fev": 2, "mar": 3, "abr": 4,
    "mai": 5, "jun": 6, "jul": 7, "ago": 8,
    "set": 9, "out": 10, "nov": 11, "dez": 12,
}
MONTHS_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_moodle_date(text: str) -> str | None:
    """Parse common Moodle date formats into ISO string."""
    text = text.strip()

    from datetime import timedelta

    relative = text.lower().split(",")[0].strip()
    if relative in ("amanhã", "tomorrow"):
        return (datetime.now() + timedelta(days=1)).replace(hour=23, minute=59).isoformat(timespec="seconds")
    if relative in ("hoje", "today"):
        return datetime.now().replace(hour=23, minute=59).isoformat(timespec="seconds")
    if relative in ("ontem", "yesterday"):
        return (datetime.now() - timedelta(days=1)).replace(hour=23, minute=59).isoformat(timespec="seconds")

    patterns = [
        (r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4}),\s+(\d{1,2}):(\d{2})", "pt_long"),
        (r"(\d{1,2})\s+(\w+)\s+(\d{4}),\s+(\d{1,2}):(\d{2})", "en_long"),
        (r"(\d{1,2})/(\d{1,2})/(\d{4}),?\s+(\d{1,2}):(\d{2})", "numeric"),
        (r"(?:\w+day),?\s+(\d{1,2})\s+(\w+)", "en_weekday"),
        (r"(\d{1,2})\s+de\s+(\w+)", "pt_short"),
    ]

    for pat, fmt in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if not m:
            continue
        try:
            if fmt == "pt_long":
                day, month_name, year, hour, minute = m.groups()
                month = MONTHS_PT.get(month_name.lower())
                if not month:
                    continue
                return datetime(int(year), month, int(day), int(hour), int(minute)).isoformat()
            elif fmt == "en_long":
                day, month_name, year, hour, minute = m.groups()
                month = MONTHS_EN.get(month_name.lower())
                if not month:
                    continue
                return datetime(int(year), month, int(day), int(hour), int(minute)).isoformat()
            elif fmt == "numeric":
                day, mon, year, hour, minute = m.groups()
                return datetime(int(year), int(mon), int(day), int(hour), int(minute)).isoformat()
            elif fmt == "en_weekday":
                day, month_name = m.groups()
                month = MONTHS_EN.get(month_name.lower())
                if not month:
                    continue
                year = datetime.now().year
                return datetime(year, month, int(day), 23, 59).isoformat()
            elif fmt == "pt_short":
                day, month_name = m.groups()
                month = MONTHS_PT.get(month_name.lower())
                if not month:
                    continue
                year = datetime.now().year
                return datetime(year, month, int(day), 23, 59).isoformat()
        except (ValueError, TypeError):
            continue

    return None


class MoodleScraper:
    def __init__(self, context: BrowserContext, moodle_url: str, course_ids: list[str], data_file: str):
        self.context = context
        self.moodle_url = moodle_url.rstrip("/")
        self.course_ids = course_ids
        self.data_file = Path(data_file)

    def scrape_all(self) -> dict:
        logger.info(f"Starting scrape of {len(self.course_ids)} courses...")
        courses = []
        for cid in self.course_ids:
            course = self._scrape_course(cid)
            if course:
                courses.append(course)

        calendar_events = self._scrape_calendar()
        self._merge_calendar_dates(courses, calendar_events)

        data = {
            "last_updated": datetime.now().isoformat(timespec="seconds"),
            "courses": courses,
        }

        self._save(data)
        return data

    def _scrape_course(self, course_id: str) -> dict | None:
        url = f"{self.moodle_url}/course/view.php?id={course_id}"
        page = self.context.new_page()
        try:
            logger.info(f"Scraping course {course_id}...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            course_name = self._extract_course_name(page, course_id)
            activities = self._extract_activities(page)

            for act in activities:
                if act["type"] in TIMED_TYPES and not act.get("due_date"):
                    self._fetch_activity_date(act)

            logger.info(f"  -> {course_name}: {len(activities)} activities found")
            return {
                "id": course_id,
                "name": course_name,
                "url": url,
                "activities": activities,
            }
        except Exception as e:
            logger.error(f"Failed to scrape course {course_id}: {e}")
            return None
        finally:
            page.close()

    @staticmethod
    def _extract_course_name(page: Page, course_id: str) -> str:
        title = page.title()
        for prefix in ("Curso: ", "Course: "):
            if title.startswith(prefix):
                return title[len(prefix):].strip()

        for sel in (".breadcrumb li:last-child", "h1", ".page-header-headings h1", "h1.h2"):
            el = page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if text and text.lower() not in ("", "página inicial"):
                    return text

        return f"Curso {course_id}"

    def _extract_activities(self, page: Page) -> list[dict]:
        activities = []
        seen_urls = set()

        links = page.evaluate("""() => {
            const results = [];
            const courseContent = document.querySelector('#region-main, [role="main"], .course-content')
                                 || document.body;
            const anchors = courseContent.querySelectorAll('a[href*="/mod/"]');
            for (const a of anchors) {
                const href = a.href;
                if (!href || !href.includes('/mod/')) continue;
                // Get visible text, stripping accesshide spans
                const clone = a.cloneNode(true);
                clone.querySelectorAll('.accesshide').forEach(el => el.remove());
                const name = clone.textContent.trim().replace(/\\s+/g, ' ');
                if (!name) continue;
                results.push({ href, name });
            }
            return results;
        }""")

        for item in links:
            href = item["href"]
            name = item["name"]

            if href in seen_urls:
                continue
            seen_urls.add(href)

            atype = classify_activity(href)
            if atype == "label":
                continue

            clean_name, _ = strip_type_suffix(name)
            if not clean_name:
                continue

            activities.append({
                "name": clean_name,
                "type": atype,
                "url": href,
                "due_date": None,
                "status": "unknown",
            })

        return activities

    def _fetch_activity_date(self, activity: dict):
        page = self.context.new_page()
        try:
            page.goto(activity["url"], wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1500)

            date_info = page.evaluate("""() => {
                const body = document.querySelector('#region-main, [role="main"]') || document.body;

                // Strategy 1: assignment status table — look for "Data de entrega" row
                const rows = body.querySelectorAll('table tr, .submissionstatustable tr');
                for (const row of rows) {
                    const cells = row.querySelectorAll('td, th');
                    for (let i = 0; i < cells.length - 1; i++) {
                        const label = cells[i].textContent.trim().toLowerCase();
                        if (label.includes('data de entrega') || label.includes('due date')) {
                            return { source: 'table', text: cells[i + 1].textContent.trim() };
                        }
                    }
                }

                // Strategy 2: quiz closing date — "será fechado" / "closes" / "is due"
                const fullText = body.innerText;
                const quizPatterns = [
                    /será fechado\\s+(.{20,80})/i,
                    /será encerrado\\s+(.{20,80})/i,
                    /closes?\\s+(.{20,80})/i,
                    /is due\\s+(.{20,80})/i,
                    /fecha em\\s+(.{20,80})/i,
                ];
                for (const pat of quizPatterns) {
                    const m = fullText.match(pat);
                    if (m) return { source: 'quiz_text', text: m[1] };
                }

                // Strategy 3: keyword search in full page text
                const keywords = [
                    'Prazo', 'Data de entrega', 'Encerramento', 'Due date',
                    'Close', 'fechado', 'encerrado', 'Deadline',
                ];
                for (const kw of keywords) {
                    const idx = fullText.indexOf(kw);
                    if (idx !== -1) {
                        return { source: 'keyword', text: fullText.substring(idx, idx + 150) };
                    }
                }

                // Strategy 4: broad scan for any Moodle date pattern in the text
                const dateRe = /\\b(\\d{1,2})\\s+(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\\s+(\\d{4}),\\s+\\d{1,2}:\\d{2}/i;
                const broad = fullText.match(dateRe);
                if (broad) return { source: 'broad_en', text: broad[0] };

                const dateRePt = /\\b(\\d{1,2})\\s+de\\s+(janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\\s+de\\s+(\\d{4}),\\s+\\d{1,2}:\\d{2}/i;
                const broadPt = fullText.match(dateRePt);
                if (broadPt) return { source: 'broad_pt', text: broadPt[0] };

                return null;
            }""")

            if date_info and date_info.get("text"):
                parsed = parse_moodle_date(date_info["text"])
                if parsed:
                    activity["due_date"] = parsed
                    logger.debug(f"  Date found for '{activity['name']}' via {date_info['source']}: {parsed}")
                    return
                else:
                    logger.debug(f"  Date text found but unparseable for '{activity['name']}': {date_info['text']}")
            else:
                logger.debug(f"  No date info found on page for '{activity['name']}'")
        except Exception as e:
            logger.debug(f"Could not fetch date for {activity['name']}: {e}")
        finally:
            page.close()

    def _scrape_calendar(self) -> list[dict]:
        """Scrape the upcoming events from the Moodle calendar."""
        events = []
        page = self.context.new_page()
        try:
            logger.info("Scraping Moodle calendar...")
            page.goto(
                f"{self.moodle_url}/calendar/view.php?view=upcoming",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            page.wait_for_timeout(2000)

            raw_events = page.evaluate("""() => {
                const results = [];
                const container = document.querySelector('.eventlist, .maincalendar, #region-main') || document.body;
                const eventDivs = container.querySelectorAll('.event');
                for (const ev of eventDivs) {
                    const nameEl = ev.querySelector('h3 a, .referer a, a[data-action="view-event"]');
                    const courseEl = ev.querySelector('.course a, .referer + .course a, .coursename a');
                    const allLinks = ev.querySelectorAll('a');
                    let dateText = '';
                    for (const a of allLinks) {
                        const text = a.textContent.trim();
                        if (/\\d/.test(text) && /[a-zA-Záéíóúàã]/.test(text) && text.length < 40) {
                            dateText = text;
                        }
                        if (/amanh|today|hoje|tomorrow/i.test(text)) {
                            dateText = text;
                        }
                    }
                    if (!dateText) {
                        const dateEl = ev.querySelector('.date, .col-11');
                        dateText = dateEl ? dateEl.textContent.trim() : '';
                    }
                    const name = nameEl ? nameEl.textContent.trim() : '';
                    const url = nameEl ? nameEl.href : '';
                    const course = courseEl ? courseEl.textContent.trim() : '';
                    if (name) {
                        results.push({ name, url, course, dateText });
                    }
                }
                if (results.length === 0) {
                    const headings = container.querySelectorAll('h3');
                    for (const h of headings) {
                        const a = h.querySelector('a');
                        if (!a) continue;
                        let sibling = h.nextElementSibling;
                        let dateText = '';
                        let course = '';
                        while (sibling && !sibling.matches('h3')) {
                            const text = sibling.textContent.trim();
                            const sLinks = sibling.querySelectorAll('a');
                            for (const sl of sLinks) {
                                const lt = sl.textContent.trim();
                                if (/\\d/.test(lt) && lt.length < 40) dateText = lt;
                                if (/amanh|hoje|tomorrow|today/i.test(lt)) dateText = lt;
                            }
                            sibling = sibling.nextElementSibling;
                        }
                        results.push({
                            name: a.textContent.trim(),
                            url: a.href,
                            course,
                            dateText,
                        });
                    }
                }
                return results;
            }""")

            for ev in raw_events:
                parsed_date = parse_moodle_date(ev["dateText"]) if ev["dateText"] else None
                events.append({
                    "name": ev["name"],
                    "url": ev["url"] or None,
                    "course": ev.get("course", ""),
                    "date": parsed_date,
                    "raw_date": ev["dateText"][:80] if ev["dateText"] else "",
                })
                logger.debug(f"  Calendar event: {ev['name']} | date_text='{ev['dateText']}' | parsed={parsed_date}")

            logger.info(f"  -> {len(events)} calendar events found")
        except Exception as e:
            logger.error(f"Calendar scrape failed: {e}")
        finally:
            page.close()

        return events

    def _merge_calendar_dates(self, courses: list[dict], events: list[dict]):
        """Fill in due_date from calendar events where we couldn't get it from the activity page."""
        for event in events:
            if not event.get("date"):
                continue
            for course in courses:
                for act in course["activities"]:
                    if act["due_date"]:
                        continue
                    if self._fuzzy_match(act["name"], event["name"]):
                        act["due_date"] = event["date"]

    @staticmethod
    def _fuzzy_match(a: str, b: str) -> bool:
        a_clean = re.sub(r"\s+", " ", a.lower().strip())
        b_clean = re.sub(r"\s+", " ", b.lower().strip())
        return a_clean in b_clean or b_clean in a_clean

    def _save(self, data: dict):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.data_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Data saved to {self.data_file}")
