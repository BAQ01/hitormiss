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
    return SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=scope,
        show_dialog=True,  # ✅ Dwing opnieuw inloggen af bij app-herstart
        cache_path=None  # ✅ Zorg ervoor dat oude tokens niet hergebruikt worden
    )

# 🎵 **Startpagina**
@app.route('/')
def home():
    session.clear()  # ✅ Wis de sessie bij app-herstart
    return render_template("home.html", logged_in=False)

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
    auth_url = get_spotify_oauth().get_authorize_url()
    return redirect(auth_url)

# 🔹 **Callback - Haal access token op en keer terug naar startpagina**
@app.route('/callback')
def callback():
    session.clear()  # ✅ Wis de sessie om een nieuwe login te forceren
    sp_oauth = get_spotify_oauth()
    
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

    return redirect(url_for("home"))  # ✅ Keer terug naar home

# 🔹 **Verkrijg Spotify Token (met refresh)**
def get_token():
    token_info = session.get("token_info")
    if not token_info:
        print("❌ Geen opgeslagen token gevonden, opnieuw inloggen vereist.")
        return None  # 🔄 Forceer opnieuw inloggen als er geen token is

    sp_oauth = get_spotify_oauth()
    if sp_oauth.is_token_expired(token_info):
        try:
            token_info = sp_oauth.refresh_access_token(token_info["refresh_token"])
            session["token_info"] = token_info  # ✅ Sla het vernieuwde token op
            print("🔄 Token vernieuwd en opgeslagen in sessie.")
        except Exception as e:
            print(f"❌ Fout bij vernieuwen van token: {e}")
            session.clear()  # 🚨 Reset de sessie om foute tokens te verwijderen
            return None  # 🔄 Forceer opnieuw inloggen

    return token_info["access_token"]

# 🔹 **Speel een track af op een mobiel apparaat**
@app.route('/play/<track_id>')
def play(track_id):
    access_token = get_token()
    if not access_token:
        return redirect(url_for("login"))

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # 🔥 **Stap 1: Haal alle apparaten op**
    device_response = requests.get("https://api.spotify.com/v1/me/player/devices", headers=headers)
    if device_response.status_code != 200:
        return f"❌ Fout bij ophalen van apparaten: {device_response.status_code} {device_response.text}", 500

    devices = device_response.json().get("devices", [])
    if not devices:
        return ('❌ Geen actieve Spotify apparaten gevonden!<br>'
                '📱 Open <a href="spotify://">Spotify op je telefoon</a> en speel iets af.', 400)

    # 🔥 **Stap 2: Kies ALTIJD een telefoon als afspeelapparaat**
    device_id = None
    for d in devices:
        if d["type"] == "Smartphone":  # ✅ Zorgt ervoor dat ALLEEN telefoons gekozen worden
            device_id = d["id"]
            break

    if not device_id:
        return ('❌ Geen mobiel apparaat gevonden!<br>'
                '📱 Open <a href="spotify://">Spotify op je telefoon</a> en speel iets af.', 400)

    print(f"✅ Geselecteerd apparaat: {device_id} (Mobiel)")

    # 🔥 **Stap 3: Forceer Spotify naar de telefoon**
    transfer_url = "https://api.spotify.com/v1/me/player"
    transfer_payload = {"device_ids": [device_id]}  
    transfer_response = requests.put(transfer_url, headers=headers, json=transfer_payload)

    if transfer_response.status_code not in [200, 204]:
        return f"⚠️ Kan Spotify niet verplaatsen: {transfer_response.status_code} {transfer_response.text}", 500

    print(f"✅ Spotify sessie verplaatst naar apparaat: {device_id}")

    # 🔥 **Stap 4: Start het afspelen van de track**
    play_url = f"https://api.spotify.com/v1/me/player/play?device_id={device_id}"
    response = requests.put(play_url, headers=headers, json={"uris": [f"spotify:track:{track_id}"]})

    if response.status_code == 204:
        return f"🎵 Track {track_id} wordt afgespeeld op jouw telefoon!"
    else:
        return f"❌ Fout bij afspelen: {response.status_code} {response.text}", 500

if __name__ == '__main__':
    app.run(debug=True, port=5500)