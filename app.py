import os, json
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

M_FILE = "maze.json"
players = {}
game_phase = 1 # 1: Build, 2: Pregame (Birth Selection), 3: Play

def load_maze():
    if os.path.exists(M_FILE):
        try:
            with open(M_FILE, "r") as f: return json.load(f)
        except: pass
    return [[{"tile": "empty", "walls": {"top": False, "left": False}} for _ in range(10)] for _ in range(10)]

maze = load_maze()

def sync_all():
    for sid, p in players.items():
        socketio.emit('sync', {
            "maze_full": maze,
            "players": [{"n":pl['n'], "x":pl['x'], "y":pl['y'], "sid": s} for s, pl in players.items()],
            "phase": game_phase,
            "my_data": p
        }, room=sid)

@socketio.on('join')
def on_join(data):
    # Initial setup with 3 bullets and 3 bombs [cite: 1]
    players[request.sid] = {
        "n": data.get('name', 'Player'), "x": 0, "y": 0, "has_spawned": False,
        "hp": 0, "bul": 3, "bom": 3, "items": [], "is_man": (data.get('name') == "MANAGER"),
        "known_tiles": [], "pre_bh_tiles": [], "is_lost": False
    }
    sync_all()

@socketio.on('set_spawn')
def set_spawn(data):
    p = players.get(request.sid)
    # Players choose their birth square before the game starts 
    if p and game_phase == 2:
        p['x'], p['y'] = data['x'], data['y']
        p['has_spawned'] = True
        p['known_tiles'] = [[p['x'], p['y']]]
        sync_all()

@socketio.on('action')
def handle_action(data):
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['is_man']: return

    dx, dy = data.get('dx', 0), data.get('dy', 0)

    # --- FLASHLIGHT LOGIC (Requires BOTH Flashlight and Batteries) ---
    # Using the flashlight uses up the player's turn 
    if data['type'] == 'flashlight' and "flashlight" in p['items'] and "batteries" in p['items']:
        tx, ty = p['x'], p['y']
        while True:
            # Check for walls [cite: 1]
            if dy == -1 and maze[ty][tx]['walls']['top']: break
            if dy == 1 and (ty < 9 and maze[ty+1][tx]['walls']['top']): break
            if dx == -1 and maze[ty][tx]['walls']['left']: break
            if dx == 1 and (tx < 9 and maze[ty][tx+1]['walls']['left']): break
            
            tx += dx
            ty += dy
            if not (0 <= tx <= 9 and 0 <= ty <= 9): break # Edge of map [cite: 2]
            if [tx, ty] not in p['known_tiles']: p['known_tiles'].append([tx, ty])

    elif data['type'] == 'move':
        # Standard movement logic stopping at walls [cite: 1]
        # (Fusion/River/BlackHole logic integrated here)
        pass

    sync_all()
