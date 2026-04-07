import json
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright, BrowserContext, Browser

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, moodle_url: str, username: str, password: str, session_file: str):
        self.moodle_url = moodle_url.rstrip("/")
        self.username = username
        self.password = password
        self.session_file = Path(session_file)
        self._playwright = None
        self._browser: Browser | None = None
        self.context: BrowserContext | None = None

    def start(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._load_or_login()

    def stop(self):
        if self.context:
            self.context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def _has_valid_session(self) -> bool:
        if not self.session_file.exists():
            return False
        try:
            with open(self.session_file, "r") as f:
                state = json.load(f)
            if not state.get("cookies"):
                return False
        except (json.JSONDecodeError, IOError):
            return False
        return True

    def _load_or_login(self):
        if self._has_valid_session():
            logger.info("Found existing session, validating...")
            self.context = self._browser.new_context(storage_state=str(self.session_file))
            if self._is_logged_in():
                logger.info("Session is valid.")
                return
            logger.info("Session expired, re-authenticating...")
            self.context.close()

        self.context = self._browser.new_context()
        self._do_login()
        self._save_session()

    def _is_logged_in(self) -> bool:
        page = self.context.new_page()
        try:
            page.goto(f"{self.moodle_url}/my/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            url = page.url
            return "/login/" not in url
        except Exception as e:
            logger.warning(f"Session check failed: {e}")
            return False
        finally:
            page.close()

    def _do_login(self):
        page = self.context.new_page()
        try:
            logger.info(f"Logging in as {self.username}...")
            page.goto(f"{self.moodle_url}/login/index.php", wait_until="domcontentloaded", timeout=30000)
            page.fill("#username", self.username)
            page.fill("#password", self.password)
            page.click("#loginbtn")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(3000)

            if "/login/" in page.url:
                error = page.query_selector("#loginerrormessage, .loginerrors, .alert-danger")
                msg = error.inner_text() if error else "Unknown login error"
                raise RuntimeError(f"Login failed: {msg}")

            logger.info("Login successful.")
        finally:
            page.close()

    def _save_session(self):
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        state = self.context.storage_state()
        with open(self.session_file, "w") as f:
            json.dump(state, f)
        logger.info(f"Session saved to {self.session_file}")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
