from flask import Flask, request, redirect, session, render_template, url_for, jsonify
from dotenv import load_dotenv
import os
load_dotenv()
import re
import random
import string
import requests
import logging
import jwt
import json
from supabase import create_client as create_supabase_client
from spotipy.oauth2 import SpotifyOAuth

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "een_willekeurige_lange_string_voor_beveiliging")
app.config['SESSION_COOKIE_NAME'] = "SpotifyLogin"
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600

# ── Spotify ───────────────────────────────────────────────────────────────────
SPOTIPY_CLIENT_ID     = os.environ.get("SPOTIPY_CLIENT_ID",     "523d90f864664cb7b8bde95b200b653e")
SPOTIPY_CLIENT_SECRET = os.environ.get("SPOTIPY_CLIENT_SECRET", "cbd38ca3e0414011869bb300332ba43c")
SCOPE = "user-read-playback-state user-modify-playback-state streaming"

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL         = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY    = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
JWT_SECRET           = os.environ.get("JWT_SECRET", "hitormiss-secret")

# ── Kaartendatabase laden ─────────────────────────────────────────────────────
_tracks_path = os.path.join(os.path.dirname(__file__), 'tracks.json')
try:
    with open(_tracks_path, 'r', encoding='utf-8') as _f:
        TRACKS = json.load(_f)
    logger.info(f"Geladen: {len(TRACKS)} nummers uit tracks.json")
except Exception as _e:
    TRACKS = []
    logger.warning(f"tracks.json niet geladen: {_e}")

_db = None

def get_db():
    global _db
    if _db is None and SUPABASE_URL and SUPABASE_SERVICE_KEY:
        _db = create_supabase_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _db


# ── JWT helpers ───────────────────────────────────────────────────────────────

def make_host_token(room_id, pin):
    return jwt.encode({"role": "host", "room_id": room_id, "pin": pin}, JWT_SECRET, algorithm="HS256")

def make_team_token(team_id, room_id):
    return jwt.encode({"role": "player", "team_id": team_id, "room_id": room_id}, JWT_SECRET, algorithm="HS256")

def verify_token(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return None


# ── Spotify helpers ───────────────────────────────────────────────────────────

def get_redirect_uri():
    env_uri = os.environ.get("SPOTIPY_REDIRECT_URI")
    if env_uri:
        return env_uri
    host = request.host.replace('127.0.0.1', 'localhost')
    return f"https://{host}/callback"

def get_spotify_oauth(redirect_uri):
    return SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=redirect_uri,
        scope=SCOPE,
        show_dialog=False,
        cache_path=None,
    )

def get_token():
    token_info = session.get("token_info")
    if not token_info or "access_token" not in token_info:
        return None
    redirect_uri = session.get("redirect_uri", "http://localhost:5000/callback")
    sp_oauth = get_spotify_oauth(redirect_uri)
    if sp_oauth.is_token_expired(token_info):
        try:
            token_info = sp_oauth.refresh_access_token(token_info["refresh_token"])
            session["token_info"] = token_info
        except Exception as e:
            logger.error(f"Token vernieuwen mislukt: {e}")
            session.pop("token_info", None)
            return None
    return token_info["access_token"]

def extract_track_id(text):
    text = text.strip()
    m = re.search(r'spotify:track:([A-Za-z0-9]+)', text)
    if m:
        return m.group(1)
    m = re.search(r'open\.spotify\.com/track/([A-Za-z0-9]+)', text)
    if m:
        return m.group(1)
    if re.match(r'^[A-Za-z0-9]{22}$', text):
        return text
    return None

def extract_playlist_id(text):
    text = text.strip()
    m = re.search(r'open\.spotify\.com/playlist/([A-Za-z0-9]+)', text)
    if m:
        return m.group(1)
    m = re.search(r'spotify:playlist:([A-Za-z0-9]+)', text)
    if m:
        return m.group(1)
    if re.match(r'^[A-Za-z0-9]{22}$', text):
        return text
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Spotify OAuth routes
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def home():
    logged_in = bool(session.get("token_info"))
    return render_template("home.html", logged_in=logged_in)

@app.route('/login')
def login():
    redirect_uri = get_redirect_uri()
    session['redirect_uri'] = redirect_uri
    return redirect(get_spotify_oauth(redirect_uri).get_authorize_url())

@app.route('/callback')
def callback():
    error = request.args.get('error')
    if error:
        return render_template("error.html", message="Spotify login geweigerd.", error_details=error)
    code = request.args.get('code')
    if not code:
        return render_template("error.html", message="Geen autorisatiecode ontvangen van Spotify.")
    redirect_uri = session.get('redirect_uri', get_redirect_uri())
    try:
        token_info = get_spotify_oauth(redirect_uri).get_access_token(code, as_dict=True)
        session["token_info"] = token_info
    except Exception as e:
        return render_template("error.html", message="Inloggen mislukt.", error_details=str(e))
    return redirect(url_for("lobby"))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for("home"))


# ══════════════════════════════════════════════════════════════════════════════
# Single-player modus
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/scan')
def scan_page():
    if not get_token():
        return redirect(url_for("login"))
    error_map = {
        "invalid_qr": "Ongeldige QR-code. Scan een Hitster kaart.",
        "track_not_found": "Nummer niet gevonden op Spotify.",
        "no_track": "Geen track gevonden in de QR-code.",
    }
    return render_template("scan.html", error_msg=error_map.get(request.args.get("error")))

@app.route('/process_scan')
def process_scan():
    qr_text = request.args.get("track", "").strip()
    if not qr_text:
        return redirect(url_for("scan_page", error="no_track"))
    track_id = extract_track_id(qr_text)
    if not track_id:
        return redirect(url_for("scan_page", error="invalid_qr"))
    return redirect(url_for("play", track_id=track_id))

@app.route('/play/<track_id>')
def play(track_id):
    access_token = get_token()
    if not access_token:
        return redirect(url_for("login"))
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(f"https://api.spotify.com/v1/tracks/{track_id}", headers=headers)
    if resp.status_code == 401:
        session.pop("token_info", None)
        return redirect(url_for("login"))
    if resp.status_code != 200:
        return redirect(url_for("scan_page", error="track_not_found"))
    track = resp.json()
    images = track["album"]["images"]
    return render_template(
        "play.html",
        track_id=track_id,
        track_name=track["name"],
        artist_name=", ".join(a["name"] for a in track["artists"]),
        year=track["album"]["release_date"][:4],
        album_art=images[0]["url"] if images else None,
        access_token=access_token,
    )

@app.route('/api/play', methods=['POST'])
def api_play():
    access_token = get_token()
    if not access_token:
        return jsonify({"error": "not_authenticated"}), 401
    data = request.get_json() or {}
    track_id = data.get("track_id")
    device_id = data.get("device_id")
    if not track_id:
        return jsonify({"error": "no track_id"}), 400
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    if not device_id:
        dev_resp = requests.get("https://api.spotify.com/v1/me/player/devices", headers=headers)
        if dev_resp.status_code == 200:
            for d in dev_resp.json().get("devices", []):
                if "phone" in d["type"].lower():
                    device_id = d["id"]
                    break
        if not device_id:
            return jsonify({"error": "no_device"}), 404
    play_resp = requests.put(
        f"https://api.spotify.com/v1/me/player/play?device_id={device_id}",
        headers=headers,
        json={"uris": [f"spotify:track:{track_id}"], "position_ms": 0},
    )
    if play_resp.status_code in [204, 202]:
        return jsonify({"status": "playing"})
    return jsonify({"error": "playback_failed", "details": play_resp.text}), 500

@app.route('/api/pause', methods=['POST'])
def api_pause():
    access_token = get_token()
    if not access_token:
        return jsonify({"error": "not_authenticated"}), 401
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    resp = requests.put("https://api.spotify.com/v1/me/player/pause", headers=headers)
    if resp.status_code in [200, 204]:
        return jsonify({"status": "paused"})
    return jsonify({"error": "pause_failed", "details": resp.text}), 500


# ══════════════════════════════════════════════════════════════════════════════
# Multiplayer — Lobby & Rooms
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/lobby')
def lobby():
    if not get_token():
        return redirect(url_for("login"))
    return render_template("lobby.html",
                           supabase_url=SUPABASE_URL,
                           supabase_anon_key=SUPABASE_ANON_KEY)

@app.route('/room/create', methods=['POST'])
def room_create():
    if not get_token():
        return jsonify({"error": "not_authenticated"}), 401
    data = request.get_json() or {}
    deck_mode      = data.get("deck_mode", "digital")
    playlist_id    = extract_playlist_id(data.get("playlist_url", "")) or ""
    host_team_name = data.get("host_team_name", "Host").strip() or "Host"

    pin = ''.join(random.choices(string.digits, k=6))
    db  = get_db()

    try:
        room = db.table("rooms").insert({
            "pin": pin, "deck_mode": deck_mode, "playlist_id": playlist_id
        }).execute()
        room_id = room.data[0]["id"]

        db.table("game_state").insert({
            "room_id": room_id, "phase": "idle"
        }).execute()

        # Host doet ook mee als team
        team = db.table("teams").insert({
            "room_id": room_id, "name": host_team_name
        }).execute()
        team_id = team.data[0]["id"]
    except Exception as e:
        logger.error(f"Room create error: {e}")
        return jsonify({"error": "Kamer aanmaken mislukt", "details": str(e)}), 500

    token      = make_host_token(room_id, pin)
    team_token = make_team_token(team_id, room_id)
    return jsonify({"pin": pin, "room_id": room_id, "token": token,
                    "team_id": team_id, "team_token": team_token})

@app.route('/room/join', methods=['POST'])
def room_join():
    data = request.get_json() or {}
    pin       = data.get("pin", "").strip()
    team_name = data.get("team_name", "").strip()
    if not pin or not team_name:
        return jsonify({"error": "PIN en teamnaam zijn verplicht"}), 400

    db = get_db()
    try:
        rooms = db.table("rooms").select("*").eq("pin", pin).eq("status", "waiting").execute()
        if not rooms.data:
            return jsonify({"error": "Kamer niet gevonden of spel al gestart"}), 404
        room    = rooms.data[0]
        room_id = room["id"]

        team = db.table("teams").insert({"room_id": room_id, "name": team_name}).execute()
        team = team.data[0]
    except Exception as e:
        logger.error(f"Room join error: {e}")
        return jsonify({"error": "Meedoen mislukt", "details": str(e)}), 500

    token = make_team_token(team["id"], room_id)
    return jsonify({"team_id": team["id"], "room_id": room_id,
                    "team_name": team_name, "token": token,
                    "deck_mode": room["deck_mode"]})

@app.route('/host/<pin>')
def host_page(pin):
    if not get_token():
        return redirect(url_for("login"))
    return render_template("host.html", pin=pin,
                           supabase_url=SUPABASE_URL,
                           supabase_anon_key=SUPABASE_ANON_KEY,
                           access_token=get_token())

@app.route('/controller/<pin>')
def controller_page(pin):
    return render_template("controller.html", pin=pin,
                           supabase_url=SUPABASE_URL,
                           supabase_anon_key=SUPABASE_ANON_KEY)


# ══════════════════════════════════════════════════════════════════════════════
# Multiplayer — Game flow
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/game/start', methods=['POST'])
def game_start():
    data   = request.get_json() or {}
    claims = verify_token(data.get("token"))
    if not claims or claims.get("role") != "host":
        return jsonify({"error": "Geen toegang"}), 403
    room_id = claims["room_id"]
    db = get_db()

    try:
        teams = db.table("teams").select("*").eq("room_id", room_id).order("created_at").execute()
        if not teams.data:
            return jsonify({"error": "Geen teams gevonden"}), 400

        db.table("rooms").update({"status": "playing"}).eq("id", room_id).execute()
        db.table("game_state").update({
            "current_team_id": teams.data[0]["id"],
            "phase": "idle",
            "round_number": 1,
        }).eq("room_id", room_id).execute()
    except Exception as e:
        logger.error(f"Game start error: {e}")
        return jsonify({"error": "Start mislukt", "details": str(e)}), 500

    return jsonify({"status": "started", "first_team": teams.data[0]["name"]})


@app.route('/game/draw', methods=['POST'])
def game_draw():
    data   = request.get_json() or {}
    claims = verify_token(data.get("token"))
    if not claims or claims.get("role") != "host":
        return jsonify({"error": "Geen toegang"}), 403
    room_id = claims["room_id"]

    if not TRACKS:
        return jsonify({"error": "Geen nummers beschikbaar (tracks.json ontbreekt)"}), 500

    access_token = get_token()
    if not access_token:
        return jsonify({"error": "Spotify niet verbonden"}), 401

    # Trek een willekeurig nummer uit de kaartendatabase
    card = random.choice(TRACKS)
    artist     = card["artist"]
    track_name = card["track"]
    year       = card["year"]

    # Zoek het nummer op Spotify voor track_id en albumhoes
    headers = {"Authorization": f"Bearer {access_token}"}
    search_resp = requests.get(
        "https://api.spotify.com/v1/search",
        headers=headers,
        params={"q": f"artist:{artist} track:{track_name}", "type": "track", "limit": 1},
    )

    track_id  = None
    album_art = None
    if search_resp.status_code == 200:
        items = search_resp.json().get("tracks", {}).get("items", [])
        if items:
            track_id  = items[0]["id"]
            images    = items[0]["album"]["images"]
            album_art = images[0]["url"] if images else None

    if not track_id:
        # Bredere zoekopdracht als exacte match mislukt
        search_resp2 = requests.get(
            "https://api.spotify.com/v1/search",
            headers=headers,
            params={"q": f"{artist} {track_name}", "type": "track", "limit": 1},
        )
        if search_resp2.status_code == 200:
            items2 = search_resp2.json().get("tracks", {}).get("items", [])
            if items2:
                track_id  = items2[0]["id"]
                images    = items2[0]["album"]["images"]
                album_art = images[0]["url"] if images else None

    if not track_id:
        return jsonify({"error": f"Nummer niet gevonden op Spotify: {artist} – {track_name}"}), 404

    active_track = {
        "track_id":  track_id,
        "name":      track_name,
        "artist":    artist,
        "year":      year,
        "album_art": album_art,
    }

    db = get_db()
    try:
        db.table("game_state").update({
            "active_track": active_track,
            "phase": "placing",
        }).eq("room_id", room_id).execute()
    except Exception as e:
        return jsonify({"error": "Game state updaten mislukt", "details": str(e)}), 500

    return jsonify({"track": active_track})


@app.route('/game/place', methods=['POST'])
def game_place():
    data   = request.get_json() or {}
    claims = verify_token(data.get("token"))
    if not claims or claims.get("role") != "player":
        return jsonify({"error": "Geen toegang"}), 403

    team_id  = claims["team_id"]
    room_id  = claims["room_id"]
    position = data.get("position")

    if position is None:
        return jsonify({"error": "Geen positie opgegeven"}), 400

    db = get_db()
    try:
        state = db.table("game_state").select("*").eq("room_id", room_id).execute()
        if not state.data:
            return jsonify({"error": "Game state niet gevonden"}), 404
        state = state.data[0]

        if state["current_team_id"] != team_id:
            return jsonify({"error": "Niet jouw beurt"}), 403
        if state["phase"] != "placing":
            return jsonify({"error": "Geen kaart actief"}), 400

        year         = state["active_track"]["year"]
        active_track = state["active_track"]

        timeline = db.table("timeline_cards").select("*").eq("team_id", team_id).order("position").execute()
        timeline = timeline.data

        # Validate placement
        correct = True
        if position > 0 and len(timeline) >= position and timeline[position - 1]["year"] > year:
            correct = False
        if position < len(timeline) and timeline[position]["year"] < year:
            correct = False

        if correct:
            for card in timeline[position:]:
                db.table("timeline_cards").update({"position": card["position"] + 1}).eq("id", card["id"]).execute()

            db.table("timeline_cards").insert({
                "team_id":     team_id,
                "room_id":     room_id,
                "track_id":    active_track["track_id"],
                "track_name":  active_track["name"],
                "artist_name": active_track["artist"],
                "year":        year,
                "position":    position,
            }).execute()

            new_count = len(timeline) + 1
            if new_count >= 10:
                team_name = db.table("teams").select("name").eq("id", team_id).execute().data[0]["name"]
                db.table("rooms").update({"status": "finished"}).eq("id", room_id).execute()
                db.table("game_state").update({
                    "phase":        "finished",
                    "active_track": {**active_track, "winner": team_name},
                }).eq("room_id", room_id).execute()
                return jsonify({"correct": True, "winner": team_name, "card_count": new_count})

        db.table("game_state").update({
            "phase":        "result",
            "active_track": {**active_track, "placement_correct": correct},
        }).eq("room_id", room_id).execute()

    except Exception as e:
        logger.error(f"Game place error: {e}")
        return jsonify({"error": "Plaatsen mislukt", "details": str(e)}), 500

    return jsonify({"correct": correct, "card_count": len(timeline) + (1 if correct else 0)})


@app.route('/game/next-turn', methods=['POST'])
def game_next_turn():
    data   = request.get_json() or {}
    claims = verify_token(data.get("token"))
    if not claims or claims.get("role") != "host":
        return jsonify({"error": "Geen toegang"}), 403
    room_id = claims["room_id"]
    db = get_db()

    try:
        state = db.table("game_state").select("*").eq("room_id", room_id).execute().data[0]
        teams = db.table("teams").select("*").eq("room_id", room_id).order("created_at").execute().data

        cur_idx   = next((i for i, t in enumerate(teams) if t["id"] == state["current_team_id"]), 0)
        next_team = teams[(cur_idx + 1) % len(teams)]

        db.table("game_state").update({
            "current_team_id": next_team["id"],
            "phase":           "idle",
            "active_track":    None,
        }).eq("room_id", room_id).execute()
    except Exception as e:
        logger.error(f"Next turn error: {e}")
        return jsonify({"error": "Beurt wisselen mislukt", "details": str(e)}), 500

    return jsonify({"next_team": next_team["name"]})


if __name__ == '__main__':
    app.run(debug=True, ssl_context='adhoc')
