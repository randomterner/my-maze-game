import os, json
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'maze_secret_123'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Global variables to stay in RAM for Render
maze = [[{"tile": "empty", "walls": {"top": False, "left": False}} for _ in range(10)] for _ in range(10)]
players = {}
game_phase = 1 
game_logs = []
winner = None

def sync_all():
    # Determine winner
    p_list = [p for p in players.values() if not p['is_man']]
    alive = [p for p in p_list if p['injuries'] < 5]
    curr_winner = winner
    if len(alive) == 1 and len(p_list) > 1:
        curr_winner = alive[0]['n']

    # Broadcast to EVERYONE
    socketio.emit('sync', {
        "maze": maze,
        "players": [{"n":pl['n'], "x":pl['x'], "y":pl['y'], "injuries":pl['injuries'], "dead":pl['injuries']>=5} for pl in players.values()],
        "phase": game_phase,
        "logs": game_logs,
        "winner": curr_winner
    })

@app.route('/')
def index(): return render_template('index.html')

@app.route('/manager')
def manager(): return render_template('manager.html')

@socketio.on('join')
def on_join(data):
    name = data.get('name', 'Player')
    players[request.sid] = {
        "n": name, "x": 0, "y": 0, "has_spawned": False, 
        "injuries": 0, "bul": 3, "bom": 3, "items": [], 
        "is_man": (name == "MANAGER"), "known_tiles": [], "is_lost": False
    }
    sync_all()

@socketio.on('set_phase')
def set_phase(data):
    global game_phase
    try:
        game_phase = int(data['phase'])
        sync_all()
    except: pass

@socketio.on('save_maze')
def save_maze(data):
    global maze
    if game_phase < 3:
        maze = data['maze']
        sync_all()

@socketio.on('action')
def handle_action(data):
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['is_man']: return
    # (Movement/Bullet logic remains same as previous working version)
    p['x'] = max(0, min(9, p['x'] + data.get('dx', 0)))
    p['y'] = max(0, min(9, p['y'] + data.get('dy', 0)))
    if [p['x'], p['y']] not in p['known_tiles']: p['known_tiles'].append([p['x'], p['y']])
    sync_all()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)
