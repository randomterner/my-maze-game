import os, json
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

M_FILE = "maze.json"
players = {}
game_phase = 1 
game_logs = []
winner = None

def load_maze():
    if os.path.exists(M_FILE):
        try:
            with open(M_FILE, "r") as f: return json.load(f)
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
        "known_tiles": [], "is_lost": False
    }
    add_log(f"{name} הצטרף למבוך")
    sync_all()

@socketio.on('action')
def handle_action(data):
    global winner
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['hp'] >= 5 or p['is_man'] or winner: return
    
    act = data.get('type')
    dx, dy = data.get('dx', 0), data.get('dy', 0)

    # --- SHOOTING (Bullets) ---
    if act == 'shoot' and p['bul'] > 0:
        p['bul'] -= 1
        tx, ty = p['x'], p['y']
        hit = False
        while 0 <= tx <= 9 and 0 <= ty <= 9:
            # Check for wall hit
            if dy == -1 and maze[ty][tx]['walls']['top']: break
            if dy == 1 and ty < 9 and maze[ty+1][tx]['walls']['top']: break
            if dx == -1 and maze[ty][tx]['walls']['left']: break
            if dx == 1 and tx < 9 and maze[ty][tx+1]['walls']['left']: break
            
            tx += dx; ty += dy
            # Check for player hit
            for sid, other in players.items():
                if other['x'] == tx and other['y'] == ty and not other['is_man'] and other['hp'] < 5:
                    other['hp'] += 1
                    add_log(f"{p['n']} ירה ופגע ב-{other['n']}!")
                    hit = True; break
            if hit: break
        if not hit: add_log(f"{p['n']} ירה לכיוון ריק")

    # --- BOMB ---
    elif act == 'bomb' and p['bom'] > 0:
        p['bom'] -= 1
        if dy == -1: maze[p['y']][p['x']]['walls']['top'] = False
        elif dy == 1 and p['y'] < 9: maze[p['y']+1][p['x']]['walls']['top'] = False
        elif dx == -1: maze[p['y']][p['x']]['walls']['left'] = False
        elif dx == 1 and p['x'] < 9: maze[p['y']][p['x']+1]['walls']['left'] = False
        add_log(f"{p['n']} פוצץ קיר!")

    # --- MOVE ---
    elif act == 'move':
        blocked = False
        if dy == -1 and maze[p['y']][p['x']]['walls']['top']: blocked = True
        elif dy == 1 and p['y'] < 9 and maze[p['y']+1][p['x']]['walls']['top']: blocked = True
        elif dx == -1 and maze[p['y']][p['x']]['walls']['left']: blocked = True
        elif dx == 1 and p['x'] < 9 and maze[p['y']][p['x']+1]['walls']['left']: blocked = True
        
        if not blocked:
            p['x'] += dx; p['y'] += dy
            tile = maze[p['y']][p['x']]['tile']
            if tile == "monster":
                p['bul'] += 1; p['bom'] += 1
                add_log(f"{p['n']} מצא מפלצת! +ציוד ותור נוסף")
                sync_all(); return # Extra turn
            elif tile == "devil":
                p['hp'] += 1; p['bul'] = max(0, p['bul']-1); p['bom'] = max(0, p['bom']-1)
                add_log(f"{p['n']} נפגע מהשטן")
            elif tile in ["treasure", "fake_treasure", "flashlight", "batteries", "boat", "raft"]:
                p['items'].append(tile)
                maze[p['y']][p['x']]['tile'] = "empty"
                add_log(f"{p['n']} מצא {tile}")
            elif tile == "exit" and "treasure" in p['items']:
                winner = p['n']
            if [p['x'], p['y']] not in p['known_tiles']: p['known_tiles'].append([p['x'], p['y']])

    sync_all()

@socketio.on('set_phase')
def set_phase(d): global game_phase; game_phase = int(d['phase']); sync_all()
@socketio.on('save_maze')
def save_maze(d): 
    global maze
    if game_phase < 3: maze = d['maze']; sync_all()
@socketio.on('set_spawn')
def set_spawn(d):
    p = players.get(request.sid)
    if p and game_phase == 2:
        p['x'], p['y'] = d['x'], d['y']
        p['has_spawned'] = True
        p['known_tiles'] = [[p['x'], p['y']]]
        sync_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8080)
