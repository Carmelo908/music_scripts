import os
import sys
import json
import time
import shutil
import subprocess
import dotenv

from pathlib import Path

# ==========================================
# CONFIGURATION
# ==========================================

dotenv.load_dotenv()

MUSIC_FOLDER = Path.home("MUSIC_FOLDER_DIR")

SCRIPT_LYRICS = (
    Path(__file__).parent / "add_lyrics.py"
)

PYTHON_BIN = (
    Path(__file__).parent / "bin" / "python3"
)

def checkProgram(nombre):

    if shutil.which(nombre) is None:
        print(f"ERROR: not found {nombre}.")
        sys.exit(1)


# ==========================================
# READ METADATA
# ==========================================

def getMetadata(file):

    result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-show_entries", "format_tags",
            "-of", "json",
            str(file)
        ],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        return {}

    try:
        data = json.loads(result.stdout)
        return data.get("format", {}).get("tags", {})
    except (json.JSONDecodeError, AttributeError):
        return {}


def getTags(tags, name):

    for key, value in tags.items():
        if key.casefold() == name.casefold():
            return str(value).strip()

    return ""


# ==========================================
# ARTISTS
# ==========================================

def splitArtists(artist):

    return [
        nombre.strip()
        for nombre in artist.split("/")
        if nombre.strip()
    ]


def isColaboration(artist):

    return len(splitArtists(artist)) >= 2


def normalize_artist(artist, all_colaborative):

    artists = splitArtists(artist)

    if not artists:
        return ""

    if all_colaborative:
        return " & ".join(artists)

    return artists[0]


# ==========================================
# TRACK NUMBER
# ==========================================

def getTrackNumber(tags):

    track = getTags(tags, "track")

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

def processSong(
    file,
    gender,
    year,
    artist,
    title,
    number
):

    extension = file.suffix

    newName = (
        f"{number}. {artist} - {title}{extension}"
    )

    destiny = file.parent / newName

    if destiny != file and destiny.exists():
        print(f"ERROR: Ya existe {destiny.name}")
        return None

    tmp = file.with_name(
        file.stem + ".temporal" + extension
    )

    command = [
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
        "-metadata", "comment="
    ]

    if gender:
        command.extend([
            "-metadata", f"genre={gender}"
        ])

    if year:
        command.extend([
            "-metadata", f"date={year}"
        ])

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

def processAlbum(gender, year):

    sourceFolder = Path.cwd()

    files = sorted(
        [
            f for f in sourceFolder.iterdir()
            if f.is_file() and f.suffix.lower() == ".mp3"
        ]
    )

    if not files:
        print("Couldn't find any MP3 file.")
        return

    print(f"\nFound songs: {len(files)}")

    songs = []

    for file in files:

        tags = getMetadata(file)

        artist = getTags(tags, "artist")
        album = getTags(tags, "album")
        title = getTags(tags, "title")

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
            "number": getTrackNumber(tags)
        })

    if not songs:
        print("Not found ant songs with enough metadata.")
        return

    # Check all are part of the same album

    album = songs[0]["album"]

    if any(
        c["album"].casefold() != album.casefold()
        for c in songs
    ):
        print("ERROR: there are songs of different album")
        return

    # Sort for track number

    songs.sort(
        key=lambda c: (
            c["number"],
            c["file"].name.casefold()
        )
    )

    # ======================================
    # DETECT COLABORATIVE PROYECT
    # ======================================

    allColaborative = all(
        isColaboration(c["artist"])
        for c in songs
    )

    print(
        "\nAll the songs are colaborative: ",
        allColaborative
    )

    # ======================================
    # DETERMINE ALBUM ARTIST
    # ======================================

    album_artist = next(
        (
            getTags(c["tags"], "album_artist")
            for c in songs
            if getTags(c["tags"], "album_artist")
        ),
        ""
    )

    if allColaborative:

        # Colaborative proyect:
        # Keep all album artists.

        if album_artist:
            artist_folder = " & ".join(
                splitArtists(album_artist)
            )
        else:
            albumArtists = []

            for s in songs:
                for artist in splitArtists(s["artist"]):
                    if artist.casefold() not in [
                        a.casefold() for a in albumArtists
                    ]:
                        albumArtists.append(artist)

            artist_folder = " & ".join(albumArtists)

    else:

        # Normal album:
        # Keep just the main artist.

        if album_artist:
            artist_folder = splitArtists(album_artist)[0]
        else:
            artist_folder = splitArtists(
                songs[0]["artista"]
            )[0]

    folderName = f"{artist_folder} - {album}"

    print("\nArtista del álbum:", artist_folder)
    print("Álbum:", album)
    print("Carpeta:", folderName)

    # ======================================
    # PROCESS SONGS
    # ======================================

    processed = []

    print("\nProcessing metadata...\n")

    for s in songs:

        artista_final = normalize_artist(
            s["artist"],
            allColaborative
        )

        result = processSong(
            s["archiv"],
            gender,
            year,
            artista_final,
            s["titul"],
            s["numer"]
        )

        if result:
            processed.append(result)

    if not processed:
        print("Couldn't process any s ong")
        return

    # ======================================
    # CREATE ALBUM'S FOLDER
    # ======================================

    albumFolder = sourceFolder / folderName

    albumFolder.mkdir(exist_ok=True)

    print(f"\nOrganizing album: {folderName}")

    for file in processed:

        destiny = albumFolder / file.name

        if destiny.exists():
            print(f"ERROR: already existing {destiny}")
            continue

        shutil.move(str(file), str(destiny))

    # ======================================
    # ADD LYRICS
    # ======================================

    print("\n Adding lyrics...\n")

    if not SCRIPT_LYRICS.is_file():

        print("Couldn't find add_lyrics.py.")

    else:

        python = (
            PYTHON_BIN
            if PYTHON_BIN.is_file()
            else Path(sys.executable)
        )

        for file in sorted(albumFolder.glob("*.mp3")):

            print(f"\nLetra: {file.name}")

            subprocess.run([
                str(python),
                str(SCRIPT_LYRICS),
                str(file)
            ])

            time.sleep(3)

    # ======================================
    # COPY TO MUSIC
    # ======================================

    MUSIC_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )

    musicDestiny = MUSIC_FOLDER / folderName

    sourcePath = albumFolder.resolve()
    destinyPath = musicDestiny.resolve()

    if sourcePath == destinyPath:

        print("\nThe album already on the destiny folder.")

    else:

        try:

            shutil.copytree(
                albumFolder,
                musicDestiny,
                dirs_exist_ok=True
            )

            print("\nAlbum copied succesfully to::")
            print(musicDestiny)

        except OSError as e:

            print("Error while copying the album:", e)

    print("\n================================")
    print("ALBUM PROCESSED")
    print("================================")
    print(f"Artist: {artist_folder}")
    print(f"Álbum: {album}")
    print(f"Folder: {folderName}")
    print(f"Songs: {len(processed)}")
    print("================================")


# ==========================================
# MAIN
# ==========================================

def main():

    if len(sys.argv) < 3:

        print(
            f"Usage: python3 {sys.argv[0]} "
            "'gender' 'year'"
        )

        sys.exit(1)

    checkProgram("ffmpeg")
    checkProgram("ffprobe")

    gender = sys.argv[1]
    year = sys.argv[2]

    processAlbum(gender, year)


if __name__ == "__main__":
    main()
