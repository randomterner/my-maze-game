from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import os, json, random

app = Flask(__name__)
app.config['SECRET_KEY'] = 'maze_2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

M_FILE = "maze.json"
players = {}
turn_idx = 0
game_started = False
winner_name = None
game_logs = []

def load_maze():
    if os.path.exists(M_FILE):
        try:
            with open(M_FILE, "r") as f: return json.load(f)
        except: pass
    return [[{"tile": "empty", "walls": {"top": False, "left": False}} for _ in range(10)] for _ in range(10)]

maze = load_maze()

def add_log(msg):
    game_logs.append(msg)
    if len(game_logs) > 10: game_logs.pop(0)

def sync_all():
    active = [p for p in players.values() if not p['is_man'] and p['hp'] < 5]
    curr_turn = active[turn_idx % len(active)]['n'] if active else "None"
    socketio.emit('sync', {
        "maze": maze,
        "players": [{"n":p['n'], "x":p['x'], "y":p['y'], "hp":p['hp'], "bul":p['bul'], "bom":p['bom']} for p in players.values()],
        "turn": curr_turn, "started": game_started, "winner": winner_name, "logs": game_logs
    })

@socketio.on('join')
def on_join(data):
    players[request.sid] = {
        "n": data.get('name', 'Player'), "x": 0, "y": 0, "hp": 0, 
        "bul": 3, "bom": 3, "items": [], "is_man": (data.get('name') == "MANAGER")
    }
    sync_all()

@socketio.on('action')
def handle_action(data):
    global turn_idx, winner_name
    p = players.get(request.sid)
    if not p or not game_started or p['is_man'] or winner_name: return

    active = [pl for pl in players.values() if not pl['is_man'] and pl['hp'] < 5]
    if not active or active[turn_idx % len(active)]['n'] != p['n']: return

    action_done = False
    extra_turn = False
    dx, dy = data.get('dx', 0), data.get('dy', 0)

    if data['type'] == 'move':
        blocked = False
        if dy == -1 and (p['y'] == 0 or maze[p['y']][p['x']]['walls']['top']): blocked = True
        elif dy == 1 and (p['y'] == 9 or maze[p['y']+1][p['x']]['walls']['top']): blocked = True
        elif dx == -1 and (p['x'] == 0 or maze[p['y']][p['x']]['walls']['left']): blocked = True
        elif dx == 1 and (p['x'] == 9 or maze[p['y']][p['x']+1]['walls']['left']): blocked = True
        
        if not blocked:
            p['x'] += dx; p['y'] += dy; action_done = True
            tile = maze[p['y']][p['x']]['tile']
            
            # Tile Logic [cite: 2, 3, 4, 5, 6]
            if tile in ["treasure", "fake_treasure", "boat", "raft", "flashlight", "batteries"]:
                p['items'].append(tile); add_log(f"{p['n']} מצא {tile}!"); maze[p['y']][p['x']]['tile'] = "empty"
            elif tile == "river":
                if "boat" not in p['items']:
                    if "raft" not in p['items']: p['hp'] += 1; add_log(f"{p['n']} נפצע בנהר!") [cite: 3]
                    for ry in range(10): # Sweep to River Start [cite: 5]
                        for rx in range(10):
                            if maze[ry][rx]['tile'] == "river_start": p['x'], p['y'] = rx, ry; break
            elif tile == "clinic" and p['hp'] < 4: p['hp'] = 0; add_log(f"{p['n']} התרפא במרפאה") [cite: 4]
            elif tile == "er" and p['hp'] == 4: p['hp'] = 3; add_log(f"{p['n']} קיבל עזרה במיון") [cite: 4]
            elif tile == "monster": 
                p['bul'] = min(5, p['bul']+1); p['bom'] = min(5, p['bom']+1); extra_turn = True; add_log(f"{p['n']} פגש מפלצת וקיבל תור נוסף!") [cite: 5]
            elif tile == "devil":
                p['hp'] += 1; p['bul'] = max(0, p['bul']-1); p['bom'] = max(0, p['bom']-1); add_log(f"{p['n']} פגש את השטן!") [cite: 5]
            elif tile == "armory": p['bul'] = 3; p['bom'] = 3; add_log(f"{p['n']} התחמש בנשקייה") [cite: 5]
            elif tile == "exit" and "treasure" in p['items']: winner_name = p['n'] [cite: 3]

    elif data['type'] == 'shoot' and p['bul'] > 0:
        p['bul'] -= 1; action_done = True
        tx, ty = p['x'] + dx, p['y'] + dy
        targets = [pl for pl in players.values() if pl['x'] == tx and pl['y'] == ty and pl['n'] != p['n']]
        if targets: targets[0]['hp'] += 1; add_log(f"{p['n']} ירה ב {targets[0]['n']}!") [cite: 7]

    elif data['type'] == 'bomb' and p['bom'] > 0:
        if dy == -1 and maze[p['y']][p['x']]['walls']['top']: maze[p['y']][p['x']]['walls']['top'] = False; p['bom'] -= 1; action_done = True
        elif dx == -1 and maze[p['y']][p['x']]['walls']['left']: maze[p['y']][p['x']]['walls']['left'] = False; p['bom'] -= 1; action_done = True

    if action_done and not extra_turn: turn_idx += 1
    sync_all()

@socketio.on('save_maze')
def save_maze(data):
    global maze; maze = data['maze']
    with open(M_FILE, "w") as f: json.dump(maze, f)
    sync_all()

@socketio.on('start_trigger')
def start():
    global game_started; game_started = True; sync_all()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)
