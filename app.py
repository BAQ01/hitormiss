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

# 🎵 **Startpagina: Spotify moet elke keer opnieuw verbonden worden**
@app.route('/')
def home():
    token_info = session.get("token_info")
    logged_in = token_info and "access_token" in token_info  # ✅ Check hier correct of er een token is
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
    return render_template("force_browser.html", auth_url=auth_url)  # ✅ Zorgt dat de juiste pagina opent

# 🔹 **Callback - Haal access token op en keer terug naar startpagina**
@app.route('/callback')
def callback():
    if "token_info" in session:
        session.pop("token_info")  # Oude token verwijderen

    code = request.args.get('code')  

    if not code:
        return "❌ Geen code ontvangen van Spotify!", 400

    try:
        token_info = sp_oauth.get_access_token(code, as_dict=True)
        session["token_info"] = token_info  
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

    if sp_oauth.is_token_expired(token_info):
        try:
            token_info = sp_oauth.refresh_access_token(token_info["refresh_token"])
            session["token_info"] = token_info
            print("🔄 Token vernieuwd en opgeslagen in sessie.")
        except Exception as e:
            print(f"❌ Fout bij vernieuwen van token: {e}")
            session.clear()
            return None  

    return token_info["access_token"]

# 🔹 **Speel een track af op de telefoon waarmee gescand wordt**
@app.route('/play/<track_id>')
def play(track_id):
    # 🎯 Directe Spotify Deeplink genereren
    track_url = f"spotify://track/{track_id}"

    # ✅ Open de track in Spotify, maar zorg dat Hit or Miss actief blijft
    return render_template("keep_foreground.html", track_url=track_url)

if __name__ == '__main__':
    app.run(debug=False, port=5500)  # ❗ Zet debug op False in productie!