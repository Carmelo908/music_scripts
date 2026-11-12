#!/usr/bin/env python3

import os
import sys
import json
import time
import shutil
import subprocess

from pathlib import Path

# ==========================================
# CONFIGURACIÓN
# ==========================================

CARPETA_MUSICA = Path.home() / "Música"

SCRIPT_LETRAS = (
    Path.home() / "Programas" / "scripts" / "add_lyrics.py"
)

PYTHON_LETRAS = (
    Path.home() / "Programas" / "scripts" / "bin" / "python3"
)

# ==========================================
# COMPROBAR PROGRAMAS
# ==========================================

def comprobar_programa(nombre):

    if shutil.which(nombre) is None:
        print(f"ERROR: No se encuentra {nombre}.")
        sys.exit(1)


# ==========================================
# LEER METADATOS
# ==========================================

def obtener_metadatos(archivo):

    resultado = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-show_entries", "format_tags",
            "-of", "json",
            str(archivo)
        ],
        capture_output=True,
        text=True
    )

    if resultado.returncode != 0:
        return {}

    try:
        datos = json.loads(resultado.stdout)
        return datos.get("format", {}).get("tags", {})
    except (json.JSONDecodeError, AttributeError):
        return {}


def obtener_tag(tags, nombre):

    for clave, valor in tags.items():
        if clave.casefold() == nombre.casefold():
            return str(valor).strip()

    return ""


# ==========================================
# ARTISTAS
# ==========================================

def separar_artistas(artista):

    return [
        nombre.strip()
        for nombre in artista.split("/")
        if nombre.strip()
    ]


def es_colaboracion(artista):

    return len(separar_artistas(artista)) >= 2


def normalizar_artista(artista, todas_colaborativas):

    artistas = separar_artistas(artista)

    if not artistas:
        return ""

    if todas_colaborativas:
        return " & ".join(artistas)

    return artistas[0]


# ==========================================
# NÚMERO DE PISTA
# ==========================================

def obtener_numero_pista(tags):

    pista = obtener_tag(tags, "track")

    if not pista:
        return 1

    pista = pista.split("/")[0].strip()

    try:
        return int(pista)
    except ValueError:
        return 1


# ==========================================
# PROCESAR METADATOS Y RENOMBRAR
# ==========================================

def procesar_cancion(
    archivo,
    genero,
    anio,
    artista,
    titulo,
    numero
):

    extension = archivo.suffix

    nuevo_nombre = (
        f"{numero}. {artista} - {titulo}{extension}"
    )

    destino = archivo.parent / nuevo_nombre

    if destino != archivo and destino.exists():
        print(f"ERROR: Ya existe {destino.name}")
        return None

    temporal = archivo.with_name(
        archivo.stem + ".temporal" + extension
    )

    comando = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-i", str(archivo),

        # Conservar audio, imágenes y demás streams
        "-map", "0",
        "-map_metadata", "0",
        "-c", "copy",

        "-id3v2_version", "3",

        "-metadata", f"artist={artista}",
        "-metadata", f"title={titulo}",
        "-metadata", f"track={numero}",
        "-metadata", "comment="
    ]

    if genero:
        comando.extend([
            "-metadata", f"genre={genero}"
        ])

    if anio:
        comando.extend([
            "-metadata", f"date={anio}"
        ])

    comando.append(str(temporal))

    resultado = subprocess.run(comando)

    if resultado.returncode != 0 or not temporal.is_file():

        print(f"ERROR procesando {archivo.name}")

        temporal.unlink(missing_ok=True)
        return None

    os.replace(temporal, archivo)

    if destino != archivo:
        archivo.rename(destino)

    print(f"Procesado: {destino.name}")

    return destino


# ==========================================
# PROCESAR TODAS LAS CANCIONES
# ==========================================

def procesar_album(genero, anio):

    carpeta_origen = Path.cwd()

    archivos = sorted(
        [
            f for f in carpeta_origen.iterdir()
            if f.is_file() and f.suffix.lower() == ".mp3"
        ]
    )

    if not archivos:
        print("No se encontraron archivos MP3.")
        return

    print(f"\nCanciones encontradas: {len(archivos)}")

    canciones = []

    for archivo in archivos:

        tags = obtener_metadatos(archivo)

        artista = obtener_tag(tags, "artist")
        album = obtener_tag(tags, "album")
        titulo = obtener_tag(tags, "title")

        if not artista or not album:
            print(f"Faltan metadatos en {archivo.name}")
            continue

        if not titulo:
            titulo = archivo.stem

        canciones.append({
            "archivo": archivo,
            "artista": artista,
            "album": album,
            "titulo": titulo,
            "tags": tags,
            "numero": obtener_numero_pista(tags)
        })

    if not canciones:
        print("No hay canciones con metadatos suficientes.")
        return

    # Comprobar que todas pertenecen al mismo álbum

    album = canciones[0]["album"]

    if any(
        c["album"].casefold() != album.casefold()
        for c in canciones
    ):
        print("ERROR: Hay canciones de distintos álbumes.")
        return

    # Ordenar por número de pista

    canciones.sort(
        key=lambda c: (
            c["numero"],
            c["archivo"].name.casefold()
        )
    )

    # ======================================
    # DETECTAR PROYECTO COLABORATIVO
    # ======================================

    todas_colaborativas = all(
        es_colaboracion(c["artista"])
        for c in canciones
    )

    print(
        "\nTodas las canciones son colaborativas:",
        todas_colaborativas
    )

    # ======================================
    # DETERMINAR ARTISTA DEL ÁLBUM
    # ======================================

    album_artist = next(
        (
            obtener_tag(c["tags"], "album_artist")
            for c in canciones
            if obtener_tag(c["tags"], "album_artist")
        ),
        ""
    )

    if todas_colaborativas:

        # Proyecto colaborativo:
        # conservar todos los artistas del álbum.

        if album_artist:
            artista_carpeta = " & ".join(
                separar_artistas(album_artist)
            )
        else:
            artistas_album = []

            for c in canciones:
                for artista in separar_artistas(c["artista"]):
                    if artista.casefold() not in [
                        a.casefold() for a in artistas_album
                    ]:
                        artistas_album.append(artista)

            artista_carpeta = " & ".join(artistas_album)

    else:

        # Álbum normal:
        # conservar solamente el artista principal.

        if album_artist:
            artista_carpeta = separar_artistas(album_artist)[0]
        else:
            artista_carpeta = separar_artistas(
                canciones[0]["artista"]
            )[0]

    nombre_carpeta = f"{artista_carpeta} - {album}"

    print("\nArtista del álbum:", artista_carpeta)
    print("Álbum:", album)
    print("Carpeta:", nombre_carpeta)

    # ======================================
    # PROCESAR CANCIONES
    # ======================================

    procesadas = []

    print("\nProcesando metadatos...\n")

    for c in canciones:

        artista_final = normalizar_artista(
            c["artista"],
            todas_colaborativas
        )

        resultado = procesar_cancion(
            c["archivo"],
            genero,
            anio,
            artista_final,
            c["titulo"],
            c["numero"]
        )

        if resultado:
            procesadas.append(resultado)

    if not procesadas:
        print("No se pudo procesar ninguna canción.")
        return

    # ======================================
    # CREAR CARPETA DEL ÁLBUM
    # ======================================

    carpeta_album = carpeta_origen / nombre_carpeta

    carpeta_album.mkdir(exist_ok=True)

    print(f"\nOrganizando álbum: {nombre_carpeta}")

    for archivo in procesadas:

        destino = carpeta_album / archivo.name

        if destino.exists():
            print(f"ERROR: Ya existe {destino}")
            continue

        shutil.move(str(archivo), str(destino))

    # ======================================
    # AÑADIR LETRAS
    # ======================================

    print("\nAñadiendo letras...\n")

    if not SCRIPT_LETRAS.is_file():

        print("No se encuentra add_lyrics.py.")

    else:

        python = (
            PYTHON_LETRAS
            if PYTHON_LETRAS.is_file()
            else Path(sys.executable)
        )

        for archivo in sorted(carpeta_album.glob("*.mp3")):

            print(f"\nLetra: {archivo.name}")

            subprocess.run([
                str(python),
                str(SCRIPT_LETRAS),
                str(archivo)
            ])

            time.sleep(3)

    # ======================================
    # COPIAR A MÚSICA
    # ======================================

    CARPETA_MUSICA.mkdir(
        parents=True,
        exist_ok=True
    )

    destino_musica = CARPETA_MUSICA / nombre_carpeta

    origen_real = carpeta_album.resolve()
    destino_real = destino_musica.resolve()

    if origen_real == destino_real:

        print("\nEl álbum ya está en Música.")

    else:

        try:

            shutil.copytree(
                carpeta_album,
                destino_musica,
                dirs_exist_ok=True
            )

            print("\nÁlbum copiado correctamente a:")
            print(destino_musica)

        except OSError as e:

            print("Error al copiar el álbum:", e)

    print("\n================================")
    print("ÁLBUM PROCESADO")
    print("================================")
    print(f"Artista: {artista_carpeta}")
    print(f"Álbum: {album}")
    print(f"Carpeta: {nombre_carpeta}")
    print(f"Canciones: {len(procesadas)}")
    print("================================")


# ==========================================
# PROGRAMA PRINCIPAL
# ==========================================

def main():

    if len(sys.argv) < 3:

        print(
            f"Uso: python3 {sys.argv[0]} "
            "'género' 'año'"
        )

        sys.exit(1)

    comprobar_programa("ffmpeg")
    comprobar_programa("ffprobe")

    genero = sys.argv[1]
    anio = sys.argv[2]

    procesar_album(genero, anio)


if __name__ == "__main__":
    main()

