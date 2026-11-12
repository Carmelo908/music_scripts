import sys
import os
import re
import lyricsgenius
import eyed3

from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ==========================================
# CONFIGURACIÓN
# ==========================================

GENIUS_TOKEN = os.getenv("GENIUS_TOKEN")

if not GENIUS_TOKEN:
    print("ERROR: Falta GENIUS_TOKEN.")
    sys.exit(1)

TIEMPO_ESPERA = 90 * 1000

# Perfil persistente de Firefox
PERFIL_FIREFOX = Path.home() / "Programas" / "scripts" / "perfil_genius"
PERFIL_FIREFOX.mkdir(parents=True, exist_ok=True)

# Preguntar antes de insertar [Instrumental]
MARCAR_INSTRUMENTAL = False

genius = lyricsgenius.Genius(
    GENIUS_TOKEN,
    retries=2,
    remove_section_headers=False
)


# ==========================================
# LIMPIAR LETRA
# ==========================================

def limpiar_letra(letra, titulo):

    letra = re.sub(
        r'^\s*\d+\s+Contributors\s*\n',
        '',
        letra,
        flags=re.IGNORECASE
    )

    letra = re.sub(
        r'^\s*' + re.escape(titulo) + r'\s+Lyrics\s*\n',
        '',
        letra,
        count=1,
        flags=re.IGNORECASE
    )

    letra = re.sub(
        r'\n{3,}',
        '\n\n',
        letra
    )

    return letra.strip()


# ==========================================
# OBTENER LETRA MEDIANTE FIREFOX
# ==========================================

def obtener_letra_firefox(url):

       with sync_playwright() as p:

        context = p.firefox.launch_persistent_context(
            user_data_dir=str(PERFIL_FIREFOX),
            headless=False,
            viewport={"width": 1366, "height": 900}
        )

        try:
            page = context.pages[0] if context.pages else context.new_page()

            print("Abriendo Genius:", url)

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            contenedores = page.locator(
                'div[data-lyrics-container="true"]'
            )

            # Esperar a que Genius muestre la letra.
            # Si aparece una verificación de Cloudflare,
            # podrás resolverla manualmente en Firefox.

            print("Esperando a que Genius esté disponible...")

            limite = 180  # segundos

            for segundo in range(limite):

                if contenedores.count() > 0:

                    partes = contenedores.all_inner_texts()
                    letra = "\n".join(partes).strip()

                    if letra:
                        print("Letra encontrada correctamente.")
                        return letra

                titulo = page.title().lower()

                contenido = page.locator("body").inner_text(
                    timeout=3000
                ).lower()

                if (
                    "just a moment" in titulo
                    or "verify you are human" in contenido
                    or "checking your browser" in contenido
                ):
                    if segundo == 0:
                        print(
                            "Cloudflare está verificando "
                            "el acceso. Si solicita un CAPTCHA, "
                            "resuélvelo manualmente."
                        )

                page.wait_for_timeout(1000)

            raise RuntimeError(
                "No se pudo obtener la letra después de "
                f"{limite} segundos."
            )

        finally:
            context.close()



# ==========================================
# MARCAR COMO INSTRUMENTAL
# ==========================================

def marcar_instrumental(audiofile, titulo):

    if not MARCAR_INSTRUMENTAL:
        print("No se marcará como instrumental.")
        return

    respuesta = input(
        f"¿Añadir [Instrumental] a '{titulo}'? (s/n): "
    ).strip().lower()

    if respuesta == "s":

        audiofile.tag.lyrics.set(
            "[Instrumental]",
            lang=b"eng"
        )

        audiofile.tag.save()

        print("[Instrumental] añadido correctamente.")

    else:
        print("Se ha omitido esta canción.")


# ==========================================
# PROCESAR MP3
# ==========================================

def agregar_letra_a_mp3(archivo_mp3):

    if not os.path.isfile(archivo_mp3):
        print("Archivo inexistente:", archivo_mp3)
        return

    audiofile = eyed3.load(archivo_mp3)

    if audiofile is None:
        print("No se pudo abrir el MP3.")
        return

    if audiofile.tag is None:
        audiofile.initTag()

    titulo = audiofile.tag.title
    artista = audiofile.tag.artist

    if not titulo or not artista:
        print("Falta título o artista.")
        return

    print(f"\nBuscando: {artista} - {titulo}")

    try:

        # Buscar canción en Genius
        resultados = genius.search_songs(
            f"{titulo} {artista}"
        )

        hits = resultados.get("hits", [])

        if not hits:
            print("No se encontraron resultados en Genius.")
            marcar_instrumental(audiofile, titulo)
            return

        # Seleccionar SIEMPRE el primer resultado
        cancion = hits[0]["result"]

        url = cancion["url"]

        print("Primer resultado seleccionado:")
        print(cancion["full_title"])
        print("URL:", url)

        print("Obteniendo letra mediante Firefox...")

        letra = obtener_letra_firefox(url)

        letra = limpiar_letra(
            letra,
            cancion["title"]
        )

        if not letra:
            print("No se obtuvo una letra válida.")
            marcar_instrumental(audiofile, titulo)
            return

        # Guardar letra en MP3
        audiofile.tag.lyrics.set(
            letra,
            lang=b"eng"
        )

        audiofile.tag.save()

        print("¡Letra añadida correctamente!")

    except PlaywrightTimeout:
        print("Tiempo agotado esperando la página.")
        print("No se marcará como instrumental.")

    except Exception as e:
        print("Error:", e)
        print("No se marcará como instrumental por un error.")


# ==========================================
# PROGRAMA PRINCIPAL
# ==========================================

def main():

    if len(sys.argv) < 2:
        print("Uso: python add_lyrics.py archivo.mp3")
        sys.exit(1)

    agregar_letra_a_mp3(sys.argv[1])


if __name__ == "__main__":
    main()

