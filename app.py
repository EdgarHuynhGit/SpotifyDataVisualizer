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
    
    # Get the current year
    current_year = datetime.datetime.now().year
    
    # Get user's top artists for different time ranges
    top_artists_short = sp.current_user_top_artists(limit=50, time_range='short_term')
    top_artists_medium = sp.current_user_top_artists(limit=50, time_range='medium_term')
    top_artists_long = sp.current_user_top_artists(limit=50, time_range='long_term')
    
    # Get recently played tracks
    recent_tracks = sp.current_user_recently_played(limit=50)
    
    # We'll need to make multiple calls to build up our listening history
    # This is a simplified version; in production, you'd use a database to store this data
    all_tracks = []
    
    # Get as many recent tracks as possible (up to API limits)
    after = None
    for _ in range(10):  # Try to get 10 pages of history
        try:
            if after:
                tracks = sp.current_user_recently_played(limit=50, after=after)
            else:
                tracks = sp.current_user_recently_played(limit=50)
                
            if not tracks['items']:
                break
                
            all_tracks.extend(tracks['items'])
            
            # Get cursor for next page
            after = tracks['cursors']['after']
            
            # Sleep to avoid hitting rate limits
            time.sleep(1)
        except Exception as e:
            print(f"Error fetching tracks: {e}")
            break
    
    # Process the data for visualization
    monthly_data = process_monthly_data(sp, all_tracks, current_year)
    
    # Create visualizations
    visualizations = create_visualizations(sp, top_artists_short, top_artists_medium, 
                                        top_artists_long, monthly_data)
    
    return render_template('visualize.html', 
                          user_name=sp.me()['display_name'],
                          current_year=current_year,
                          monthly_data=monthly_data,
                          yearly_artists_chart=visualizations['yearly_artists'],
                          genres_chart=visualizations['genres'],
                          listening_patterns_chart=visualizations['listening_patterns'])

def process_monthly_data(sp, tracks, current_year):
    """Process tracks to get monthly top artists data."""
    # Initialize monthly data
    months = []
    for month_num in range(1, 13):
        month_name = calendar.month_name[month_num]
        months.append({
            'name': month_name,
            'number': month_num,
            'artists': [],
            'track_count': 0,
            'artist_plays': Counter()
        })
    
    # Group tracks by month and count artist plays
    for item in tracks:
        track = item['track']
        artist_id = track['artists'][0]['id']
        artist_name = track['artists'][0]['name']
        
        # Parse the played_at timestamp
        played_at = datetime.datetime.strptime(item['played_at'], "%Y-%m-%dT%H:%M:%S.%fZ")
        
        # Skip if not from the current year
        if played_at.year != current_year:
            continue
            
        # Add to monthly counts
        month_index = played_at.month - 1  # 0-based index
        months[month_index]['track_count'] += 1
        months[month_index]['artist_plays'][artist_id] += 1
    
    # Get the top 3 artists for each month
    for month in months:
        if month['artist_plays']:
            # Get top 3 artist IDs
            top_artist_ids = [artist_id for artist_id, _ in month['artist_plays'].most_common(3)]
            
            # Get detailed artist info
            for i, artist_id in enumerate(top_artist_ids):
                try:
                    artist_info = sp.artist(artist_id)
                    
                    # Get artist image or use placeholder
                    image_url = artist_info['images'][0]['url'] if artist_info['images'] else '/static/placeholder.png'
                    
                    # Get top genres (limit to 3)
                    top_genres = artist_info['genres'][:3] if artist_info['genres'] else []
                    
                    month['artists'].append({
                        'id': artist_id,
                        'name': artist_info['name'],
                        'image_url': image_url,
                        'popularity': artist_info['popularity'],
                        'play_count': month['artist_plays'][artist_id],
                        'top_genres': top_genres
                    })
                except Exception as e:
                    print(f"Error fetching artist {artist_id}: {e}")
                    continue
    
    return months

def create_visualizations(sp, top_artists_short, top_artists_medium, top_artists_long, monthly_data):
    """Create visualizations from processed data."""
    visualizations = {}
    
    # Create yearly top artists chart
    yearly_artist_plays = Counter()
    for month in monthly_data:
        for artist_id, count in month['artist_plays'].items():
            yearly_artist_plays[artist_id] += count
    
    # Get top 10 artists of the year
    top_yearly_artists = []
    for artist_id, count in yearly_artist_plays.most_common(10):
        try:
            artist_info = sp.artist(artist_id)
            top_yearly_artists.append({
                'id': artist_id,
                'name': artist_info['name'],
                'play_count': count
            })
        except:
            continue
    
    # Create year overview chart
    if top_yearly_artists:
        df_yearly = pd.DataFrame(top_yearly_artists)
        fig_yearly = px.bar(df_yearly, 
                           x='name', 
                           y='play_count', 
                           title=f'Your Top Artists of {datetime.datetime.now().year}',
                           labels={'name': 'Artist', 'play_count': 'Play Count'})
        fig_yearly.update_layout(xaxis_tickangle=-45)
        visualizations['yearly_artists'] = json.dumps(fig_yearly, cls=plotly.utils.PlotlyJSONEncoder)
    else:
        # Create empty chart if no data
        fig_yearly = px.bar(x=[], y=[], title=f'Your Top Artists of {datetime.datetime.now().year}')
        visualizations['yearly_artists'] = json.dumps(fig_yearly, cls=plotly.utils.PlotlyJSONEncoder)
    
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
                           title='Your Top Genres')
        visualizations['genres'] = json.dumps(fig_genres, cls=plotly.utils.PlotlyJSONEncoder)
    else:
        fig_genres = px.pie(values=[], names=[], title='Your Top Genres')
        visualizations['genres'] = json.dumps(fig_genres, cls=plotly.utils.PlotlyJSONEncoder)
    
    # Create monthly listening patterns chart
    monthly_counts = [month['track_count'] for month in monthly_data]
    month_names = [month['name'] for month in monthly_data]
    
    fig_patterns = px.line(x=month_names, 
                          y=monthly_counts, 
                          title='Your Listening Activity by Month',
                          labels={'x': 'Month', 'y': 'Tracks Played'})
    fig_patterns.update_layout(xaxis_tickangle=-45)
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