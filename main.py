"""
MIT License

Copyright (c) 2018 Niko Mätäsaho

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import time
import os
import json
import requests
import re
from urllib.parse import quote

from winamp import Winamp, PlayingStatus
from pypresence import Presence


def update_rpc():
    global previous_track
    global cleared
    trackinfo_raw = w.get_track_title()  # This is in format {tracknum}. {artist} - {track title} - Winamp

    if trackinfo_raw != previous_track:
        previous_track = trackinfo_raw
        trackinfo = trackinfo_raw.split(" - ")[:-1]
        track_pos = w.get_playlist_position()  # Track position in the playlist
        artist = trackinfo[0].strip(f"{track_pos + 1}. ")
        track_name = " - ".join(trackinfo[1:])
        pos, now = w.get_track_status()[1] / 1000, time.time()  # Both are in seconds

        if len(track_name) < 2:
            track_name = f"Track: {track_name}"
        if pos >= 100000:  # Sometimes this is over 4 million if a new track starts
            pos = 0
        start = now - pos

        # Choose between URL-based or custom assets
        if use_direct_urls:
            large_asset_key, large_asset_text = get_album_art_url(artist, track_name)
        elif custom_assets:
            large_asset_key, large_asset_text = get_album_art(track_pos, artist)
        else:
            large_asset_key = "logo"
            large_asset_text = f"Winamp v{winamp_version}"

        rpc.update(details=track_name, state=f"by {artist}", start=int(start), large_image=large_asset_key,
                   small_image=small_asset_key, large_text=large_asset_text, small_text=small_asset_text)
        cleared = False


def get_album_art_url(artist: str, track_name: str):
    """
    Fetch album art URL from Last.FM API based on artist and track information.
    
    :param artist: The artist name
    :param track_name: The track name
    :return: Tuple of (image_url, album_name)
    """
    try:
        # Clean up artist and track names
        artist_clean = clean_string(artist)
        track_clean = clean_string(track_name)
        
        # First try to get album info from track
        album_name, image_url = get_album_from_track(artist_clean, track_clean)
        
        # If no album found from track, try searching for artist's top albums
        if not album_name or not image_url:
            album_name, image_url = get_album_from_artist(artist_clean)
        
        # Use the album name as text, or artist name if no album found
        large_asset_text = album_name if album_name else artist
        
        # Fallback to default if no image found
        if not image_url:
            image_url = fallback_image_url if fallback_image_url else "logo"
            
        if len(large_asset_text) < 2:
            large_asset_text = f"Album: {large_asset_text}"
            
        return image_url, large_asset_text
        
    except Exception as e:
        print(f"Error fetching album art: {e}")
        return fallback_image_url if fallback_image_url else "logo", artist


def clean_string(text: str) -> str:
    """Clean up artist/track names for API calls"""
    # Remove common patterns that might interfere with search
    text = re.sub(r'\(.*?\)', '', text)  # Remove text in parentheses
    text = re.sub(r'\[.*?\]', '', text)  # Remove text in brackets
    text = re.sub(r'\s+', ' ', text)     # Replace multiple spaces with single space
    return text.strip()


def get_album_from_track(artist: str, track: str):
    """Get album info from Last.FM track.getInfo API"""
    try:
        url = "http://ws.audioscrobbler.com/2.0/"
        params = {
            'method': 'track.getInfo',
            'api_key': lastfm_api_key,
            'artist': artist,
            'track': track,
            'format': 'json'
        }
        
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        
        if 'track' in data and 'album' in data['track']:
            album = data['track']['album']
            album_name = album.get('title', '')
            
            # Get the largest available image
            images = album.get('image', [])
            image_url = get_largest_image(images)
            
            return album_name, image_url
            
    except Exception as e:
        print(f"Error getting album from track: {e}")
    
    return None, None


def get_album_from_artist(artist: str):
    """Get top album from artist as fallback"""
    try:
        url = "http://ws.audioscrobbler.com/2.0/"
        params = {
            'method': 'artist.getTopAlbums',
            'api_key': lastfm_api_key,
            'artist': artist,
            'limit': 1,
            'format': 'json'
        }
        
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        
        if 'topalbums' in data and 'album' in data['topalbums']:
            albums = data['topalbums']['album']
            if albums:
                # Get first album (most popular)
                album = albums[0] if isinstance(albums, list) else albums
                album_name = album.get('name', '')
                
                # Get the largest available image
                images = album.get('image', [])
                image_url = get_largest_image(images)
                
                return album_name, image_url
                
    except Exception as e:
        print(f"Error getting top album from artist: {e}")
    
    return None, None


def get_largest_image(images):
    """Extract the largest image URL from Last.FM image array"""
    if not images:
        return None
        
    # Last.FM provides images in different sizes, get the largest one
    size_priority = ['extralarge', 'large', 'medium', 'small']
    
    for size in size_priority:
        for img in images:
            if img.get('size') == size and img.get('#text'):
                return img['#text']
    
    # Fallback to any available image
    for img in images:
        if img.get('#text'):
            return img['#text']
    
    return None


def get_album_art(track_position: int, artist: str):
    """
    Original function for custom Discord assets - kept for backward compatibility
    """
    w.dump_playlist()
    appdata_path = os.getenv("APPDATA")
    tracklist_paths = w.get_playlist(f"{appdata_path}\\Winamp\\Winamp.m3u8")
    track_path = os.path.dirname(tracklist_paths[track_position])
    album_name = os.path.basename(track_path)

    large_asset_text = album_name
    if album_name in album_exceptions:
        album_key = f"{artist} - {album_name}"
    else:
        album_key = album_name
    try:
        large_asset_key = album_asset_keys[album_key]
    except KeyError:
        large_asset_key = default_large_key
        if default_large_text == "winamp version":
            large_asset_text = f"Winamp v{winamp_version}"
        elif default_large_text == "album name":
            large_asset_text = album_name
        else:
            large_asset_text = default_large_text

    if len(large_asset_text) < 2:
        large_asset_text = f"Album: {large_asset_text}"

    return large_asset_key, large_asset_text


# Get the directory where this script was executed
main_path = os.path.dirname(__file__)

# Load settings
try:
    with open(f"{main_path}\\settings.json") as settings_file:
        settings = json.load(settings_file)
except FileNotFoundError:
    settings = {
        "_comment": "Set use_direct_urls to true to fetch album art from Last.FM. Get your API key from https://www.last.fm/api/account/create",
        "client_id": "default",
        "use_direct_urls": True,
        "lastfm_api_key": "YOUR_LASTFM_API_KEY_HERE",
        "default_large_asset_key": "logo",
        "default_large_asset_text": "winamp version",
        "small_asset_key": "playbutton",
        "small_asset_text": "Playing",
        "custom_assets": False,
        "fallback_image_url": ""
    }

    with open(f"{main_path}\\settings.json", "w") as settings_file:
        json.dump(settings, settings_file, indent=2)
    print("Could not find settings.json. Made new settings file with default values.")

client_id = settings["client_id"]
use_direct_urls = settings.get("use_direct_urls", False)
lastfm_api_key = settings.get("lastfm_api_key", "")
fallback_image_url = settings.get("fallback_image_url", "")
default_large_key = settings["default_large_asset_key"]
default_large_text = settings["default_large_asset_text"]
small_asset_key = settings["small_asset_key"]
small_asset_text = settings["small_asset_text"]
custom_assets = settings["custom_assets"]

if client_id == "default":
    client_id = "507484022675603456"

# Validate Last.FM API key if using direct URLs
if use_direct_urls and (not lastfm_api_key or lastfm_api_key == "YOUR_LASTFM_API_KEY_HERE"):
    print("Warning: use_direct_urls is enabled but no valid Last.FM API key provided.")
    print("Get your free API key from: https://www.last.fm/api/account/create")
    print("Falling back to custom assets mode.")
    use_direct_urls = False

w = Winamp()
rpc = Presence(client_id)
rpc.connect()

winamp_version = w.version
previous_track = ""
cleared = False

# Load custom assets files if needed (backward compatibility)
if custom_assets and not use_direct_urls:
    try:
        with open(f"{main_path}\\album_name_exceptions.txt", "r", encoding="utf8") as exceptions_file:
            album_exceptions = exceptions_file.read().splitlines()
    except FileNotFoundError:
        print("Could not find album_name_exceptions.txt. Default assets will be used for duplicate album names.")
        album_exceptions = []
    try:
        with open(f"{main_path}\\album_covers.json", encoding="utf8") as data_file:
            album_asset_keys = json.load(data_file)
    except FileNotFoundError:
        print("Could not find album_covers.json. Default assets will be used.")
        custom_assets = False

print()
if use_direct_urls:
    print("Using direct URLs for album art from Last.FM API.")
else:
    print("Using Discord custom assets for album art.")
print("Winamp status is now being updated to Discord.")
print("To exit, simply press CTRL + C.")

while True:
    status = w.get_playing_status()
    if status == PlayingStatus.Paused or status == PlayingStatus.Stopped and not cleared:
        rpc.clear()
        previous_track = ""
        cleared = True

    elif status == PlayingStatus.Playing:
        update_rpc()
    time.sleep(1)
