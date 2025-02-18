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
SPOTIPY_REDIRECT_URI = "http://localhost:5500/callback"

scope = "user-read-playback-state user-modify-playback-state streaming"

sp_oauth = SpotifyOAuth(client_id=SPOTIPY_CLIENT_ID,
                        client_secret=SPOTIPY_CLIENT_SECRET,
                        redirect_uri=SPOTIPY_REDIRECT_URI,
                        scope=scope)

# 🔹 Hoofdpagina - Vraag login aan
@app.route('/')
def home():
    return '<a href="/login">Log in met Spotify</a>'

# 🔹 Spotify OAuth Login
@app.route('/login')
def login():
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

# 🔹 Callback - Haal access token op
@app.route('/callback')
@app.route('/callback')

def callback():
    session.clear()
    code = request.args.get('code')

    if not code:
        return "❌ Geen code ontvangen van Spotify!", 400

    try:
        token_info = sp_oauth.get_access_token(code, as_dict=True)  # ✅ Forceer dictionary
        print(f"✅ Token ontvangen: {token_info}")  # Debugging log
        session["token_info"] = dict(token_info)  # ✅ Zorg ervoor dat het een dictionary blijft
    except Exception as e:
        print(f"❌ Fout bij ophalen van token: {e}")
        return f"❌ Fout bij ophalen van token: {e}", 500

    return redirect("/player")

# 🔹 Voeg deze route toe boven de /play/<track_id> route
@app.route('/player')
def player():
    return "✅ Spotify is ingelogd! Maar je moet een track ID selecteren."

import requests

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

    # 🔥 Stap 1: Controleer of Spotify al iets afspeelt
    device_response = requests.get("https://api.spotify.com/v1/me/player", headers=headers)

    if device_response.status_code == 204:
        print("⚠️ Spotify geeft een lege status terug (204). Mogelijk geen actief apparaat!")
    elif device_response.status_code == 200:
        player_state = device_response.json()
        if not player_state.get("is_playing"):
            print("⚠️ Spotify is niet actief! Probeer het handmatig te starten.")
    else:
        return f"❌ Fout bij ophalen van player status: {device_response.status_code}", 500

    # 🔥 Stap 2: Haal het laatst gebruikte apparaat op
    device_response = requests.get("https://api.spotify.com/v1/me/player/devices", headers=headers)
    devices = device_response.json().get("devices", [])

    if not devices:
        return "❌ Geen actieve Spotify apparaten gevonden! Open Spotify op een ander apparaat en speel iets af.", 400

    device_id = devices[0]["id"]  # Gebruik het eerste actieve apparaat
    print(f"✅ Geselecteerd apparaat: {device_id}")

    # 🔄 **Stap 2.5: Verplaats de weergave naar dit apparaat als er geen actieve weergave is**
    transfer_url = "https://api.spotify.com/v1/me/player"
    transfer_response = requests.put(transfer_url, headers=headers, json={"device_ids": [device_id]})

    if transfer_response.status_code not in [200, 204]:
        print(f"⚠️ Kon Spotify weergave niet overzetten: {transfer_response.status_code} {transfer_response.text}")

    # 🔥 Stap 3: Stuur afspeelcommando naar Spotify
    play_url = f"https://api.spotify.com/v1/me/player/play?device_id={device_id}"
    response = requests.put(play_url, headers=headers, json={"uris": [f"spotify:track:{track_id}"]})

    if response.status_code == 204:
        return f"🎵 Track {track_id} wordt afgespeeld op {device_id}!"
    else:
        return f"❌ Fout bij afspelen: {response.status_code} {response.text}", 500
    
if __name__ == '__main__':
    app.run(debug=True, port=5500)