from flask import Flask, request, redirect, session, render_template
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
import requests

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.config['SESSION_COOKIE_NAME'] = "SpotifyLogin"

SPOTIPY_CLIENT_ID = "523d90f864664cb7b8bde95b200b653e"
SPOTIPY_CLIENT_SECRET = "cbd38ca3e0414011869bb300332ba43c"
SPOTIPY_REDIRECT_URI = "https://hitormiss.onrender.com/callback"  # ✅ Render URL

scope = "user-read-playback-state user-modify-playback-state streaming"

sp_oauth = SpotifyOAuth(client_id=SPOTIPY_CLIENT_ID,
                        client_secret=SPOTIPY_CLIENT_SECRET,
                        redirect_uri=SPOTIPY_REDIRECT_URI,
                        scope=scope)

# 🎵 Hoofdpagina
@app.route('/')
def home():
    return render_template("home.html")

# 🔹 QR-Scanner pagina
@app.route('/scan')
def scan_page():
    return render_template("scan.html")

# 🔹 Verwerk gescande QR-code
@app.route('/process_scan')
def process_scan():
    track_id = request.args.get("track")

    if not track_id:
        return "❌ Geen track ID gevonden!", 400

    # 🔄 Redirect naar de afspeelpagina
    return redirect(f"https://hitormiss.onrender.com/play/{track_id}")

# 🔹 Spotify OAuth Login
@app.route('/login')
def login():
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

# 🔹 Callback - Haal access token op
@app.route('/callback')
def callback():
    session.clear()
    code = request.args.get('code')

    if not code:
        return "❌ Geen code ontvangen van Spotify!", 400

    try:
        token_info = sp_oauth.get_access_token(code, as_dict=True)
        print(f"✅ Token ontvangen: {token_info}")  
        session["token_info"] = dict(token_info)  
    except Exception as e:
        print(f"❌ Fout bij ophalen van token: {e}")
        return f"❌ Fout bij ophalen van token: {e}", 500

    return redirect("/player")

# 🔹 Spelerpagina
@app.route('/player')
def player():
    return "✅ Spotify is ingelogd! Maar je moet een track ID selecteren."

@app.route('/play/<track_id>')
def play(track_id):
    token_info = session.get("token_info", {})
    access_token = token_info.get("access_token")

    if not access_token:
        return "❌ Geen Spotify token beschikbaar. Log opnieuw in.", 401

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
        return '❌ Geen actieve Spotify apparaten gevonden! Open Spotify op je telefoon en speel iets af.', 400

    # 🔹 **Stap 2: Selecteer een mobiel apparaat als prioriteit**
    device_id = None
    for device in devices:
        if device["type"] == "Smartphone":  # 🎯 Selecteer ALTIJD een mobiel apparaat
            device_id = device["id"]
            break

    # 🔹 **Als er geen mobiel apparaat is, pak een ander actief apparaat**
    if not device_id:
        device_id = next((d["id"] for d in devices if d["is_active"]), None)

    # ❌ Als er nog steeds geen apparaat is, neem het eerste beschikbare apparaat
    if not device_id:
        device_id = devices[0]["id"]  # Fallback

    print(f"✅ Geselecteerd apparaat: {device_id}")

    # **Stap 3: Forceer Spotify om naar dit apparaat te schakelen**
    transfer_url = "https://api.spotify.com/v1/me/player"
    transfer_payload = {"device_ids": [device_id]}  

    transfer_response = requests.put(transfer_url, headers=headers, json=transfer_payload)

    if transfer_response.status_code not in [200, 204]:
        return f"⚠️ Kan Spotify niet verplaatsen: {transfer_response.status_code} {transfer_response.text}", 500

    print(f"✅ Spotify sessie verplaatst naar apparaat: {device_id}")

    # **Stap 4: Start het afspelen op het geselecteerde apparaat**
    play_url = f"https://api.spotify.com/v1/me/player/play?device_id={device_id}"
    response = requests.put(play_url, headers=headers, json={"uris": [f"spotify:track:{track_id}"]})

    if response.status_code == 204:
        return f"🎵 Track {track_id} wordt afgespeeld op apparaat {device_id}!"
    else:
        return f"❌ Fout bij afspelen: {response.status_code} {response.text}", 500
    
if __name__ == '__main__':
    app.run(debug=True, port=5500)