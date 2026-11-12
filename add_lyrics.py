import sys
import os
import re
import lyricsgenius
import eyed3

from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ==========================================
# CONFIGURATION
# ==========================================

GENIUS_TOKEN = os.getenv("GENIUS_TOKEN")

if not GENIUS_TOKEN:
    print("ERROR: Missing GENIUS_TOKEN.")
    sys.exit(1)

WAIT_TIME = 90 * 1000


PLAYWRIGHT_PROFILE = Path.home() / "Programas" / "scripts" / "perfil_genius"
PLAYWRIGHT_PROFILE.mkdir(parents=True, exist_ok=True)

# Ask before inserting "[Instrumental]""
MARK_INSTRUMENTAL = False

genius = lyricsgenius.Genius(
    GENIUS_TOKEN,
    retries=2,
    remove_section_headers=False
)


# ==========================================
# SANITIZE LYRICS
# ==========================================

def SanitizeLyrics(lyrics, titulo):

    lyrics = re.sub(
        r'^\s*\d+\s+Contributors\s*\n',
        '',
        lyrics,
        flags=re.IGNORECASE
    )

    lyrics = re.sub(
        r'^\s*' + re.escape(titulo) + r'\s+Lyrics\s*\n',
        '',
        lyrics,
        count=1,
        flags=re.IGNORECASE
    )

    lyrics = re.sub(
        r'\n{3,}',
        '\n\n',
        lyrics
    )

    return lyrics.strip()


# ==========================================
# GET LYRICS WITH PLAYWRIGHT
# ==========================================

def getLyricsPlaywright(url):

       with sync_playwright() as p:

        context = p.firefox.launch_persistent_context(
            user_data_dir=str(PLAYWRIGHT_PROFILE),
            headless=False,
            viewport={"width": 1366, "height": 900}
        )

        try:
            page = context.pages[0] if context.pages else context.new_page()

            print("Opening Genius:", url)

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            containers = page.locator(
                'div[data-lyrics-container="true"]'
            )

            # Esperar a que Genius muestre la letra.
            # Si aparece una verificación de Cloudflare,
            # podrás resolverla manualmente en Firefox.

            print("Waiting for Genius to be avaliable")

            limit = 180  # segundos

            for second in range(limit):

                if containers.count() > 0:

                    parts = containers.all_inner_texts()
                    lyrics = "\n".join(parts).strip()

                    if lyrics:
                        print("Lyrics found succesfully.")
                        return lyrics

                title = page.title().lower()

                content = page.locator("body").inner_text(
                    timeout=3000
                ).lower()

                if (
                    "just a moment" in title
                    or "verify you are human" in content
                    or "checking your browser" in content
                ):
                    if second == 0:
                        print(
                            "Cloudflare is verifying "
                            "the access, if it request a CAPTCHA "
                            "resolve it manually."
                        )

                page.wait_for_timeout(1000)

            raise RuntimeError(
                f"Couldn't get the lyrics after "
                f"{limit} seconds."
            )

        finally:
            context.close()



# ==========================================
# MARk AS INSTRUMENTAL
# ==========================================

def markInstrumental(audiofile, titulo):

    if not MARK_INSTRUMENTAL:
        print("Won't get marked as instrumental")
        return

    answer = input(
        f"¿Add [Instrumental] to '{titulo}'? (s/n): "
    ).strip().lower()

    if answer == "s":

        audiofile.tag.lyrics.set(
            "[Instrumental]",
            lang=b"eng"
        )

        audiofile.tag.save()

        print("[Instrumental] added.")

    else:
        print("the song was skipped.")


# ==========================================
# PROCESS MP3
# ==========================================

def insertLyricsToFile(archivo_mp3):

    if not os.path.isfile(archivo_mp3):
        print("Missing file:", archivo_mp3)
        return

    audiofile = eyed3.load(archivo_mp3)

    if audiofile is None:
        print("Couldn't open the MP3.")
        return

    if audiofile.tag is None:
        audiofile.initTag()

    titulo = audiofile.tag.title
    artista = audiofile.tag.artist

    if not titulo or not artista:
        print("Missing artist or title.")
        return

    print(f"\nSearching: {artista} - {titulo}")

    try:
        resultados = genius.search_songs(
            f"{titulo} {artista}"
        )

        hits = resultados.get("hits", [])

        if not hits:
            print("No se encontraron resultados en Genius.")
            markInstrumental(audiofile, titulo)
            return

        # Select always the first result
        song = hits[0]["result"]

        url = song["url"]

        print("First result selected:")
        print(song["full_title"])
        print("URL:", url)

        print("Getting lyrics with Playwiright...")

        letra = getLyricsPlaywright(url)

        letra = SanitizeLyrics(
            letra,
            song["title"]
        )

        if not letra:
            print("No se obtuvo una letra válida.")
            markInstrumental(audiofile, titulo)
            return

        # Guardar letra en MP3
        audiofile.tag.lyrics.set(
            letra,
            lang=b"eng"
        )

        audiofile.tag.save()

        print("Lyrics added successfully!")

    except PlaywrightTimeout:
        print("Timeout while searching the page.")
        print("Won't be marked as instrumental.")

    except Exception as e:
        print("Error:", e)
        print("Won't be marked as instrumental for a unexpected error.")


# ==========================================
# MAIN
# ==========================================

def main():

    if len(sys.argv) < 2:
        print("Usage: python add_lyrics.py file.mp3")
        sys.exit(1)

    insertLyricsToFile(sys.argv[1])


if __name__ == "__main__":
    main()

