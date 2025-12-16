from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from authlib.integrations.flask_client import OAuth
import sqlite3
import os
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'yearend-party-2025-secret-key-change-me')
DB_PATH = os.environ.get('DB_PATH', 'party.db')
ADMIN_KEY = os.environ.get('ADMIN_KEY', 'hosting2025!')
ADMIN_EMAILS = os.environ.get('ADMIN_EMAILS', '').split(',')  # 관리자 이메일 목록

# Google OAuth 설정
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            google_id TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            picture TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS attendees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id)
        );
        CREATE TABLE IF NOT EXISTS places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            place_id INTEGER NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (place_id) REFERENCES places(id),
            UNIQUE(user_id)
        );
    ''')
    conn.commit()
    conn.close()

def get_current_user():
    """현재 로그인한 사용자 정보 반환"""
    if 'user' not in session:
        return None
    return session['user']

def is_admin():
    """관리자 여부 확인"""
    user = get_current_user()
    if not user:
        return False
    return user.get('email') in ADMIN_EMAILS or session.get('admin_key_verified')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_user():
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_admin():
            return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
        return f(*args, **kwargs)
    return decorated_function

# ===== Auth Routes =====
@app.route('/login')
def login():
    if get_current_user():
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/login/google')
def login_google():
    redirect_uri = url_for('auth_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/callback')
def auth_callback():
    try:
        token = google.authorize_access_token()
        userinfo = token.get('userinfo')

        if not userinfo:
            return redirect(url_for('login'))

        conn = get_db()
        # 사용자 조회 또는 생성
        user = conn.execute('SELECT * FROM users WHERE google_id=?', (userinfo['sub'],)).fetchone()

        if not user:
            conn.execute('''
                INSERT INTO users (google_id, email, name, picture) VALUES (?, ?, ?, ?)
            ''', (userinfo['sub'], userinfo['email'], userinfo.get('name', ''), userinfo.get('picture', '')))
            conn.commit()
            user = conn.execute('SELECT * FROM users WHERE google_id=?', (userinfo['sub'],)).fetchone()

        conn.close()

        session['user'] = {
            'id': user['id'],
            'google_id': user['google_id'],
            'email': user['email'],
            'name': user['name'],
            'picture': user['picture']
        }

        return redirect(url_for('index'))
    except Exception as e:
        print(f"Auth error: {e}")
        return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ===== Main Routes =====
@app.route('/')
def index():
    conn = get_db()
    stats = {
        'total': conn.execute('SELECT COUNT(*) FROM attendees').fetchone()[0],
        'attending': conn.execute("SELECT COUNT(*) FROM attendees WHERE status='ATTENDING'").fetchone()[0],
        'not_attending': conn.execute("SELECT COUNT(*) FROM attendees WHERE status='NOT_ATTENDING'").fetchone()[0]
    }
    conn.close()
    return render_template('index.html', stats=stats, user=get_current_user())

@app.route('/rsvp', methods=['GET', 'POST'])
@login_required
def rsvp():
    user = get_current_user()
    message = None
    msg_type = None

    conn = get_db()
    current_status = conn.execute('SELECT status FROM attendees WHERE user_id=?', (user['id'],)).fetchone()

    if request.method == 'POST':
        status = request.form.get('status', '')

        if status not in ['ATTENDING', 'NOT_ATTENDING']:
            message = '참석 여부를 선택해주세요.'
            msg_type = 'error'
        else:
            try:
                conn.execute('''
                    INSERT INTO attendees (user_id, status, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at
                ''', (user['id'], status, datetime.now()))
                conn.commit()
                message = '참석 여부가 등록되었습니다!'
                msg_type = 'success'
                current_status = {'status': status}
            except Exception as e:
                message = f'오류가 발생했습니다: {str(e)}'
                msg_type = 'error'

    conn.close()
    return render_template('rsvp.html', message=message, msg_type=msg_type,
                          user=user, current_status=current_status['status'] if current_status else None)

@app.route('/attendees')
def attendees():
    filter_val = request.args.get('filter', 'all')
    conn = get_db()

    base_query = '''
        SELECT a.*, u.name, u.email, u.picture
        FROM attendees a JOIN users u ON a.user_id = u.id
    '''

    if filter_val == 'attending':
        rows = conn.execute(base_query + " WHERE a.status='ATTENDING' ORDER BY a.updated_at DESC").fetchall()
    elif filter_val == 'not_attending':
        rows = conn.execute(base_query + " WHERE a.status='NOT_ATTENDING' ORDER BY a.updated_at DESC").fetchall()
    else:
        rows = conn.execute(base_query + " ORDER BY a.updated_at DESC").fetchall()

    conn.close()
    return render_template('attendees.html', attendees=rows, filter=filter_val, user=get_current_user(), is_admin=is_admin())

@app.route('/places', methods=['GET', 'POST'])
def places():
    user = get_current_user()
    add_message = None
    vote_message = None

    if request.method == 'POST' and user:
        action = request.form.get('action')
        conn = get_db()

        if action == 'add_place':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()

            if not title or len(title) > 60:
                add_message = ('장소명을 1~60자로 입력해주세요.', 'error')
            else:
                try:
                    conn.execute('INSERT INTO places (user_id, title, description) VALUES (?, ?, ?)',
                               (user['id'], title, description or None))
                    conn.commit()
                    add_message = ('장소가 추가되었습니다!', 'success')
                except Exception as e:
                    add_message = (f'오류: {str(e)}', 'error')

        elif action == 'vote':
            place_id = request.form.get('place_id')

            if not place_id:
                vote_message = ('장소를 선택해주세요.', 'error')
            else:
                try:
                    conn.execute('''
                        INSERT INTO votes (user_id, place_id, updated_at) VALUES (?, ?, ?)
                        ON CONFLICT(user_id) DO UPDATE SET place_id=excluded.place_id, updated_at=excluded.updated_at
                    ''', (user['id'], int(place_id), datetime.now()))
                    conn.commit()
                    vote_message = ('투표가 완료되었습니다!', 'success')
                except Exception as e:
                    vote_message = (f'오류: {str(e)}', 'error')

        conn.close()

    conn = get_db()
    places_list = conn.execute('''
        SELECT p.*, u.name as creator_name, COUNT(v.id) as vote_count
        FROM places p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN votes v ON p.id = v.place_id
        GROUP BY p.id ORDER BY vote_count DESC, p.created_at DESC
    ''').fetchall()
    max_votes = max([p['vote_count'] for p in places_list], default=0)

    # 현재 사용자의 투표 상태
    user_vote = None
    if user:
        user_vote = conn.execute('SELECT place_id FROM votes WHERE user_id=?', (user['id'],)).fetchone()

    conn.close()
    return render_template('places.html', places=places_list, max_votes=max_votes,
                          add_message=add_message, vote_message=vote_message,
                          user=user, user_vote=user_vote['place_id'] if user_vote else None, is_admin=is_admin())

# ===== Admin Routes =====
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    user = get_current_user()
    message = None

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'admin_key_login':
            key = request.form.get('key', '')
            if key == ADMIN_KEY:
                session['admin_key_verified'] = True
                message = ('관리자 인증 성공!', 'success')
            else:
                message = ('비밀키가 틀렸습니다.', 'error')

        elif action == 'admin_logout':
            session.pop('admin_key_verified', None)
            message = ('관리자 로그아웃 되었습니다.', 'success')

        elif is_admin():
            conn = get_db()

            if action == 'delete_attendee':
                attendee_id = request.form.get('id')
                conn.execute('DELETE FROM attendees WHERE id=?', (attendee_id,))
                conn.commit()
                message = ('참석자가 삭제되었습니다.', 'success')

            elif action == 'delete_place':
                place_id = request.form.get('id')
                conn.execute('DELETE FROM votes WHERE place_id=?', (place_id,))
                conn.execute('DELETE FROM places WHERE id=?', (place_id,))
                conn.commit()
                message = ('장소가 삭제되었습니다.', 'success')

            elif action == 'delete_vote':
                vote_id = request.form.get('id')
                conn.execute('DELETE FROM votes WHERE id=?', (vote_id,))
                conn.commit()
                message = ('투표가 삭제되었습니다.', 'success')

            elif action == 'delete_all_attendees':
                conn.execute('DELETE FROM attendees')
                conn.commit()
                message = ('모든 참석자가 삭제되었습니다.', 'success')

            elif action == 'delete_all_places':
                conn.execute('DELETE FROM votes')
                conn.execute('DELETE FROM places')
                conn.commit()
                message = ('모든 장소와 투표가 삭제되었습니다.', 'success')

            elif action == 'delete_all_votes':
                conn.execute('DELETE FROM votes')
                conn.commit()
                message = ('모든 투표가 삭제되었습니다.', 'success')

            conn.close()
        else:
            message = ('관리자 권한이 필요합니다.', 'error')

    # 데이터 조회
    conn = get_db()
    attendees_list = conn.execute('''
        SELECT a.*, u.name, u.email FROM attendees a JOIN users u ON a.user_id = u.id ORDER BY a.updated_at DESC
    ''').fetchall()
    places_list = conn.execute('''
        SELECT p.*, u.name as creator_name FROM places p JOIN users u ON p.user_id = u.id ORDER BY p.created_at DESC
    ''').fetchall()
    votes_list = conn.execute('''
        SELECT v.*, u.name as voter_name, u.email as voter_email, p.title as place_title
        FROM votes v
        JOIN users u ON v.user_id = u.id
        JOIN places p ON v.place_id = p.id
        ORDER BY v.updated_at DESC
    ''').fetchall()

    stats = {
        'attendees': len(attendees_list),
        'places': len(places_list),
        'votes': len(votes_list),
    }
    conn.close()

    return render_template('admin.html', user=user, is_admin=is_admin(), message=message,
                          stats=stats, attendees=attendees_list, places=places_list, votes=votes_list)

# ===== API Routes =====
@app.route('/api/stats')
def api_stats():
    conn = get_db()
    stats = {
        'total': conn.execute('SELECT COUNT(*) FROM attendees').fetchone()[0],
        'attending': conn.execute("SELECT COUNT(*) FROM attendees WHERE status='ATTENDING'").fetchone()[0],
        'notAttending': conn.execute("SELECT COUNT(*) FROM attendees WHERE status='NOT_ATTENDING'").fetchone()[0]
    }
    conn.close()
    return jsonify(stats)

@app.route('/api/attendees')
def api_attendees():
    conn = get_db()
    filter_val = request.args.get('filter')

    base_query = '''
        SELECT a.id, a.status, a.updated_at, u.name, u.email
        FROM attendees a JOIN users u ON a.user_id = u.id
    '''

    if filter_val == 'attending':
        rows = conn.execute(base_query + " WHERE a.status='ATTENDING' ORDER BY a.updated_at DESC").fetchall()
    elif filter_val == 'not_attending':
        rows = conn.execute(base_query + " WHERE a.status='NOT_ATTENDING' ORDER BY a.updated_at DESC").fetchall()
    else:
        rows = conn.execute(base_query + " ORDER BY a.updated_at DESC").fetchall()

    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/places')
def api_places():
    conn = get_db()
    rows = conn.execute('''
        SELECT p.id, p.title, p.description, p.created_at, u.name as creator_name, COUNT(v.id) as voteCount
        FROM places p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN votes v ON p.id = v.place_id
        GROUP BY p.id ORDER BY voteCount DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/my/rsvp', methods=['DELETE'])
@login_required
def api_delete_my_rsvp():
    user = get_current_user()
    conn = get_db()
    conn.execute('DELETE FROM attendees WHERE user_id=?', (user['id'],))
    conn.commit()
    conn.close()
    return jsonify({'message': '참석 등록이 취소되었습니다.'})

@app.route('/api/my/vote', methods=['DELETE'])
@login_required
def api_delete_my_vote():
    user = get_current_user()
    conn = get_db()
    conn.execute('DELETE FROM votes WHERE user_id=?', (user['id'],))
    conn.commit()
    conn.close()
    return jsonify({'message': '투표가 취소되었습니다.'})

# Initialize DB on import
init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
