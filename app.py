from flask import Flask, request, redirect, session, render_template, url_for
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
import requests
import time

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.config['SESSION_COOKIE_NAME'] = "SpotifyLogin"

SPOTIPY_CLIENT_ID = "523d90f864664cb7b8bde95b200b653e"
SPOTIPY_CLIENT_SECRET = "cbd38ca3e0414011869bb300332ba43c"
SPOTIPY_REDIRECT_URI = "https://hitormiss.onrender.com/callback"

scope = "user-read-playback-state user-modify-playback-state streaming"

def get_spotify_oauth():
    return SpotifyOAuth(client_id=SPOTIPY_CLIENT_ID,
                        client_secret=SPOTIPY_CLIENT_SECRET,
                        redirect_uri=SPOTIPY_REDIRECT_URI,
                        scope=scope,
                        show_dialog=True)  # ✅ Forceer Spotify login bij elke keer opstarten

sp_oauth = get_spotify_oauth()

# 🎵 **Startpagina: Toon een login knop**
@app.route('/')
def home():
    token_info = session.get("token_info")
    logged_in = token_info and "access_token" in token_info

    return render_template("home.html", logged_in=logged_in)

# 🔹 **QR-Scanner pagina**
@app.route('/scan')
def scan_page():
    return render_template("scan.html")

# 🔹 **Verwerk gescande QR-code**
@app.route('/process_scan')
def process_scan():
    track_id = request.args.get("track")

    if not track_id:
        return "❌ Geen track ID gevonden!", 400

    return redirect(url_for("play", track_id=track_id))

# 🔹 **Spotify OAuth Login**
@app.route('/login')
def login():
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

# 🔹 **Callback - Haal access token op en keer terug naar startpagina**
@app.route('/callback')
def callback():
    session.clear()  # ❌ Wis de sessie om een nieuwe login te forceren
    
    code = request.args.get('code')
    if not code:
        return "❌ Geen code ontvangen van Spotify!", 400

    try:
        token_info = sp_oauth.get_access_token(code, as_dict=True)
        session["token_info"] = dict(token_info)
        print(f"✅ Token opgeslagen in sessie: {session['token_info']}")
    except Exception as e:
        print(f"❌ Fout bij ophalen van token: {e}")
        return f"❌ Fout bij ophalen van token: {e}", 500

    return redirect(url_for("home"))  # ✅ Keer terug naar de homepagina

# 🔹 **Verkrijg Spotify Token (met refresh)**
def get_token():
    token_info = session.get("token_info")
    if not token_info:
        return None

    if sp_oauth.is_token_expired(token_info):
        token_info = sp_oauth.refresh_access_token(token_info["refresh_token"])
        session["token_info"] = token_info  # Sla het nieuwe token op
    return token_info["access_token"]

# 🔹 **Speel een track af op een mobiel apparaat**
@app.route('/play/<track_id>')
def play(track_id):
    access_token = get_token()
    if not access_token:
        return redirect(url_for("login"))  # 🚀 Forceer herlogin als er geen token is

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # 🔍 **Stap 1: Detecteer welk apparaat de gebruiker gebruikt via User-Agent**
    user_agent = request.headers.get('User-Agent', '').lower()
    print(f"🔍 User-Agent: {user_agent}")

    if "iphone" in user_agent:
        phone_type = "iPhone"
    elif "android" in user_agent:
        phone_type = "Android"
    else:
        phone_type = None  # ❌ Geen telefoon herkend

    # 🔥 **Stap 2: Haal de beschikbare Spotify apparaten op**
    device_response = requests.get("https://api.spotify.com/v1/me/player/devices", headers=headers)

    if device_response.status_code != 200:
        return f"❌ Fout bij ophalen van apparaten: {device_response.status_code} {device_response.text}", 500

    devices = device_response.json().get("devices", [])

    if not devices:
        return ('❌ Geen actieve Spotify apparaten gevonden!<br>'
                '📱 Open <a href="spotify://">Spotify op je telefoon</a> en speel iets af.', 400)

    # 🔥 **Stap 3: Selecteer ALLEEN het apparaat dat matcht met het User-Agent**
    device_id = None

    for d in devices:
        device_name = d["name"].lower()
        print(f"📱 Beschikbaar apparaat: {d['name']} ({d['type']})")

        if phone_type == "iPhone" and "iphone" in device_name:
            device_id = d["id"]
            break
        elif phone_type == "Android" and "android" in device_name:
            device_id = d["id"]
            break

    if not device_id:
        return ('❌ Geen juiste telefoon gevonden!<br>'
                '📱 Open <a href="spotify://">Spotify op je telefoon</a> en speel iets af.', 400)

    print(f"✅ Geselecteerd apparaat: {device_id} (Gebaseerd op User-Agent: {phone_type})")

    # 🔥 **Stap 4: Forceer Spotify om naar de juiste telefoon te schakelen**
    transfer_url = "https://api.spotify.com/v1/me/player"
    transfer_payload = {"device_ids": [device_id]}  

    transfer_response = requests.put(transfer_url, headers=headers, json=transfer_payload)

    if transfer_response.status_code not in [200, 204]:
        return f"⚠️ Kan Spotify niet verplaatsen: {transfer_response.status_code} {transfer_response.text}", 500

    print(f"✅ Spotify sessie verplaatst naar apparaat: {device_id}")

    # 🔥 **Stap 5: Start het afspelen van de gewenste track**
    play_url = f"https://api.spotify.com/v1/me/player/play?device_id={device_id}"
    response = requests.put(play_url, headers=headers, json={"uris": [f"spotify:track:{track_id}"]})

    if response.status_code == 204:
        return f"🎵 Track {track_id} wordt afgespeeld op jouw telefoon ({phone_type})!"
    else:
        return f"❌ Fout bij afspelen: {response.status_code} {response.text}", 500

if __name__ == '__main__':
    app.run(debug=True, port=5500)
