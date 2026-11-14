from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, TypedDict

import dotenv

# ==========================================
# CONFIGURATION
# ==========================================

dotenv.load_dotenv()

SCRIPT_LYRICS: Path = Path(__file__).parent / "add_lyrics.py"
PYTHON_BIN: Path = Path(__file__).parent / "bin" / "python"

Tags = dict[str, str]


class Song(TypedDict):
    file: Path
    artist: str
    album: str
    title: str
    tags: Tags
    number: int


def check_program(nombre: str) -> None:
    if shutil.which(nombre) is None:
        print(f"ERROR: not found {nombre}.")
        sys.exit(1)


# ==========================================
# READ METADATA
# ==========================================

def get_metadata(file: Path) -> Tags:
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-show_entries", "format_tags",
            "-of", "json",
            str(file),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return {}

    try:
        data = json.loads(result.stdout)
        return data.get("format", {}).get("tags", {})
    except (json.JSONDecodeError, AttributeError):
        return {}


def get_tags(tags: Tags, name: str) -> str:
    for key, value in tags.items():
        if key.casefold() == name.casefold():
            return str(value).strip()

    return ""


# ==========================================
# ARTISTS
# ==========================================

def split_artists(artist: str) -> list[str]:
    return [
        nombre.strip()
        for nombre in artist.split("/")
        if nombre.strip()
    ]


def is_colaboration(artist: str) -> bool:
    return len(split_artists(artist)) >= 2


def normalize_artist(artist: str, all_colaborative: bool) -> str:
    artists = split_artists(artist)

    if not artists:
        return ""

    if all_colaborative:
        return " & ".join(artists)

    return artists[0]


# ==========================================
# TRACK NUMBER
# ==========================================

def get_track_number(tags: Tags) -> int:
    track = get_tags(tags, "track")

    if not track:
        return 1

    track = track.split("/")[0].strip()

    try:
        return int(track)
    except ValueError:
        return 1


# ==========================================
# PROCESS METADATA AND RENAME
# ==========================================

def process_song(
    file: Path,
    genre: str,
    year: Optional[int],
    artist: str,
    title: str,
    number: int,
) -> Optional[Path]:
    extension = file.suffix

    new_name = f"{number}. {artist} - {title}{extension}"
    destiny = file.parent / new_name

    if destiny != file and destiny.exists():
        print(f"ERROR: Ya existe {destiny.name}")
        return None

    tmp = file.with_name(file.stem + ".temporal" + extension)

    command: list[str] = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-i", str(file),

        # Keep audio, images and other streams
        "-map", "0",
        "-map_metadata", "0",
        "-c", "copy",

        "-id3v2_version", "3",

        "-metadata", f"artist={artist}",
        "-metadata", f"title={title}",
        "-metadata", f"track={number}",
        "-metadata", "comment=",
    ]

    if genre:
        command.extend(["-metadata", f"genre={genre}"])

    if year is not None:
        command.extend(["-metadata", f"date={year}"])

    command.append(str(tmp))

    result = subprocess.run(command)

    if result.returncode != 0 or not tmp.is_file():
        print(f"ERROR processing {file.name}")
        tmp.unlink(missing_ok=True)
        return None

    os.replace(tmp, file)

    if destiny != file:
        file.rename(destiny)

    print(f"Processed: {destiny.name}")

    return destiny


# ==========================================
# PROCESS ALL SONGS
# ==========================================

def process_album(
    genre: str,
    year: Optional[int],
    source_folder: Path,
    music_folder: Optional[Path],
    add_lyrics: bool,
    lyrics_delay: float,
) -> None:
    files = sorted(
        f for f in source_folder.iterdir()
        if f.is_file() and f.suffix.lower() == ".mp3"
    )

    if not files:
        print("Couldn't find any MP3 file.")
        return

    print(f"\nFound songs: {len(files)}")

    songs: list[Song] = []

    for file in files:
        tags = get_metadata(file)

        artist = get_tags(tags, "artist")
        album = get_tags(tags, "album")
        title = get_tags(tags, "title")

        if not artist or not album:
            print(f"missing metadata fields in {file.name}")
            continue

        if not title:
            title = file.stem

        songs.append({
            "file": file,
            "artist": artist,
            "album": album,
            "title": title,
            "tags": tags,
            "number": get_track_number(tags),
        })

    if not songs:
        print("Not found any songs with enough metadata.")
        return

    # Check all are part of the same album

    album = songs[0]["album"]

    if any(c["album"].casefold() != album.casefold() for c in songs):
        print("ERROR: there are songs of different album")
        return

    # Sort for track number

    songs.sort(key=lambda c: (c["number"], c["file"].name.casefold()))

    # ======================================
    # DETECT COLABORATIVE PROYECT
    # ======================================

    all_colaborative = all(is_colaboration(c["artist"]) for c in songs)

    print("\nAll the songs are colaborative: ", all_colaborative)

    # ======================================
    # DETERMINE ALBUM ARTIST
    # ======================================

    album_artist: str = next(
        (
            get_tags(c["tags"], "album_artist")
            for c in songs
            if get_tags(c["tags"], "album_artist")
        ),
        "",
    )

    if all_colaborative:
        # Colaborative proyect: keep all album artists.
        if album_artist:
            artist_folder = " & ".join(split_artists(album_artist))
        else:
            album_artists: list[str] = []

            for s in songs:
                for artist in split_artists(s["artist"]):
                    if artist.casefold() not in [
                        a.casefold() for a in album_artists
                    ]:
                        album_artists.append(artist)

            artist_folder = " & ".join(album_artists)
    else:
        # Normal album: keep just the main artist.
        if album_artist:
            artist_folder = split_artists(album_artist)[0]
        else:
            artist_folder = split_artists(songs[0]["artist"])[0]

    folder_name = f"{artist_folder} - {album}"

    print("\nArtista del álbum:", artist_folder)
    print("Álbum:", album)
    print("Carpeta:", folder_name)

    # ======================================
    # PROCESS SONGS
    # ======================================

    processed: list[Path] = []

    print("\nProcessing metadata...\n")

    for s in songs:
        artista_final = normalize_artist(s["artist"], all_colaborative)

        result = process_song(
            s["file"],
            genre,
            year,
            artista_final,
            s["title"],
            s["number"],
        )

        if result:
            processed.append(result)

    if not processed:
        print("Couldn't process any song")
        return

    # ======================================
    # CREATE ALBUM'S FOLDER
    # ======================================

    album_folder = source_folder / folder_name
    album_folder.mkdir(exist_ok=True)

    print(f"\nOrganizing album: {folder_name}")

    for file in processed:
        destiny = album_folder / file.name

        if destiny.exists():
            print(f"ERROR: already existing {destiny}")
            continue

        shutil.move(str(file), str(destiny))

    # ======================================
    # ADD LYRICS
    # ======================================

    if add_lyrics:
        print("\n Adding lyrics...\n")

        if not SCRIPT_LYRICS.is_file():
            print("Couldn't find add_lyrics.py.")
        else:
            python = PYTHON_BIN if PYTHON_BIN.is_file() else Path(sys.executable)

            # A single call with the folder: add_lyrics.py processes every MP3
            # and reuses one Playwright instance for the whole album.
            subprocess.run([
                str(python),
                str(SCRIPT_LYRICS),
                "--delay", str(lyrics_delay),
                str(album_folder),
            ])

    # ======================================
    # COPY TO MUSIC
    # ======================================

    if music_folder is not None:
        music_folder.mkdir(parents=True, exist_ok=True)

        music_destiny = music_folder / folder_name

        if album_folder.resolve() == music_destiny.resolve():
            print("\nThe album already on the destiny folder.")
        else:
            try:
                shutil.copytree(album_folder, music_destiny, dirs_exist_ok=True)

                print("\nAlbum copied succesfully to::")
                print(music_destiny)
            except OSError as e:
                print("Error while copying the album:", e)

    print("\n================================")
    print("ALBUM PROCESSED")
    print("================================")
    print(f"Artist: {artist_folder}")
    print(f"Álbum: {album}")
    print(f"Folder: {folder_name}")
    print(f"Songs: {len(processed)}")
    print("================================")


# ==========================================
# MAIN
# ==========================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Normaliza los metadatos de los MP3 de un álbum, los renombra, "
            "los organiza en una carpeta, agrega letras y copia el resultado "
            "a la carpeta de música."
        )
    )

    parser.add_argument("genre", help="Género a escribir en los metadatos")
    parser.add_argument(
        "year",
        type=int,
        nargs="?",
        default=None,
        help="Año del álbum (opcional)",
    )
    parser.add_argument(
        "-s", "--source",
        type=Path,
        default=Path.cwd(),
        help="Carpeta con los MP3 a procesar (por defecto: la actual)",
    )
    parser.add_argument(
        "-m", "--music-folder",
        type=Path,
        default=None,
        help=(
            "Carpeta de música de destino "
            "(por defecto: variable de entorno MUSIC_FOLDER_DIR)"
        ),
    )
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="No copiar el álbum a la carpeta de música",
    )
    parser.add_argument(
        "--no-lyrics",
        action="store_true",
        help="No agregar letras (omite add_lyrics.py)",
    )
    parser.add_argument(
        "--lyrics-delay",
        type=float,
        default=3.0,
        metavar="SEGUNDOS",
        help="Pausa entre canciones al buscar letras (por defecto: 3)",
    )

    return parser


def main() -> None:
    args = build_parser().parse_args()

    check_program("ffmpeg")
    check_program("ffprobe")

    if not args.source.is_dir():
        print(f"ERROR: {args.source} no es una carpeta válida.")
        sys.exit(1)

    music_folder: Optional[Path] = None

    if not args.no_copy:
        music_folder = args.music_folder
        if music_folder is None:
            env_value = os.getenv("MUSIC_FOLDER_DIR")
            if not env_value:
                print(
                    "ERROR: define MUSIC_FOLDER_DIR, use --music-folder "
                    "o --no-copy."
                )
                sys.exit(1)
            music_folder = Path(env_value).expanduser()
        else:
            music_folder = music_folder.expanduser()

    process_album(
        genre=args.genre,
        year=args.year,
        source_folder=args.source.resolve(),
        music_folder=music_folder,
        add_lyrics=not args.no_lyrics,
        lyrics_delay=args.lyrics_delay,
    )


if __name__ == "__main__":
    main()