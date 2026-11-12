# music_scripts

This is a collection of scripts for working with mp3 music files with the purpose of automate the organization of a collection. Current scripts can fill the metadata fields of a file and search the lyrics from [Genius](http://genius.com) to insert them into the file. Because of the sources used to get the music, no functionality is given to fill the track number and the cover picture.

Currently, these scripts only work in Linux and are not guaranteed to work on Windows as these are for my personal use.

## Required modules

These scripts require the Python modules eyed3, lyricsgenius and playwright.

Genius requires a token which is accessed from the enviroment variable GENIUS_TOKEN. In order to get the lyrics, you need to create an API key and set it to that enviroment variable.

Playwright also must be installed with a specific browser after installing the pip package and it stores the profiles in the user folder.
