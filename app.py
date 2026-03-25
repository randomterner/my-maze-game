import os, json
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

M_FILE = "maze.json"
players = {}
game_phase = 1 # 1: Build, 2: Spawn, 3: Play
game_logs = []
winner = None

def load_maze():
    if os.path.exists(M_FILE):
        try:
            with open(M_FILE, "r") as f:
                data = json.load(f)
                if len(data) == 10: return data
        except: pass
    return [[{"tile": "empty", "walls": {"top": False, "left": False}} for _ in range(10)] for _ in range(10)]

maze = load_maze()

def add_log(msg):
    game_logs.insert(0, msg)
    if len(game_logs) > 12: game_logs.pop()

def sync_all():
    alive = [p for p in players.values() if not p['is_man'] and p['hp'] < 5]
    curr_winner = winner
    if len(alive) == 1 and len([p for p in players.values() if not p['is_man']]) > 1:
        curr_winner = alive[0]['n']

    for sid, p in players.items():
        socketio.emit('sync', {
            "maze": maze,
            "players": [{"n":pl['n'], "x":pl['x'], "y":pl['y'], "hp":pl['hp'], "dead":pl['hp']>=5} for pl in players.values()],
            "phase": game_phase,
            "my_data": p,
            "is_spectator": p['is_man'] or p['hp'] >= 5,
            "logs": game_logs,
            "winner": curr_winner
        }, room=sid)

@app.route('/')
def index(): return render_template('index.html')

@app.route('/manager')
def manager(): return render_template('manager.html')

@socketio.on('join')
def on_join(data):
    name = data.get('name', 'Player')
    players[request.sid] = {
        "n": name, "x": 0, "y": 0, "has_spawned": False,
        "hp": 0, "bul": 3, "bom": 3, "items": [], "is_man": (name == "MANAGER"),
        "known_tiles": [], "pre_bh_tiles": [], "is_lost": False
    }
    add_log(f"{name} הצטרף")
    sync_all()

@socketio.on('set_phase')
def set_phase(data):
    global game_phase
    game_phase = int(data['phase'])
    sync_all()

@socketio.on('save_maze')
def save_maze(data):
    global maze
    if game_phase < 3:
        maze = data['maze']
        sync_all()

@socketio.on('reset_game')
def reset_game():
    global game_phase, game_logs, winner, maze
    game_phase = 1
    game_logs = []
    winner = None
    maze = [[{"tile": "empty", "walls": {"top": False, "left": False}} for _ in range(10)] for _ in range(10)]
    for sid in players:
        players[sid].update({"x":0, "y":0, "hp":0, "items":[], "known_tiles":[], "has_spawned":False, "is_lost":False})
    sync_all()

@socketio.on('action')
def handle_action(data):
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['hp'] >= 5 or p['is_man']: return
    p['x'] = max(0, min(9, p['x'] + data.get('dx', 0)))
    p['y'] = max(0, min(9, p['y'] + data.get('dy', 0)))
    if [p['x'], p['y']] not in p['known_tiles']: p['known_tiles'].append([p['x'], p['y']])
    sync_all()

@socketio.on('set_spawn')
def set_spawn(data):
    p = players.get(request.sid)
    if p and game_phase == 2:
        p['x'], p['y'] = data['x'], data['y']
        p['has_spawned'] = True
        p['known_tiles'] = [[p['x'], p['y']]]
        sync_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8080)
