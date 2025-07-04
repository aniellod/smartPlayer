# nexttrack + build_db

A smart music track selection and database system for local music collections.

This project consists of two main applications:

1️⃣ **`build_db.py`** — Builds and maintains a SQLite database of your music files, including:
- Metadata (e.g. genre, year, album type) from MusicBrainz
- Audio embeddings using `sentence-transformers`
- MP3 tag information using `mutagen`

2️⃣ **`nexttrack.py`** — Selects the next best track to play based on:
- Similarity of style (via cosine distance on embeddings)
- Filters out duplicates (same MBID, same path, or near-identical embedding)
- Skips recently played tracks (via your play history database)
- Skips tracks whose title is already in the input file’s name (heuristic)

---

## **Features**
✅ Embedding-based similarity
✅ MusicBrainz metadata enrichment
✅ Heuristic duplicate avoidance
✅ Play history integration
✅ Works on local MP3 collections

---

## **Order of execution**
You should:
1️⃣ Run `build_db.py` first to create or update your database of tracks.
2️⃣ Then use `nexttrack.py` to select the next track based on similarity.

---

## **Requirements**
You will need:
- Python 3.8+
- `sqlite3` installed (the SQLite CLI and dev library)

## 🐍 Virtual environment setup

It is recommended to create a virtual environment to isolate dependencies.

### Create and activate the virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Linux / macOS

or run the setup.sh

### Ubuntu / Debian install:
```bash
sudo apt-get install python3 python3-pip sqlite3 libsqlite3-dev

Install the Python dependencies:

pip install -r requirements.txt

python3 build_db.py /path/to/music/ /path/to/music-resolver.db

example
python3 build_db.py /mnt/music/ ~/smartPlayer/music-resolver.db

