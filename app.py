import os, json
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

M_FILE = "maze.json"
players = {}
game_phase = 1 # 1: Build, 2: Pregame (Birth), 3: Play

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

@app.route('/')
def index(): return render_template('index.html')

@app.route('/manager')
def manager(): return render_template('manager.html')

@socketio.on('join')
def on_join(data):
    players[request.sid] = {
        "n": data.get('name', 'Player'), "x": 0, "y": 0, "has_spawned": False,
        "hp": 0, "bul": 3, "bom": 3, "items": [], "is_man": (data.get('name') == "MANAGER"),
        "known_tiles": [], "pre_bh_tiles": [], "is_lost": False
    }
    sync_all()

@socketio.on('set_spawn')
def set_spawn(data):
    p = players.get(request.sid)
    if p and game_phase == 2:
        p['x'], p['y'] = data['x'], data['y']
        p['has_spawned'] = True
        p['known_tiles'] = [[p['x'], p['y']]]
        sync_all()

@socketio.on('set_phase')
def set_phase(data):
    global game_phase
    game_phase = data['phase']
    sync_all()

@socketio.on('action')
def handle_action(data):
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['is_man']: return

    dx, dy = data.get('dx', 0), data.get('dy', 0)

    # --- FLASHLIGHT LOGIC (Stops at walls) ---
    if data['type'] == 'flashlight' and "flashlight" in p['items']:
        tx, ty = p['x'], p['y']
        while True:
            # Check for wall in the direction we are moving
            if dy == -1 and maze[ty][tx]['walls']['top']: break # Wall above
            if dy == 1 and (ty < 9 and maze[ty+1][tx]['walls']['top']): break # Wall below
            if dx == -1 and maze[ty][tx]['walls']['left']: break # Wall left
            if dx == 1 and (tx < 9 and maze[ty][tx+1]['walls']['left']): break # Wall right
            
            tx += dx
            ty += dy
            
            if not (0 <= tx <= 9 and 0 <= ty <= 9): break # Hit edge of map
            
            if [tx, ty] not in p['known_tiles']:
                p['known_tiles'].append([tx, ty])

    # --- MOVE LOGIC ---
    elif data['type'] == 'move':
        # Check walls for movement
        blocked = False
        if dy == -1 and maze[p['y']][p['x']]['walls']['top']: blocked = True
        elif dy == 1 and (p['y'] < 9 and maze[p['y']+1][p['x']]['walls']['top']): blocked = True
        elif dx == -1 and maze[p['y']][p['x']]['walls']['left']: blocked = True
        elif dx == 1 and (p['x'] < 9 and maze[p['y']][p['x']+1]['walls']['left']): blocked = True
        
        if not blocked:
            p['x'] = max(0, min(9, p['x'] + dx))
            p['y'] = max(0, min(9, p['y'] + dy))
            pos = [p['x'], p['y']]
            if pos not in p['known_tiles']: p['known_tiles'].append(pos)
            
            tile = maze[p['y']][p['x']]['tile']
            if tile == "flashlight":
                p['items'].append("flashlight")
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
