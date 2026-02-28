from flask import Flask, request, redirect, session, render_template, url_for, jsonify
import os
import re
import requests
import logging
from spotipy.oauth2 import SpotifyOAuth

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "een_willekeurige_lange_string_voor_beveiliging")
app.config['SESSION_COOKIE_NAME'] = "SpotifyLogin"
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600

SPOTIPY_CLIENT_ID = os.environ.get("SPOTIPY_CLIENT_ID", "523d90f864664cb7b8bde95b200b653e")
SPOTIPY_CLIENT_SECRET = os.environ.get("SPOTIPY_CLIENT_SECRET", "cbd38ca3e0414011869bb300332ba43c")
SCOPE = "user-read-playback-state user-modify-playback-state streaming"


def get_redirect_uri():
    """Derive redirect URI from env var or current request host."""
    env_uri = os.environ.get("SPOTIPY_REDIRECT_URI")
    if env_uri:
        return env_uri
    # Locally: always use https://localhost (matches Spotify registration)
    host = request.host.replace('127.0.0.1', 'localhost')
    return f"https://{host}/callback"


def get_spotify_oauth(redirect_uri):
    return SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=redirect_uri,
        scope=SCOPE,
        show_dialog=True,
        cache_path=None,
    )


def get_token():
    """Return a valid access token, refreshing if expired. Returns None if not logged in."""
    token_info = session.get("token_info")
    if not token_info or "access_token" not in token_info:
        return None

    redirect_uri = session.get("redirect_uri", "http://localhost:5000/callback")
    sp_oauth = get_spotify_oauth(redirect_uri)

    if sp_oauth.is_token_expired(token_info):
        try:
            token_info = sp_oauth.refresh_access_token(token_info["refresh_token"])
            session["token_info"] = token_info
            logger.info("Token vernieuwd")
        except Exception as e:
            logger.error(f"Token vernieuwen mislukt: {e}")
            session.pop("token_info", None)
            return None

    return token_info["access_token"]


def extract_track_id(text):
    """Extract a Spotify track ID from a QR code value."""
    text = text.strip()
    # spotify:track:XXXX
    m = re.search(r'spotify:track:([A-Za-z0-9]+)', text)
    if m:
        return m.group(1)
    # https://open.spotify.com/track/XXXX
    m = re.search(r'open\.spotify\.com/track/([A-Za-z0-9]+)', text)
    if m:
        return m.group(1)
    # Plain 22-char alphanumeric ID
    if re.match(r'^[A-Za-z0-9]{22}$', text):
        return text
    return None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def home():
    logged_in = bool(session.get("token_info"))
    return render_template("home.html", logged_in=logged_in)


@app.route('/login')
def login():
    redirect_uri = get_redirect_uri()
    session['redirect_uri'] = redirect_uri
    logger.info(f"Login: redirect_uri = {redirect_uri}")
    sp_oauth = get_spotify_oauth(redirect_uri)
    return redirect(sp_oauth.get_authorize_url())


@app.route('/callback')
def callback():
    error = request.args.get('error')
    if error:
        return render_template("error.html", message="Spotify login geweigerd.", error_details=error)

    code = request.args.get('code')
    if not code:
        return render_template("error.html", message="Geen autorisatiecode ontvangen van Spotify.")

    redirect_uri = session.get('redirect_uri', get_redirect_uri())
    sp_oauth = get_spotify_oauth(redirect_uri)

    try:
        token_info = sp_oauth.get_access_token(code, as_dict=True)
        session["token_info"] = token_info
        logger.info("Token opgeslagen")
    except Exception as e:
        logger.error(f"Token ophalen mislukt: {e}")
        return render_template("error.html", message="Inloggen mislukt.", error_details=str(e))

    return redirect(url_for("scan_page"))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route('/scan')
def scan_page():
    if not get_token():
        return redirect(url_for("login"))
    error_map = {
        "invalid_qr": "Ongeldige QR-code. Scan een Hitster kaart.",
        "track_not_found": "Nummer niet gevonden op Spotify.",
        "no_track": "Geen track gevonden in de QR-code.",
    }
    error_msg = error_map.get(request.args.get("error"))
    return render_template("scan.html", error_msg=error_msg)


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
        logger.error(f"Track ophalen mislukt: {resp.status_code}")
        return redirect(url_for("scan_page", error="track_not_found"))

    track = resp.json()
    artist_name = ", ".join(a["name"] for a in track["artists"])
    year = track["album"]["release_date"][:4]
    images = track["album"]["images"]
    album_art = images[0]["url"] if images else None

    return render_template(
        "play.html",
        track_id=track_id,
        track_name=track["name"],
        artist_name=artist_name,
        year=year,
        album_art=album_art,
        access_token=access_token,
    )


@app.route('/api/token')
def api_token():
    token = get_token()
    if not token:
        return jsonify({"error": "not_authenticated"}), 401
    return jsonify({"access_token": token})


@app.route('/api/play', methods=['POST'])
def api_play():
    """Play a track. Called by the client after SDK initialises or as fallback."""
    access_token = get_token()
    if not access_token:
        return jsonify({"error": "not_authenticated"}), 401

    data = request.get_json() or {}
    track_id = data.get("track_id")
    device_id = data.get("device_id")  # None when falling back to phone

    if not track_id:
        return jsonify({"error": "no track_id"}), 400

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # When no SDK device, find a Spotify device via the API
    if not device_id:
        dev_resp = requests.get("https://api.spotify.com/v1/me/player/devices", headers=headers)
        if dev_resp.status_code == 200:
            devices = dev_resp.json().get("devices", [])
            # Prefer smartphone, then any device
            for d in devices:
                if "phone" in d["type"].lower():
                    device_id = d["id"]
                    break
            if not device_id and devices:
                device_id = devices[0]["id"]

        if not device_id:
            return jsonify({
                "error": "no_device",
                "message": "Geen Spotify-apparaat gevonden. Open de Spotify-app op je telefoon.",
            }), 404

    play_resp = requests.put(
        f"https://api.spotify.com/v1/me/player/play?device_id={device_id}",
        headers=headers,
        json={"uris": [f"spotify:track:{track_id}"], "position_ms": 0},
    )

    if play_resp.status_code in [204, 202]:
        logger.info(f"Track {track_id} speelt op apparaat {device_id}")
        return jsonify({"status": "playing"})

    logger.error(f"Afspelen mislukt: {play_resp.status_code} {play_resp.text}")
    return jsonify({"error": "playback_failed", "details": play_resp.text}), 500


if __name__ == '__main__':
    app.run(debug=True, ssl_context='adhoc')
