from flask import Flask, request, redirect, session, render_template, url_for
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
import requests

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.config['SESSION_COOKIE_NAME'] = "SpotifyLogin"

SPOTIPY_CLIENT_ID = "523d90f864664cb7b8bde95b200b653e"
SPOTIPY_CLIENT_SECRET = "cbd38ca3e0414011869bb300332ba43c"
SPOTIPY_REDIRECT_URI = "https://hitormiss.onrender.com/callback"

scope = "user-read-playback-state user-modify-playback-state streaming"

def get_spotify_oauth():
    return SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=scope,
        show_dialog=True,
        cache_path=None
    )

sp_oauth = get_spotify_oauth()

# 🎵 **Startpagina**
@app.route('/')
def home():
    token_info = session.get("token_info")
    logged_in = token_info and "access_token" in token_info
    return render_template("home.html", logged_in=logged_in)

# 🔹 **Spotify OAuth Login**
@app.route('/login')
def login():
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

# 🔹 **Callback - Haal access token op en keer terug naar startpagina**
@app.route('/callback')
def callback():
    session.clear()  
    code = request.args.get('code')

    if not code:
        return "❌ Geen code ontvangen van Spotify!", 400

    try:
        token_info = sp_oauth.get_access_token(code, as_dict=True)
        session["token_info"] = dict(token_info)
        print(f"✅ Token opgeslagen: {session['token_info']}")
    except Exception as e:
        print(f"❌ Fout bij ophalen van token: {e}")
        return f"❌ Fout bij ophalen van token: {e}", 500

    return redirect(url_for("home"))

# 🔹 **Verkrijg of vernieuw Spotify Token**
def get_token():
    token_info = session.get("token_info")

    if not token_info:
        print("❌ Geen opgeslagen token gevonden, opnieuw inloggen vereist.")
        return None  

    if get_spotify_oauth().is_token_expired(token_info):
        try:
            token_info = get_spotify_oauth().refresh_access_token(token_info["refresh_token"])
            session["token_info"] = token_info  
            print("🔄 Token vernieuwd en opgeslagen.")
        except Exception as e:
            print(f"❌ Fout bij vernieuwen van token: {e}")
            session.clear()
            return None  

    return token_info["access_token"]

# 🔹 **Speel een track af op de telefoon waarmee gescand wordt**
@app.route('/play/<track_id>')
def play(track_id):
    access_token = get_token()
    if not access_token:
        return redirect(url_for("login"))

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # 🔥 **Stap 1: Haal de beschikbare apparaten op**
    device_response = requests.get("https://api.spotify.com/v1/me/player/devices", headers=headers)

    if device_response.status_code != 200:
        return f"❌ Fout bij ophalen van apparaten: {device_response.status_code} {device_response.text}", 500

    devices = device_response.json().get("devices", [])

    if not devices:
        return ('❌ Geen actieve Spotify apparaten gevonden!<br>'
                '📱 Open <a href="spotify://">Spotify op je telefoon</a> en speel iets af.', 400)

    # 🔥 **Stap 2: Kies de telefoon waarmee gescand wordt**
    user_agent = request.headers.get('User-Agent', '').lower()
    print(f"🔍 User-Agent: {user_agent}")

    device_id = None

    for d in devices:
        if "phone" in d["type"].lower():
            device_id = d["id"]
            break

    if not device_id:
        return ('❌ Geen mobiel apparaat gevonden!<br>'
                '📱 Open <a href="spotify://">Spotify op je telefoon</a> en speel iets af.', 400)

    print(f"✅ Geselecteerd apparaat: {device_id}")

    # 🔥 **Stap 3: Forceer Spotify naar de telefoon en start meteen de juiste track**
    play_url = f"https://api.spotify.com/v1/me/player/play?device_id={device_id}"
    play_payload = {
        "uris": [f"spotify:track:{track_id}"],
        "position_ms": 0
    }

    response = requests.put(play_url, headers=headers, json=play_payload)

    if response.status_code in [204, 202]:
        return f"🎵 Track {track_id} wordt afgespeeld op jouw telefoon!"
    else:
        return f"❌ Fout bij afspelen: {response.status_code} {response.text}", 500

if __name__ == '__main__':
    app.run(debug=False, port=5500)