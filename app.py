from flask import Flask, request, jsonify
import hashlib
import time
import sqlite3
import os
from datetime import datetime
import requests
import threading

app = Flask(__name__)

# Configuration
API_KEY = os.environ.get('LASTFM_API_KEY', 'your-api-key-here')
API_SECRET = os.environ.get('LASTFM_API_SECRET', 'your-api-secret-here')
DB_PATH = os.environ.get('DB_PATH', '/data/scrobbles.db')
REAL_LASTFM_API = 'https://ws.audioscrobbler.com/2.0/'

# Retention configuration - convert to seconds
RETENTION_MAP = {
    'hour': 3600,
    'day': 86400,
    'week': 604800,
    'month': 2592000,
    'never': 0
}
RETENTION_PERIOD = os.environ.get('RETENTION_PERIOD', 'month').lower()
RETENTION_SECONDS = RETENTION_MAP.get(RETENTION_PERIOD, 2592000)  # Default to 1 month

# Initialize database
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scrobbles
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  artist TEXT NOT NULL,
                  track TEXT NOT NULL,
                  album TEXT,
                  timestamp INTEGER NOT NULL,
                  album_artist TEXT,
                  duration INTEGER,
                  track_number INTEGER,
                  mbid TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sessions
                 (token TEXT PRIMARY KEY,
                  username TEXT,
                  session_key TEXT,
                  created_at INTEGER)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON scrobbles(timestamp DESC)')
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def cleanup_old_scrobbles():
    """Remove scrobbles older than the retention period"""
    if RETENTION_SECONDS == 0:
        return  # Never delete
    
    try:
        cutoff_time = int(time.time()) - RETENTION_SECONDS
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM scrobbles WHERE timestamp < ?', (cutoff_time,))
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            print(f"🗑️  Cleaned up {deleted} scrobbles older than {RETENTION_PERIOD}")
    except Exception as e:
        print(f"Error during cleanup: {e}")

def periodic_cleanup():
    """Run cleanup every hour"""
    while True:
        time.sleep(3600)  # Sleep for 1 hour
        cleanup_old_scrobbles()

# Start cleanup thread
cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
cleanup_thread.start()
print(f"Retention policy: {RETENTION_PERIOD} ({RETENTION_SECONDS}s)")

def generate_signature(params, secret):
    """Generate Last.fm API signature"""
    sorted_params = sorted(params.items())
    sig_string = ''.join([f'{k}{v}' for k, v in sorted_params if k != 'format' and k != 'callback'])
    sig_string += secret
    return hashlib.md5(sig_string.encode('utf-8')).hexdigest()

def verify_signature(params, secret):
    """Verify Last.fm API signature"""
    if 'api_sig' not in params:
        return False
    provided_sig = params['api_sig']
    params_copy = {k: v for k, v in params.items() if k != 'api_sig'}
    expected_sig = generate_signature(params_copy, secret)
    return provided_sig == expected_sig

@app.route('/', methods=['GET', 'POST'])
@app.route('/2.0/', methods=['GET', 'POST'])
@app.route('/2.0', methods=['GET', 'POST'])
def api():
    # Last.fm API can send parameters in multiple ways
    if request.method == 'POST':
        # Try form data first
        if request.form:
            params = request.form.to_dict()
        # Try JSON body
        elif request.is_json:
            params = request.get_json()
        # Fall back to query string (Navidrome does this)
        elif request.args:
            params = request.args.to_dict()
        # Try parsing raw data as form-encoded
        else:
            try:
                from urllib.parse import parse_qs
                parsed = parse_qs(request.get_data(as_text=True))
                params = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
            except:
                params = {}
    else:
        params = request.args.to_dict()
    
    method = params.get('method', '')
    request_api_key = params.get('api_key', '')
    is_our_key = (request_api_key == API_KEY)
    
    # Debug logging
    print(f"{request.method} {request.path} - method: {method} - api_key_match: {is_our_key}")
    
    # If it's not our API key, or it's a method we don't handle, proxy to real Last.fm
    handled_methods = [
        'auth.getToken', 'auth.getSession',
        'track.scrobble', 'track.updateNowPlaying',
        'user.getRecentTracks', 'user.getInfo',
        'artist.getInfo', 'artist.getSimilar', 'artist.getTopTracks', 'artist.getTopAlbums',
        'album.getInfo', 'track.getInfo', 'track.getSimilar'
    ]
    
    if not is_our_key or (method and method not in handled_methods):
        print(f"→ Proxying to Last.fm")
        try:
            if request.method == 'POST':
                response = requests.post(REAL_LASTFM_API, params=params, timeout=10)
            else:
                response = requests.get(REAL_LASTFM_API, params=params, timeout=10)
            
            return response.content, response.status_code, {'Content-Type': response.headers.get('Content-Type', 'application/json')}
        except Exception as e:
            print(f"Error proxying to Last.fm: {e}")
            return jsonify({'error': 16, 'message': 'Service temporarily unavailable'}), 503
    
    # Handle authentication methods
    if method == 'auth.getToken':
        token = hashlib.md5(str(time.time()).encode()).hexdigest()
        conn = get_db()
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO sessions (token, created_at) VALUES (?, ?)',
                  (token, int(time.time())))
        conn.commit()
        conn.close()
        
        print(f"✓ Scrobbled {accepted} track(s)")
        return jsonify({'token': token})
    
    elif method == 'auth.getSession':
        if not verify_signature(params, API_SECRET):
            return jsonify({'error': 9, 'message': 'Invalid signature'}), 403
        
        token = params.get('token')
        session_key = hashlib.md5(f"{token}{time.time()}".encode()).hexdigest()
        username = params.get('username', 'navidrome-user')
        
        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE sessions SET session_key = ?, username = ? WHERE token = ?',
                  (session_key, username, token))
        conn.commit()
        conn.close()
        
        return jsonify({
            'session': {
                'name': username,
                'key': session_key,
                'subscriber': 0
            }
        })
    
    # Handle scrobble methods
    elif method == 'track.scrobble':
        if not verify_signature(params, API_SECRET):
            return jsonify({'error': 9, 'message': 'Invalid signature'}), 403
        
        # Handle batch scrobbles (offline sync)
        scrobbles = []
        i = 0
        while f'artist[{i}]' in params or 'artist' in params:
            if i == 0 and 'artist' in params:
                # Single scrobble
                scrobble = {
                    'artist': params.get('artist'),
                    'track': params.get('track'),
                    'timestamp': params.get('timestamp', str(int(time.time()))),
                    'album': params.get('album', ''),
                    'album_artist': params.get('albumArtist', ''),
                    'duration': params.get('duration', 0),
                    'track_number': params.get('trackNumber', 0),
                    'mbid': params.get('mbid', '')
                }
                scrobbles.append(scrobble)
                break
            elif f'artist[{i}]' in params:
                # Batch scrobble
                scrobble = {
                    'artist': params.get(f'artist[{i}]'),
                    'track': params.get(f'track[{i}]'),
                    'timestamp': params.get(f'timestamp[{i}]', str(int(time.time()))),
                    'album': params.get(f'album[{i}]', ''),
                    'album_artist': params.get(f'albumArtist[{i}]', ''),
                    'duration': params.get(f'duration[{i}]', 0),
                    'track_number': params.get(f'trackNumber[{i}]', 0),
                    'mbid': params.get(f'mbid[{i}]', '')
                }
                scrobbles.append(scrobble)
                i += 1
            else:
                break
        
        conn = get_db()
        c = conn.cursor()
        accepted = 0
        for scrobble in scrobbles:
            try:
                c.execute('''INSERT INTO scrobbles 
                           (artist, track, album, timestamp, album_artist, duration, track_number, mbid)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                         (scrobble['artist'], scrobble['track'], scrobble['album'],
                          int(scrobble['timestamp']), scrobble['album_artist'],
                          int(scrobble['duration']) if scrobble['duration'] else None,
                          int(scrobble['track_number']) if scrobble['track_number'] else None,
                          scrobble['mbid']))
                accepted += 1
            except Exception as e:
                print(f"Error inserting scrobble: {e}")
        
        conn.commit()
        conn.close()
        
        # Last.fm returns single object for 1 scrobble, array for multiple
        if accepted == 1:
            scrobble_response = {
                'artist': {'corrected': '0', '#text': scrobbles[0]['artist']},
                'timestamp': str(scrobbles[0]['timestamp']),
                'track': {'corrected': '0', '#text': scrobbles[0]['track']},
                'album': {'corrected': '0', '#text': scrobbles[0]['album']},
                'albumArtist': {'corrected': '0', '#text': scrobbles[0]['album_artist']},
                'ignoredMessage': {'code': '0', '#text': ''}
            }
        else:
            scrobble_response = []
            for scrobble in scrobbles:
                scrobble_response.append({
                    'artist': {'corrected': '0', '#text': scrobble['artist']},
                    'timestamp': str(scrobble['timestamp']),
                    'track': {'corrected': '0', '#text': scrobble['track']},
                    'album': {'corrected': '0', '#text': scrobble['album']},
                    'albumArtist': {'corrected': '0', '#text': scrobble['album_artist']},
                    'ignoredMessage': {'code': '0', '#text': ''}
                })
        
        return jsonify({
            'scrobbles': {
                '@attr': {'accepted': accepted, 'ignored': 0},
                'scrobble': scrobble_response
            }
        })
    
    elif method == 'track.updateNowPlaying':
        if not verify_signature(params, API_SECRET):
            return jsonify({'error': 9, 'message': 'Invalid signature'}), 403
        
        # Just acknowledge, we don't store now playing
        return jsonify({
            'nowplaying': {
                'artist': {'#text': params.get('artist', '')},
                'track': {'#text': params.get('track', '')},
                'album': {'#text': params.get('album', '')},
                'ignoredMessage': {'code': '0'}
            }
        })
    
    # Handle read methods for multi-scrobbler
    elif method == 'user.getRecentTracks':
        username = params.get('user', 'navidrome-user')
        limit = int(params.get('limit', 50))
        page = int(params.get('page', 1))
        from_time = params.get('from')
        to_time = params.get('to')
        
        conn = get_db()
        c = conn.cursor()
        
        query = 'SELECT * FROM scrobbles WHERE 1=1'
        query_params = []
        
        if from_time:
            query += ' AND timestamp >= ?'
            query_params.append(int(from_time))
        if to_time:
            query += ' AND timestamp <= ?'
            query_params.append(int(to_time))
        
        query += ' ORDER BY timestamp DESC LIMIT ? OFFSET ?'
        query_params.extend([limit, (page - 1) * limit])
        
        c.execute(query, query_params)
        scrobbles = c.fetchall()
        
        # Get total count
        count_query = 'SELECT COUNT(*) FROM scrobbles WHERE 1=1'
        count_params = []
        if from_time:
            count_query += ' AND timestamp >= ?'
            count_params.append(int(from_time))
        if to_time:
            count_query += ' AND timestamp <= ?'
            count_params.append(int(to_time))
        
        c.execute(count_query, count_params)
        total = c.fetchone()[0]
        conn.close()
        
        tracks = []
        for s in scrobbles:
            track = {
                'artist': {'#text': s['artist'], 'mbid': ''},
                'name': s['track'],
                'album': {'#text': s['album'] or '', 'mbid': ''},
                'date': {'uts': str(s['timestamp']), '#text': datetime.fromtimestamp(s['timestamp']).strftime('%d %b %Y, %H:%M')},
                'mbid': s['mbid'] or ''
            }
            tracks.append(track)
        
        return jsonify({
            'recenttracks': {
                'track': tracks,
                '@attr': {
                    'user': username,
                    'page': str(page),
                    'perPage': str(limit),
                    'totalPages': str((total + limit - 1) // limit),
                    'total': str(total)
                }
            }
        })
    
    elif method == 'user.getInfo':
        username = params.get('user', 'navidrome-user')
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM scrobbles')
        playcount = c.fetchone()[0]
        conn.close()
        
        return jsonify({
            'user': {
                'name': username,
                'playcount': str(playcount),
                'registered': {'unixtime': '1577836800'},
                'country': 'US',
                'age': '0',
                'gender': 'n',
                'subscriber': '0'
            }
        })
    
    # Handle metadata methods (return empty responses - we don't store this data)
    elif method in ['artist.getInfo', 'artist.getSimilar', 'artist.getTopTracks', 'artist.getTopAlbums',
                     'album.getInfo', 'track.getInfo', 'track.getSimilar']:
        # Return minimal valid response to satisfy Navidrome
        return jsonify({})
    
    else:
        return jsonify({'error': 3, 'message': f'Invalid method - {method}'}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)