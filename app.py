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
import datetime
import calendar
from collections import Counter
from dotenv import load_dotenv

load_dotenv()  # Make sure environment variables are loaded

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
    try:
        sp_oauth = create_spotify_oauth()
        auth_url = sp_oauth.get_authorize_url()
        return redirect(auth_url)
    except Exception as e:
        print(f"Login error: {e}")
        return render_template('error.html', error=str(e))
    
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
    
    try:
        # Get user's top artists for different time ranges
        top_artists_short = sp.current_user_top_artists(limit=50, time_range='short_term')
        top_artists_medium = sp.current_user_top_artists(limit=50, time_range='medium_term')
        top_artists_long = sp.current_user_top_artists(limit=50, time_range='long_term')
        
        # Get user's top tracks for different time ranges
        top_tracks_short = sp.current_user_top_tracks(limit=50, time_range='short_term')
        top_tracks_medium = sp.current_user_top_tracks(limit=50, time_range='medium_term')
        top_tracks_long = sp.current_user_top_tracks(limit=50, time_range='long_term')
        
        # Process the data for time periods
        short_term_data = process_time_period_data(sp, top_artists_short, top_tracks_short, 3)
        medium_term_data = process_time_period_data(sp, top_artists_medium, top_tracks_medium, 3)
        long_term_data = process_time_period_data(sp, top_artists_long, top_tracks_long, 3)
        
        # Create visualizations
        visualizations = create_visualizations(sp, top_artists_short, top_artists_medium, top_artists_long)
        
        return render_template('visualize.html', 
                              user_name=sp.me()['display_name'],
                              current_year=current_year,
                              short_term_data=short_term_data,
                              medium_term_data=medium_term_data,
                              long_term_data=long_term_data,
                              genres_chart=visualizations['genres'],
                              listening_patterns_chart=visualizations['listening_patterns'])
    except Exception as e:
        print(f"Error in visualize route: {e}")
        # Provide empty data structures to avoid template errors
        empty_data = {'artists': [], 'tracks': []}
        
        # Create valid empty charts
        empty_fig = px.bar(x=[], y=[], title='Empty Chart')
        empty_chart = json.dumps(empty_fig, cls=plotly.utils.PlotlyJSONEncoder)
        
        return render_template('visualize.html',
                              user_name=sp.me()['display_name'],
                              current_year=current_year,
                              short_term_data=empty_data,
                              medium_term_data=empty_data,
                              long_term_data=empty_data,
                              genres_chart=empty_chart,
                              listening_patterns_chart=empty_chart)

def process_time_period_data(sp, artists_data, tracks_data, limit=3):
    """Process artist and track data for a specific time period."""
    result = {
        'artists': [],
        'tracks': []
    }
    
    # Process top artists
    for i, artist in enumerate(artists_data['items'][:limit]):
        # Get artist image or use placeholder
        image_url = artist['images'][0]['url'] if artist['images'] else '/static/placeholder.png'
        
        # Get top genres (limit to 3)
        top_genres = artist['genres'][:3] if artist['genres'] else []
        
        result['artists'].append({
            'id': artist['id'],
            'name': artist['name'],
            'image_url': image_url,
            'popularity': artist['popularity'],
            'top_genres': top_genres
        })
    
    # Process top tracks
    for i, track in enumerate(tracks_data['items'][:limit]):
        # Get album image or use placeholder
        album_image = track['album']['images'][0]['url'] if track['album']['images'] else '/static/placeholder.png'
        
        result['tracks'].append({
            'id': track['id'],
            'name': track['name'],
            'artist': track['artists'][0]['name'],
            'album': track['album']['name'],
            'album_image': album_image,
            'popularity': track['popularity']
        })
    
    return result

def create_visualizations(sp, top_artists_short, top_artists_medium, top_artists_long):
    """Create visualizations from processed data."""
    visualizations = {}
    
    # Create genre chart from medium-term top artists
    genres_count = Counter()
    for artist in top_artists_medium['items']:
        for genre in artist['genres']:
            genres_count[genre] += 1
    
    top_genres = [(genre, count) for genre, count in genres_count.most_common(10)]
    if top_genres:
        df_genres = pd.DataFrame(top_genres, columns=['genre', 'count'])
        fig_genres = px.pie(df_genres, 
                           values='count', 
                           names='genre', 
                           title='Your Top Genres',
                           color_discrete_sequence=px.colors.sequential.Viridis)
        fig_genres.update_layout(
            plot_bgcolor='rgba(40,40,40,0.8)',
            paper_bgcolor='rgba(40,40,40,0)',
            font=dict(color='white')
        )
        visualizations['genres'] = json.dumps(fig_genres, cls=plotly.utils.PlotlyJSONEncoder)
    else:
        fig_genres = px.pie(values=[], names=[], title='Your Top Genres')
        visualizations['genres'] = json.dumps(fig_genres, cls=plotly.utils.PlotlyJSONEncoder)
    
    # Create listening patterns chart comparing time periods
    # Get counts of top artists in each time period
    short_term_count = len(top_artists_short['items'])
    medium_term_count = len(top_artists_medium['items'])
    long_term_count = len(top_artists_long['items'])
    
    # Create a comparative visualization
    time_periods = ['Last 4 Weeks', 'Last 6 Months', 'All Time']
    artist_counts = [short_term_count, medium_term_count, long_term_count]
    
    listening_df = pd.DataFrame({
    'Time Period': time_periods,
    'Number of Unique Artists': artist_counts
    })
    
    fig_patterns = px.bar(
        listening_df,
        x='Time Period',
        y='Number of Unique Artists',
        title='Your Listening Diversity Across Time Periods',
        color_discrete_sequence=['#1DB954']
    )
    # Remove color bar/legend
    fig_patterns.update_layout(
        plot_bgcolor='rgba(40,40,40,0.8)',
        paper_bgcolor='rgba(40,40,40,0)',
        font=dict(color='white'),
        margin=dict(l=50, r=20, t=50, b=50),
        coloraxis_showscale=False
    )
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