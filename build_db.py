#!/usr/bin/env python3
import os
import sys
import sqlite3
import time
import json
from mutagen.id3 import ID3, TXXX, UFID
from mutagen.easyid3 import EasyID3
import musicbrainzngs
from sentence_transformers import SentenceTransformer

musicbrainzngs.set_useragent("MusicResolver", "1.0", "https://yourdomain.com")

model = SentenceTransformer('all-MiniLM-L6-v2')

DEFAULT_DB_PATH = os.path.expanduser("~/smartPlayer/music-resolver.db")

diagnostics = {
    "missing_genre": 0,
    "missing_year": 0,
    "missing_album_type": 0
}

def create_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS tracks (
        file_path TEXT PRIMARY KEY,
        track_mbid TEXT,
        artist_mbid TEXT,
        release_group_mbid TEXT,
        genre TEXT,
        year INTEGER,
        album_type TEXT,
        embedding TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS mbid_cache (
        track_mbid TEXT PRIMARY KEY,
        genre TEXT,
        year INTEGER,
        album_type TEXT
    )
    """)
    return conn

def get_mbids(file_path):
    try:
        id3 = ID3(file_path)
        track_mbid = None
        artist_mbid = None
        release_group_mbid = None

        for ufid in id3.getall("UFID"):
            if ufid.owner == "http://musicbrainz.org":
                track_mbid = ufid.data.decode("ascii")
                break

        for tag in id3.getall("TXXX"):
            desc = tag.desc.lower()
            if desc == "musicbrainz track id" and not track_mbid:
                track_mbid = tag.text[0]
            elif desc == "musicbrainz artist id":
                artist_mbid = tag.text[0]
            elif desc == "musicbrainz release group id":
                release_group_mbid = tag.text[0]

        return track_mbid, artist_mbid, release_group_mbid
    except Exception as e:
        print(f"Failed to read tags: {file_path} ({e})")
        return None, None, None

def lookup_mbid_via_api(artist, title):
    try:
        result = musicbrainzngs.search_recordings(artist=artist, recording=title, limit=1)
        recordings = result.get("recording-list", [])
        if recordings:
            mbid = recordings[0]["id"]
            print(f"Found MBID via API: {mbid} for {artist} - {title}")
            return mbid
    except Exception as e:
        print(f"MBID lookup failed: {e}")
    return None

def embed_mbid_in_file(file_path, track_mbid):
    try:
        id3 = ID3(file_path)
        id3.delall("UFID")
        id3.add(UFID(owner="http://musicbrainz.org", data=track_mbid.encode("ascii")))
        id3.save()
        print(f"Embedded MBID {track_mbid} into {file_path}")
    except Exception as e:
        print(f"Failed to embed MBID into {file_path}: {e}")

def query_musicbrainz(track_mbid, conn, diagnostics):
    import time
    import musicbrainzngs
    import json

    c = conn.cursor()
    c.execute("SELECT genre, year, album_type, recording_json FROM mbid_cache WHERE track_mbid = ?", (track_mbid,))
    row = c.fetchone()
    if row:
        genre, year, album_type, recording_json = row
        if recording_json:
            # Cached full MB data available
            return genre, year, album_type
        # Else fall through to query MB

    try:
        result = musicbrainzngs.get_recording_by_id(
            track_mbid,
            includes=["tags", "releases", "artists"]
        )
        recording = result["recording"]

        tag_counts = {}

        # Recording tags
        for tag in recording.get("tag-list", []):
            count = int(tag.get("count", 1))
            tag_counts[tag["name"]] = tag_counts.get(tag["name"], 0) + count

        # Release-group tags from releases
        for release in recording.get("release-list", []):
            if "release-group" in release:
                for tag in release["release-group"].get("tag-list", []):
                    count = int(tag.get("count", 1))
                    tag_counts[tag["name"]] = tag_counts.get(tag["name"], 0) + count

        # Artist tags fallback
        if not tag_counts:
            for credit in recording.get("artist-credit", []):
                if "artist" in credit:
                    artist_id = credit["artist"]["id"]
                    try:
                        artist_data = musicbrainzngs.get_artist_by_id(artist_id, includes=["tags"])
                        for tag in artist_data["artist"].get("tag-list", []):
                            count = int(tag.get("count", 1))
                            tag_counts[tag["name"]] = tag_counts.get(tag["name"], 0) + count
                    except:
                        pass

        genre = max(tag_counts, key=tag_counts.get) if tag_counts else None

        # YEAR
        years = []
        for release in recording.get("release-list", []):
            date = release.get("date")
            if not date and release.get("release-event-list"):
                date = release["release-event-list"][0].get("date")
            if date:
                try:
                    y = int(date.split("-")[0])
                    years.append(y)
                except:
                    pass
        year = min(years) if years else None

        # ALBUM TYPE
        type_counts = {}
        for release in recording.get("release-list", []):
            if "release-group" in release:
                primary_type = release["release-group"].get("primary-type")
                if primary_type:
                    type_counts[primary_type] = type_counts.get(primary_type, 0) + 1

        album_type = max(type_counts, key=type_counts.get) if type_counts else None

        if not album_type:
            status_counts = {}
            for release in recording.get("release-list", []):
                status = release.get("status")
                if status:
                    status_counts[status] = status_counts.get(status, 0) + 1
            if status_counts:
                album_type = max(status_counts, key=status_counts.get)

        if not album_type:
            for release in recording.get("release-list", []):
                title = release.get("title", "").lower()
                if "compilation" in title or "hits" in title:
                    album_type = "Compilation"
                    break
                if "deluxe" in title:
                    album_type = "Deluxe"
                    break
                if "soundtrack" in title:
                    album_type = "Soundtrack"
                    break
                if "live" in title:
                    album_type = "Live"
                    break

        # Diagnostics
        if not genre:
            diagnostics["missing_genre"] += 1
        if not year:
            diagnostics["missing_year"] += 1
        if not album_type:
            diagnostics["missing_album_type"] += 1

        # Cache
        recording_json = json.dumps(recording, separators=(',', ':'))
        conn.execute("""
            INSERT INTO mbid_cache (track_mbid, genre, year, album_type, recording_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(track_mbid) DO UPDATE SET
                genre = excluded.genre,
                year = excluded.year,
                album_type = excluded.album_type,
                recording_json = excluded.recording_json
        """, (track_mbid, genre, year, album_type, recording_json))
        conn.commit()

        print(f"Resolved: genre={genre or 'None'}, year={year or 'None'}, album_type={album_type or 'None'}")
        time.sleep(1)
        return genre, year, album_type

    except Exception as e:
        print(f"MusicBrainz query failed for {track_mbid}: {e}")
        return None, None, None

def generate_metadata_string(artist, title, genre, year, album_type):
    parts = []
    if artist: parts.append(f"artist: {artist}")
    if title: parts.append(f"title: {title}")
    if genre: parts.append(f"genre: {genre}")
    if year: parts.append(f"year: {year}")
    if album_type: parts.append(f"album_type: {album_type}")
    return "; ".join(parts)

def generate_embedding(metadata_string):
    vector = model.encode(metadata_string)
    return json.dumps(vector.tolist())

def track_already_in_db(conn, file_path):
    c = conn.cursor()
    c.execute("SELECT 1 FROM tracks WHERE file_path = ?", (file_path,))
    return c.fetchone() is not None

def process_file(conn, file_path, diagnostics):
    c = conn.cursor()
    c.execute("""
        SELECT track_mbid, artist_mbid, release_group_mbid, genre, year, album_type
        FROM tracks WHERE file_path = ?
    """, (file_path,))
    row = c.fetchone()

    status_flags = []

    if row:
        track_mbid, artist_mbid, release_group_mbid, genre, year, album_type = row

        if track_mbid and (not genre or not year or not album_type):
            g, y, at = query_musicbrainz(track_mbid, conn, diagnostics)
            updates = {}
            if g and not genre:
                updates["genre"] = g
            if y and not year:
                updates["year"] = y
            if at and not album_type:
                updates["album_type"] = at

            if updates:
                genre = updates.get("genre", genre)
                year = updates.get("year", year)
                album_type = updates.get("album_type", album_type)
                conn.execute("""
                    UPDATE tracks SET genre = ?, year = ?, album_type = ?
                    WHERE file_path = ?
                """, (genre, year, album_type, file_path))
                conn.commit()
                status_flags.append(f"Metadata Updated {updates}")
            else:
                status_flags.append("No new metadata from MusicBrainz")

        else:
            status_flags.append("Existing Complete")

    else:
        # New track
        mbid, artist_mbid, release_group_mbid = get_mbids(file_path)
        genre, year, album_type = query_musicbrainz(mbid, conn, diagnostics) if mbid else (None, None, None)
        conn.execute("""
            INSERT INTO tracks (file_path, track_mbid, artist_mbid, release_group_mbid, genre, year, album_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (file_path, mbid, artist_mbid, release_group_mbid, genre, year, album_type))
        conn.commit()
        status_flags.append(f"New Added genre={genre or 'None'} year={year or 'None'} album_type={album_type or 'None'}")

    print(f"{file_path} | {'; '.join(status_flags)}")

def walk_and_process(music_dir, conn, diagnostics):
    for root, _, files in os.walk(music_dir):
        for file in files:
            if file.lower().endswith(".mp3"):
                process_file(conn, os.path.join(root, file), diagnostics)

def main():
    if len(sys.argv) < 2:
        print("Usage: build_db.py <music_dir> [db_path]")
        sys.exit(1)

    music_dir = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) >= 3 else DEFAULT_DB_PATH

    conn = create_db(db_path)
    walk_and_process(music_dir, conn, diagnostics)

    print("\nDiagnostics summary:")
    print(f"Missing genre: {diagnostics['missing_genre']}")
    print(f"Missing year: {diagnostics['missing_year']}")
    print(f"Missing album_type: {diagnostics['missing_album_type']}")

if __name__ == "__main__":
    main()

