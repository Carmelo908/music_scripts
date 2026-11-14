from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from types import TracebackType
from typing import Optional, Sequence

import dotenv
import eyed3
import lyricsgenius
from playwright.sync_api import (
    BrowserContext,
    BrowserType,
    Error as PlaywrightError,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
    sync_playwright,
)

# ==========================================
# CONFIGURATION
# ==========================================

dotenv.load_dotenv()

PLAYWRIGHT_BROWSER: str = os.getenv("PLAYWRIGHT_BROWSER")

DEFAULT_PROFILE_DIR: Path = Path(__file__).parent / "playwright_profile"
DEFAULT_WAIT_SECONDS: int = 180


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)

    if not value:
        return default

    try:
        return int(value)
    except ValueError:
        print(f"WARNING: {name}={value!r} is not a number, using {default}.")
        return default


# ==========================================
# SANITIZE LYRICS
# ==========================================

def sanitize_lyrics(lyrics: str, title: str) -> str:
    lyrics = re.sub(
        r"^\s*\d+\s+Contributors\s*\n",
        "",
        lyrics,
        flags=re.IGNORECASE,
    )

    lyrics = re.sub(
        r"^\s*" + re.escape(title) + r"\s+Lyrics\s*\n",
        "",
        lyrics,
        count=1,
        flags=re.IGNORECASE,
    )

    lyrics = re.sub(r"\n{3,}", "\n\n", lyrics)

    return lyrics.strip()


# ==========================================
# GET LYRICS WITH PLAYWRIGHT
# ==========================================

class GeniusBrowser:
    """
    Single Playwright/Firefox instance shared by the whole script.

    The browser is started lazily on the first request (so nothing is
    opened if no song needs it) and closed when leaving the `with` block.
    """

    def __init__(self, profile_dir: Path, wait_seconds: int) -> None:
        self.profile_dir = profile_dir
        self.wait_seconds = wait_seconds
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None

    def __enter__(self) -> GeniusBrowser:
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()

    def _get_page(self) -> Page:
        if self._context is None:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._playwright = sync_playwright().start()

            browser: BrowserType
            match PLAYWRIGHT_BROWSER:
                case "FIREFOX":
                    browser = self._playwright.firefox
                case "CHROMIUM":
                    browser = self._playwright.chromium
                case "WEBKIT":
                    browser = self._playwright.webkit

            self._context = browser.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=False,
                viewport={"width": 1366, "height": 900},
            )

        pages = self._context.pages
        return pages[0] if pages else self._context.new_page()

    def close(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except PlaywrightError:
                pass
            self._context = None

        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def get_lyrics(self, url: str) -> str:
        page = self._get_page()

        print("Opening Genius:", url)

        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        containers = page.locator('div[data-lyrics-container="true"]')

        print("Waiting for Genius to be avaliable")

        for second in range(self.wait_seconds):

            if page.is_closed():
                raise RuntimeError("The browser page was closed.")

            if containers.count() > 0:
                lyrics = "\n".join(containers.all_inner_texts()).strip()

                if lyrics:
                    print("Lyrics found succesfully.")
                    return lyrics

            try:
                title = page.title().lower()
                content = page.locator("body").inner_text(timeout=3000).lower()
            except PlaywrightError:
                # The page may be navigating (Cloudflare redirect, etc.)
                title = content = ""

            if (
                "just a moment" in title
                or "verify you are human" in content
                or "checking your browser" in content
            ):
                if second == 0:
                    print(
                        "Cloudflare is verifying the access, "
                        "if it request a CAPTCHA resolve it manually."
                    )

            page.wait_for_timeout(1000)

        raise RuntimeError(
            f"Couldn't get the lyrics after {self.wait_seconds} seconds."
        )


# ==========================================
# MARK AS INSTRUMENTAL
# ==========================================

def mark_instrumental(
    audiofile: eyed3.core.AudioFile,
    title: str,
    ask: bool,
) -> None:
    if not ask:
        print("Won't get marked as instrumental")
        return

    answer = input(
        f"¿Add [Instrumental] to '{title}'? (s/n): "
    ).strip().lower()

    if answer == "s":
        audiofile.tag.lyrics.set("[Instrumental]", lang=b"eng")
        audiofile.tag.save()

        print("[Instrumental] added.")
    else:
        print("the song was skipped.")


# ==========================================
# PROCESS MP3
# ==========================================

def insert_lyrics_to_file(
    mp3_file: Path,
    genius: lyricsgenius.Genius,
    browser: GeniusBrowser,
    ask_instrumental: bool,
) -> bool:
    """Returns True if the lyrics were added to the file."""

    if not mp3_file.is_file():
        print("Missing file:", mp3_file)
        return False

    audiofile = eyed3.load(str(mp3_file))

    if audiofile is None:
        print("Couldn't open the MP3.")
        return False

    if audiofile.tag is None:
        audiofile.initTag()

    title: Optional[str] = audiofile.tag.title
    artist: Optional[str] = audiofile.tag.artist

    if not title or not artist:
        print("Missing artist or title.")
        return False

    print(f"\nSearching: {artist} - {title}")

    try:
        results = genius.search_songs(f"{title} {artist}")

        hits = results.get("hits", [])

        if not hits:
            print("No results found on Genius.")
            mark_instrumental(audiofile, title, ask_instrumental)
            return False

        # Select always the first result
        song = hits[0]["result"]
        url: str = song["url"]

        print("First result selected:")
        print(song["full_title"])
        print("URL:", url)

        print("Getting lyrics with Playwright...")

        lyrics = browser.get_lyrics(url)
        lyrics = sanitize_lyrics(lyrics, song["title"])

        if not lyrics:
            print("Couldn't get valid lyrics.")
            mark_instrumental(audiofile, title, ask_instrumental)
            return False

        # Save lyrics in the MP3
        audiofile.tag.lyrics.set(lyrics, lang=b"eng")
        audiofile.tag.save()

        print("Lyrics added successfully!")
        return True

    except PlaywrightTimeout:
        print("Timeout while searching the page.")
        print("Won't be marked as instrumental.")

    except Exception as e:
        print("Error:", e)
        print("Won't be marked as instrumental for a unexpected error.")

    return False


# ==========================================
# COLLECT FILES
# ==========================================

def collect_files(paths: Sequence[Path], recursive: bool) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()

    for raw in paths:
        path = raw.expanduser()
        found: list[Path]

        if path.is_dir():
            candidates = path.rglob("*") if recursive else path.iterdir()
            found = sorted(
                f for f in candidates
                if f.is_file() and f.suffix.lower() == ".mp3"
            )

            if not found:
                print(f"No MP3 files found in {path}")

        elif path.is_file():
            if path.suffix.lower() != ".mp3":
                print(f"Skipping {path} (not an MP3 file)")
                continue

            found = [path]

        else:
            print(f"Skipping {path} (doesn't exist)")
            continue

        for f in found:
            key = f.resolve()

            if key not in seen:
                seen.add(key)
                files.append(f)

    return files


# ==========================================
# MAIN
# ==========================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Busca letras en Genius y las inserta en archivos MP3. "
            "Acepta archivos MP3 y/o directorios (en un directorio se "
            "procesan todos sus MP3)."
        )
    )

    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        metavar="RUTA",
        help="Archivo(s) MP3 y/o directorio(s)",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Buscar MP3 también en los subdirectorios",
    )
    parser.add_argument(
        "--mark-instrumental",
        action="store_true",
        help="Preguntar si se agrega [Instrumental] cuando no hay letra",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=3.0,
        metavar="SEGUNDOS",
        help="Pausa entre canciones (por defecto: 3)",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=None,
        help=(
            "Perfil persistente de Playwright "
            "(por defecto: PLAYWRIGHT_PROFILE_DIR o ./playwright_profile)"
        ),
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=None,
        help=(
            "Segundos de espera por la página de Genius "
            "(por defecto: PLAYWRIGHT_WAIT_SECONDS o 180)"
        ),
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    token = os.getenv("GENIUS_TOKEN")

    if not token:
        print("ERROR: Missing GENIUS_TOKEN.")
        return 1

    profile_dir: Path = args.profile_dir or Path(
        os.getenv("PLAYWRIGHT_PROFILE_DIR") or DEFAULT_PROFILE_DIR
    )
    wait_seconds: int = args.wait_seconds or env_int(
        "PLAYWRIGHT_WAIT_SECONDS", DEFAULT_WAIT_SECONDS
    )

    files = collect_files(args.paths, args.recursive)

    if not files:
        print("No MP3 files to process.")
        return 1

    print(f"MP3 files to process: {len(files)}")

    genius = lyricsgenius.Genius(
        token,
        retries=2,
        remove_section_headers=False,
    )

    ok = 0

    with GeniusBrowser(profile_dir, wait_seconds) as browser:
        for index, file in enumerate(files):
            print(f"\n[{index + 1}/{len(files)}] {file.name}")

            if insert_lyrics_to_file(
                file, genius, browser, args.mark_instrumental
            ):
                ok += 1

            if index < len(files) - 1:
                time.sleep(args.delay)

    print(f"\nLyrics added: {ok}/{len(files)}")

    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())