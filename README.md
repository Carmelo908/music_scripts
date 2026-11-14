# music_scripts

This is a collection of scripts for working with mp3 music files with the purpose of automate the organization of a collection. Current scripts can fill the metadata fields of a file and search the lyrics from [Genius](http://genius.com) to insert them into the file.

Currently, these scripts only work in Linux and are not guaranteed to work on Windows as these are for my personal use.

## Required modules

These scripts require the following modules installed to work:

```shell
pip install eyed3 lyricsgenius playwright playwright-stealth python-dotenv
```

to use these scripts, you need to copy the [.env.example](./.env.example) file and fill the fields following the instructions in the comments.

Genius requires an API token. In order to get the lyrics, you need to create a GENIUS API key and set it to that enviroment variable.

Playwright also must be installed with a specific browser after installing the pip package and it stores the profiles in the user folder.
It can be Chromium, Firefox or WebKit

```shell
playwright install your-browser
```
