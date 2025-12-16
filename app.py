from flask import Flask, render_template, request, jsonify, redirect, url_for
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
DB_PATH = os.environ.get('DB_PATH', 'party.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS attendees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voter_name TEXT UNIQUE NOT NULL,
            place_id INTEGER NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (place_id) REFERENCES places(id)
        );
    ''')
    conn.commit()
    conn.close()

@app.route('/')
def index():
    conn = get_db()
    stats = {
        'total': conn.execute('SELECT COUNT(*) FROM attendees').fetchone()[0],
        'attending': conn.execute("SELECT COUNT(*) FROM attendees WHERE status='ATTENDING'").fetchone()[0],
        'not_attending': conn.execute("SELECT COUNT(*) FROM attendees WHERE status='NOT_ATTENDING'").fetchone()[0]
    }
    conn.close()
    return render_template('index.html', stats=stats)

@app.route('/rsvp', methods=['GET', 'POST'])
def rsvp():
    message = None
    msg_type = None
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        status = request.form.get('status', '')

        if not name or len(name) > 30:
            message = '이름을 1~30자로 입력해주세요.'
            msg_type = 'error'
        elif status not in ['ATTENDING', 'NOT_ATTENDING']:
            message = '참석 여부를 선택해주세요.'
            msg_type = 'error'
        else:
            conn = get_db()
            try:
                conn.execute('''
                    INSERT INTO attendees (name, status, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at
                ''', (name, status, datetime.now()))
                conn.commit()
                message = f'{name}님의 참석 여부가 등록되었습니다!'
                msg_type = 'success'
            except Exception as e:
                message = f'오류가 발생했습니다: {str(e)}'
                msg_type = 'error'
            finally:
                conn.close()

    return render_template('rsvp.html', message=message, msg_type=msg_type)

@app.route('/attendees')
def attendees():
    filter_val = request.args.get('filter', 'all')
    conn = get_db()

    if filter_val == 'attending':
        rows = conn.execute("SELECT * FROM attendees WHERE status='ATTENDING' ORDER BY updated_at DESC").fetchall()
    elif filter_val == 'not_attending':
        rows = conn.execute("SELECT * FROM attendees WHERE status='NOT_ATTENDING' ORDER BY updated_at DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM attendees ORDER BY updated_at DESC").fetchall()

    conn.close()
    return render_template('attendees.html', attendees=rows, filter=filter_val)

@app.route('/places', methods=['GET', 'POST'])
def places():
    add_message = None
    vote_message = None

    if request.method == 'POST':
        action = request.form.get('action')
        conn = get_db()

        if action == 'add_place':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()

            if not title or len(title) > 60:
                add_message = ('장소명을 1~60자로 입력해주세요.', 'error')
            else:
                try:
                    conn.execute('INSERT INTO places (title, description) VALUES (?, ?)',
                               (title, description or None))
                    conn.commit()
                    add_message = ('장소가 추가되었습니다!', 'success')
                except Exception as e:
                    add_message = (f'오류: {str(e)}', 'error')

        elif action == 'vote':
            voter_name = request.form.get('voter_name', '').strip()
            place_id = request.form.get('place_id')

            if not voter_name or len(voter_name) > 30:
                vote_message = ('이름을 1~30자로 입력해주세요.', 'error')
            elif not place_id:
                vote_message = ('장소를 선택해주세요.', 'error')
            else:
                try:
                    conn.execute('''
                        INSERT INTO votes (voter_name, place_id, updated_at) VALUES (?, ?, ?)
                        ON CONFLICT(voter_name) DO UPDATE SET place_id=excluded.place_id, updated_at=excluded.updated_at
                    ''', (voter_name, int(place_id), datetime.now()))
                    conn.commit()
                    vote_message = ('투표가 완료되었습니다!', 'success')
                except Exception as e:
                    vote_message = (f'오류: {str(e)}', 'error')

        conn.close()

    conn = get_db()
    places_list = conn.execute('''
        SELECT p.*, COUNT(v.id) as vote_count
        FROM places p LEFT JOIN votes v ON p.id = v.place_id
        GROUP BY p.id ORDER BY vote_count DESC, p.created_at DESC
    ''').fetchall()
    max_votes = max([p['vote_count'] for p in places_list], default=0)
    conn.close()

    return render_template('places.html', places=places_list, max_votes=max_votes,
                          add_message=add_message, vote_message=vote_message)

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

@app.route('/api/attendees', methods=['GET', 'POST'])
def api_attendees():
    conn = get_db()

    if request.method == 'POST':
        data = request.get_json()
        name = data.get('name', '').strip()
        status = data.get('status', '')

        if not name or len(name) > 30:
            return jsonify({'error': '이름을 1~30자로 입력해주세요.'}), 400
        if status not in ['ATTENDING', 'NOT_ATTENDING']:
            return jsonify({'error': '참석 여부를 선택해주세요.'}), 400

        try:
            conn.execute('''
                INSERT INTO attendees (name, status, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at
            ''', (name, status, datetime.now()))
            conn.commit()
            row = conn.execute('SELECT * FROM attendees WHERE name=?', (name,)).fetchone()
            conn.close()
            return jsonify(dict(row))
        except Exception as e:
            conn.close()
            return jsonify({'error': str(e)}), 500

    filter_val = request.args.get('filter')
    if filter_val == 'attending':
        rows = conn.execute("SELECT * FROM attendees WHERE status='ATTENDING' ORDER BY updated_at DESC").fetchall()
    elif filter_val == 'not_attending':
        rows = conn.execute("SELECT * FROM attendees WHERE status='NOT_ATTENDING' ORDER BY updated_at DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM attendees ORDER BY updated_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/places', methods=['GET', 'POST'])
def api_places():
    conn = get_db()

    if request.method == 'POST':
        data = request.get_json()
        title = data.get('title', '').strip()
        description = data.get('description', '').strip() if data.get('description') else None

        if not title or len(title) > 60:
            return jsonify({'error': '장소명을 1~60자로 입력해주세요.'}), 400

        try:
            conn.execute('INSERT INTO places (title, description) VALUES (?, ?)', (title, description))
            conn.commit()
            row = conn.execute('SELECT * FROM places ORDER BY id DESC LIMIT 1').fetchone()
            conn.close()
            return jsonify(dict(row))
        except Exception as e:
            conn.close()
            return jsonify({'error': str(e)}), 500

    rows = conn.execute('''
        SELECT p.*, COUNT(v.id) as voteCount
        FROM places p LEFT JOIN votes v ON p.id = v.place_id
        GROUP BY p.id ORDER BY voteCount DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/votes', methods=['POST'])
def api_votes():
    data = request.get_json()
    voter_name = data.get('voterName', '').strip()
    place_id = data.get('placeId')

    if not voter_name or len(voter_name) > 30:
        return jsonify({'error': '이름을 1~30자로 입력해주세요.'}), 400
    if not place_id:
        return jsonify({'error': '장소를 선택해주세요.'}), 400

    conn = get_db()
    try:
        conn.execute('''
            INSERT INTO votes (voter_name, place_id, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(voter_name) DO UPDATE SET place_id=excluded.place_id, updated_at=excluded.updated_at
        ''', (voter_name, int(place_id), datetime.now()))
        conn.commit()
        row = conn.execute('SELECT * FROM votes WHERE voter_name=?', (voter_name,)).fetchone()
        conn.close()
        return jsonify(dict(row))
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

# Initialize DB on import (works with gunicorn)
init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
