#!/usr/bin/env python3
import sys
import sqlite3
import json
import numpy as np
from datetime import datetime
import re

DISTANCE_THRESHOLD = 0.001  # skip nearly identical matches

def normalize_string(s):
    s = s.lower()
    s = re.sub(r'[^a-z0-9]', '', s)
    return s
    
def cosine_distance(a, b):
    return 1 - np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def load_input_track(conn, file_path):
    c = conn.cursor()
    c.execute("SELECT embedding, track_mbid FROM tracks WHERE file_path = ?", (file_path,))
    row = c.fetchone()
    if not row or not row[0]:
        print(f"Input track not found or missing embedding: {file_path}")
        sys.exit(1)
    emb = np.array(json.loads(row[0]))
    mbid = row[1]

    # Extract title from file path
    title = re.sub(r'\.mp3$', '', file_path.split('/')[-1], flags=re.IGNORECASE)
    return emb, mbid, title

def update_play_info(conn_library, file_path):
    c = conn_library.cursor()

    # Try to update play_count and last_played
    now = datetime.now().isoformat(sep=' ', timespec='seconds')
    c.execute("SELECT play_count FROM tracks WHERE path = ?", (file_path,))
    row = c.fetchone()

    if row:
        play_count = (row[0] or 0) + 1
        c.execute("""
            UPDATE tracks SET play_count = ?, last_played = ?
            WHERE path = ?
        """, (play_count, now, file_path))
        conn_library.commit()
        #print(f"[DEBUG] Updated play_count and last_played for {file_path}")
    #else:
        #print(f"[DEBUG] No row found to update for: {file_path}")

def load_candidates(conn_tracks, conn_library, current_path, current_mbid, input_title):
    c1 = conn_tracks.cursor()
    c2 = conn_library.cursor()

    c1.execute("SELECT file_path, embedding, track_mbid FROM tracks WHERE embedding IS NOT NULL")
    candidates = []
    norm_input_title = normalize_string(input_title)

    for file_path, emb_json, track_mbid in c1.fetchall():
        if file_path == current_path:
            continue
        if current_mbid and track_mbid == current_mbid:
            continue

        # Heuristic skip: if input title appears in candidate path
        filename = file_path.split('/')[-1]
        norm_filename = normalize_string(filename)
        if norm_input_title in norm_filename:
            print(f"[DEBUG] Skipping {file_path} due to title match heuristic")
            continue

        emb = np.array(json.loads(emb_json))

        c2.execute("SELECT last_played FROM tracks WHERE path = ?", (file_path,))
        lib_row = c2.fetchone()
        last_played = lib_row[0] if lib_row else None
        candidates.append((file_path, emb, track_mbid, last_played))
    return candidates


def select_best_match(current_emb, candidates):
    best = None
    best_dist = None
    best_last_played = None

    for file_path, emb, track_mbid, last_played in candidates:
        dist = cosine_distance(current_emb, emb)

        if dist < DISTANCE_THRESHOLD:
            continue  # skip near-duplicates

        # Parse last_played
        if last_played:
            try:
                last_played_dt = datetime.fromisoformat(last_played)
            except Exception:
                last_played_dt = None
        else:
            last_played_dt = None

        if best is None:
            best = (file_path, dist, last_played_dt)
            best_dist = dist
            best_last_played = last_played_dt
        else:
            if dist < best_dist:
                best = (file_path, dist, last_played_dt)
                best_dist = dist
                best_last_played = last_played_dt
            elif abs(dist - best_dist) < 1e-6:
                # If distances are equal, prefer older last_played
                if best_last_played and last_played_dt:
                    if last_played_dt < best_last_played:
                        best = (file_path, dist, last_played_dt)
                        best_last_played = last_played_dt
                elif not best_last_played and last_played_dt:
                    continue  # keep best
                elif best_last_played and not last_played_dt:
                    best = (file_path, dist, last_played_dt)
                    best_last_played = last_played_dt

    return best

def main():
    if len(sys.argv) != 3:
        print("Usage: nexttrack.py <current_file_path> <music_resolver_db_path>")
        sys.exit(1)

    current_path = sys.argv[1]
    resolver_db_path = sys.argv[2]
    library_db_path = "/var/lib/mp3server/music_library.db"

    conn_tracks = sqlite3.connect(resolver_db_path)
    conn_library = sqlite3.connect(library_db_path)

    current_emb, current_mbid, current_title = load_input_track(conn_tracks, current_path)
    candidates = load_candidates(conn_tracks, conn_library, current_path, current_mbid, current_title)

    best = select_best_match(current_emb, candidates)

    if best:
        best_file, best_score, best_last_played = best
        lp_str = best_last_played.isoformat() if best_last_played else "never"
        print(f"{best_file} (cosine distance: {best_score:.4f}, last played: {lp_str})")

        # Attempt update
        update_play_info(conn_library, best_file)
    else:
        print("No suitable match found.")

if __name__ == "__main__":
    main()

