import os, json, random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

M_FILE = "maze.json"
players = {}
game_phase = 1  # 1: Build, 2: Pregame, 3: Play, 4: End
game_logs = []

def load_maze():
    if os.path.exists(M_FILE):
        try:
            with open(M_FILE, "r") as f: return json.load(f)
        except: pass
    return [[{"tile": "empty", "walls": {"top": False, "left": False}} for _ in range(10)] for _ in range(10)]

maze = load_maze()

def add_log(msg):
    game_logs.insert(0, msg)
    if len(game_logs) > 15: game_logs.pop()

def sync_all():
    for sid, p in players.items():
        socketio.emit('sync', {
            "maze_full": maze,
            "players": [{"n":pl['n'], "x":pl['x'], "y":pl['y'], "hp":pl['hp'], "sid": s} for s, pl in players.items()],
            "phase": game_phase,
            "my_data": p,
            "logs": game_logs
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
    add_log(f"השחקן {name} התחבר")
    sync_all()

@socketio.on('set_phase')
def set_phase(data):
    global game_phase
    game_phase = data['phase']
    add_log(f"המשחק עבר לשלב {game_phase}")
    sync_all()

@socketio.on('set_spawn')
def set_spawn(data):
    p = players.get(request.sid)
    if p and game_phase == 2:
        p['x'], p['y'] = data['x'], data['y']
        p['has_spawned'] = True
        p['known_tiles'] = [[p['x'], p['y']]]
        add_log(f"{p['n']} בחר נקודת לידה")
        sync_all()

@socketio.on('action')
def handle_action(data):
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['is_man']: return
    
    dx, dy = data.get('dx', 0), data.get('dy', 0)
    dirs = {(0,-1): "למעלה", (0,1): "למטה", (-1,0): "שמאלה", (1,0): "ימינה"}
    d_name = dirs.get((dx,dy), "מקום כלשהו")

    # --- FLASHLIGHT ---
    if data['type'] == 'flashlight' and "flashlight" in p['items'] and "batteries" in p['items']:
        add_log(f"{p['n']} השתמש בפנס לכיוון {d_name}")
        tx, ty = p['x'], p['y']
        while True:
            if dy == -1 and maze[ty][tx]['walls']['top']: break
            if dy == 1 and (ty < 9 and maze[ty+1][tx]['walls']['top']): break
            if dx == -1 and maze[ty][tx]['walls']['left']: break
            if dx == 1 and (tx < 9 and maze[ty][tx+1]['walls']['left']): break
            tx += dx; ty += dy
            if not (0 <= tx <= 9 and 0 <= ty <= 9): break
            if [tx, ty] not in p['known_tiles']: p['known_tiles'].append([tx, ty])

    # --- MOVE ---
    elif data['type'] == 'move':
        blocked = False
        if dy == -1 and maze[p['y']][p['x']]['walls']['top']: blocked = True
        elif dy == 1 and (p['y'] < 9 and maze[p['y']+1][p['x']]['walls']['top']): blocked = True
        elif dx == -1 and maze[p['y']][p['x']]['walls']['left']: blocked = True
        elif dx == 1 and (p['x'] < 9 and maze[p['y']][p['x']+1]['walls']['left']): blocked = True
        
        if blocked:
            add_log(f"{p['n']} נתקע בקיר {d_name}")
        else:
            p['x'] += dx; p['y'] += dy
            pos = [p['x'], p['y']]
            if pos not in p['known_tiles']: p['known_tiles'].append(pos)
            tile = maze[p['y']][p['x']]['tile']
            
            if tile == "empty": add_log(f"{p['n']} הלך {d_name} ומצא משבצת ריקה")
            else:
                add_log(f"{p['n']} הלך {d_name} ומצא {tile}!")
                if tile in ["flashlight", "batteries", "treasure", "boat", "raft"]:
                    p['items'].append(tile)
                    maze[p['y']][p['x']]['tile'] = "empty"
                elif tile == "black_hole":
                    socketio.emit('bh_event', {"sid": request.sid, "n": p['n']})

    sync_all()

@socketio.on('save_maze')
def save_maze(data):
    global maze; maze = data['maze']; sync_all()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)
