# app.py
import os
import json
import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import Flask, request, url_for, session, redirect, render_template
import pandas as pd
import plotly
import plotly.express as px
from dotenv import load_dotenv

app = Flask(__name__)

app.secret_key = os.getenv("FLASK_SECRET_KEY")
app.config['SESSION_COOKIE_NAME'] = 'Spotify Cookie'
app.config['SESSION_TYPE'] = 'filesystem'

# Spotify API credentials
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = "http://localhost:5000/callback"
SCOPE = "user-read-recently-played user-top-read user-read-currently-playing user-read-playback-state"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login():
    sp_oauth = create_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/callback')
def callback():
    sp_oauth = create_spotify_oauth()
    session.clear()
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)
    session["token_info"] = token_info
    return redirect('/visualize')

@app.route('/visualize')
def visualize():
    try:
        token_info = get_token()
    except:
        return redirect('/login')
    
    sp = spotipy.Spotify(auth=token_info['access_token'])
    
    # Get user's top tracks
    top_tracks_short = sp.current_user_top_tracks(limit=50, time_range='short_term')
    top_tracks_medium = sp.current_user_top_tracks(limit=50, time_range='medium_term')
    top_tracks_long = sp.current_user_top_tracks(limit=50, time_range='long_term')
    
    # Get user's top artists
    top_artists_short = sp.current_user_top_artists(limit=50, time_range='short_term')
    top_artists_medium = sp.current_user_top_artists(limit=50, time_range='medium_term')
    top_artists_long = sp.current_user_top_artists(limit=50, time_range='long_term')
    
    # Get recently played tracks
    recent_tracks = sp.current_user_recently_played(limit=50)
    
    # Process the data for visualization
    data = process_data(top_tracks_short, top_tracks_medium, top_tracks_long,
                       top_artists_short, top_artists_medium, top_artists_long,
                       recent_tracks)
    
    # Create visualizations
    visualizations = create_visualizations(data)
    
    return render_template('visualize.html', 
                          viz_top_artists=visualizations['top_artists'],
                          viz_top_tracks=visualizations['top_tracks'],
                          viz_genres=visualizations['genres'],
                          viz_listening_patterns=visualizations['listening_patterns'],
                          user_name=sp.me()['display_name'])

def process_data(top_tracks_short, top_tracks_medium, top_tracks_long,
                top_artists_short, top_artists_medium, top_artists_long,
                recent_tracks):
    """Process Spotify data for visualization."""
    data = {}
    
    # Process top tracks data
    tracks_short = [{'name': track['name'], 'popularity': track['popularity'], 
                    'artist': track['artists'][0]['name']} for track in top_tracks_short['items']]
    tracks_medium = [{'name': track['name'], 'popularity': track['popularity'], 
                     'artist': track['artists'][0]['name']} for track in top_tracks_medium['items']]
    tracks_long = [{'name': track['name'], 'popularity': track['popularity'], 
                   'artist': track['artists'][0]['name']} for track in top_tracks_long['items']]
    
    data['tracks'] = {
        'short_term': tracks_short,
        'medium_term': tracks_medium,
        'long_term': tracks_long
    }
    
    # Process top artists data
    artists_short = [{'name': artist['name'], 'popularity': artist['popularity'], 
                     'genres': artist['genres']} for artist in top_artists_short['items']]
    artists_medium = [{'name': artist['name'], 'popularity': artist['popularity'], 
                      'genres': artist['genres']} for artist in top_artists_medium['items']]
    artists_long = [{'name': artist['name'], 'popularity': artist['popularity'], 
                    'genres': artist['genres']} for artist in top_artists_long['items']]
    
    data['artists'] = {
        'short_term': artists_short,
        'medium_term': artists_medium,
        'long_term': artists_long
    }
    
    # Process genres
    genres = {}
    for term in ['short_term', 'medium_term', 'long_term']:
        term_genres = {}
        for artist in data['artists'][term]:
            for genre in artist['genres']:
                if genre in term_genres:
                    term_genres[genre] += 1
                else:
                    term_genres[genre] = 1
        genres[term] = term_genres
    
    data['genres'] = genres
    
    # Process recently played
    recent = []
    for item in recent_tracks['items']:
        track = item['track']
        played_at = item['played_at']
        recent.append({
            'name': track['name'],
            'artist': track['artists'][0]['name'],
            'played_at': played_at
        })
    
    data['recent'] = recent
    
    return data

def create_visualizations(data):
    """Create visualizations from processed data."""
    visualizations = {}
    
    # Top artists visualization (medium term)
    df_artists = pd.DataFrame(data['artists']['medium_term'])
    df_artists = df_artists.sort_values('popularity', ascending=False).head(10)
    fig_artists = px.bar(df_artists, x='name', y='popularity', title='Your Top 10 Artists',
                        labels={'name': 'Artist', 'popularity': 'Popularity Score'})
    visualizations['top_artists'] = json.dumps(fig_artists, cls=plotly.utils.PlotlyJSONEncoder)
    
    # Top tracks visualization (medium term)
    df_tracks = pd.DataFrame(data['tracks']['medium_term'])
    df_tracks = df_tracks.sort_values('popularity', ascending=False).head(10)
    fig_tracks = px.bar(df_tracks, x='name', y='popularity', title='Your Top 10 Tracks',
                       labels={'name': 'Track', 'popularity': 'Popularity Score'})
    visualizations['top_tracks'] = json.dumps(fig_tracks, cls=plotly.utils.PlotlyJSONEncoder)
    
    # Genre visualization (medium term)
    genres = data['genres']['medium_term']
    df_genres = pd.DataFrame(list(genres.items()), columns=['genre', 'count'])
    df_genres = df_genres.sort_values('count', ascending=False).head(10)
    fig_genres = px.pie(df_genres, values='count', names='genre', title='Your Top Genres')
    visualizations['genres'] = json.dumps(fig_genres, cls=plotly.utils.PlotlyJSONEncoder)
    
    # Listening patterns by time of day
    df_recent = pd.DataFrame(data['recent'])
    df_recent['played_at'] = pd.to_datetime(df_recent['played_at'])
    df_recent['hour'] = df_recent['played_at'].dt.hour
    hour_counts = df_recent.groupby('hour').size().reset_index(name='count')
    fig_patterns = px.line(hour_counts, x='hour', y='count', title='Your Listening Patterns by Hour',
                          labels={'hour': 'Hour of Day', 'count': 'Tracks Played'})
    visualizations['listening_patterns'] = json.dumps(fig_patterns, cls=plotly.utils.PlotlyJSONEncoder)
    
    return visualizations

def create_spotify_oauth():
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE
    )

def get_token():
    token_info = session.get("token_info", None)
    if not token_info:
        raise Exception("No token info")
    
    # Check if token is expired and refresh if needed
    now = int(time.time())
    is_expired = token_info['expires_at'] - now < 60
    if is_expired:
        sp_oauth = create_spotify_oauth()
        token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
        session["token_info"] = token_info
    
    return token_info

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)