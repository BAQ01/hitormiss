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
                        scope=scope)

sp_oauth = get_spotify_oauth()

# 🎵 **Startpagina: Toon een login knop**
@app.route('/')
def home():
    session.clear()  # ❌ Wis de sessie bij elk bezoek

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

# 🔹 **Spotify OAuth Login (Forceer mobiele app indien mogelijk)**
@app.route('/login')
def login():
    sp_oauth = get_spotify_oauth()  # ✅ Zorg ervoor dat SpotifyOAuth een redirect URI bevat
    auth_url = sp_oauth.get_authorize_url()
    return render_template("force_browser.html", auth_url=auth_url)

# 🔹 **Callback - Haal access token op en keer terug naar startpagina**
@app.route('/callback')
def callback():
    sp_oauth = get_spotify_oauth()  # ✅ Zorg ervoor dat SpotifyOAuth correct is geladen
    session.clear()
    
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

# 🔹 **Forceer Spotify op de telefoon en speel af**
@app.route('/play/<track_id>')
def play(track_id):
    token_info = session.get("token_info", {})
    access_token = token_info.get("access_token")

    if not access_token:
        return redirect(url_for("login"))  # 🚀 Forceer herlogin als er geen token is

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # 🔥 **Stap 1: Zoek actieve apparaten**
    device_response = requests.get("https://api.spotify.com/v1/me/player/devices", headers=headers)

    if device_response.status_code != 200:
        return f"❌ Fout bij ophalen van apparaten: {device_response.status_code} {device_response.text}", 500

    devices = device_response.json().get("devices", [])

    if not devices:
        return ('❌ Geen actieve Spotify apparaten gevonden!<br>'
                '📱 Open <a href="spotify://">Spotify op je telefoon</a> en speel iets af.', 400)

    # 🔹 **Stap 2: Zoek en forceer mobiel apparaat**
    device_id = None
    for d in devices:
        device_type = d["type"].lower()
        if "phone" in device_type or "mobile" in device_type or "smartphone" in device_type:
            device_id = d["id"]
            break

    if not device_id:
        return ('❌ Geen mobiel apparaat gevonden!<br>'
                '📱 Open <a href="spotify://">Spotify op je telefoon</a> en speel iets af.', 400)

    print(f"✅ Geselecteerd apparaat: {device_id}")

    # 🔹 **Stap 3: Forceer Spotify om naar de telefoon te schakelen**
    transfer_url = "https://api.spotify.com/v1/me/player"
    transfer_payload = {"device_ids": [device_id]}  

    transfer_response = requests.put(transfer_url, headers=headers, json=transfer_payload)

    if transfer_response.status_code not in [200, 204]:
        return f"⚠️ Kan Spotify niet verplaatsen: {transfer_response.status_code} {transfer_response.text}", 500

    print(f"✅ Spotify sessie verplaatst naar apparaat: {device_id}")

    # **Stap 4: Dummy track afspelen om apparaat te activeren**
    dummy_track = "spotify:track:7xGfFoTpQ2E7fRF5lN10tr"  # 🎵 Random track (Leeg/Low Volume)
    play_dummy_url = f"https://api.spotify.com/v1/me/player/play?device_id={device_id}"
    
    requests.put(play_dummy_url, headers=headers, json={"uris": [dummy_track]})
    print("🔸 Dummy track gestart om apparaat te activeren.")

    time.sleep(2)  # ⏳ 2 seconden wachten

    # **Stap 5: Start het afspelen van de echte track**
    play_url = f"https://api.spotify.com/v1/me/player/play?device_id={device_id}"
    response = requests.put(play_url, headers=headers, json={"uris": [f"spotify:track:{track_id}"]})

    if response.status_code == 204:
        return f"🎵 Track {track_id} wordt afgespeeld op apparaat {device_id}!"
    else:
        return f"❌ Fout bij afspelen: {response.status_code} {response.text}", 500

if __name__ == '__main__':
    app.run(debug=True, port=5500)