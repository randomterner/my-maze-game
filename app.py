import os, json
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

M_FILE = "maze.json"
players = {}
game_started = False

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
            "started": game_started,
            "my_data": p
        }, room=sid)

@app.route('/')
def index(): return render_template('index.html')

@app.route('/manager')
def manager(): return render_template('manager.html')

@socketio.on('join')
def on_join(data):
    players[request.sid] = {
        "n": data.get('name', 'Player'), "x": 0, "y": 0, "hp": 0, "bul": 3, "bom": 3,
        "items": [], "is_man": (data.get('name') == "MANAGER"),
        "known_tiles": [], "pre_bh_tiles": [], "is_lost": False
    }
    sync_all()

@socketio.on('teleport_player')
def handle_teleport(data):
    target_sid = data.get('target_sid')
    if target_sid in players:
        players[target_sid]['pre_bh_tiles'] = [list(t) for t in players[target_sid]['known_tiles']]
        players[target_sid]['x'] = data['x']
        players[target_sid]['y'] = data['y']
        players[target_sid]['is_lost'] = True 
        sync_all()

@socketio.on('action')
def handle_action(data):
    p = players.get(request.sid)
    if not p or p['is_man']: return
    if data['type'] == 'move':
        p['x'] += data['dx']; p['y'] += data['dy']
        pos = [p['x'], p['y']]
        tile_type = maze[p['y']][p['x']]['tile']

        if tile_type != "empty":
            for sid, other in players.items():
                if sid != request.sid and not other['is_man']:
                    if any(t[0] == p['x'] and t[1] == p['y'] for t in other['known_tiles']):
                        # Player A (other) learns what Player B (p) found after BH
                        post_bh = [t for t in p['known_tiles'] if t not in p['pre_bh_tiles']]
                        other['known_tiles'] = list(set(map(tuple, other['known_tiles'] + post_bh)))
                        
                        # Player B (p) recovers only if they knew THIS square before BH
                        if any(t[0] == p['x'] and t[1] == p['y'] for t in p['pre_bh_tiles']):
                            p['is_lost'] = False
                        
                        socketio.emit('relative_ping', {
                            "target_n": other['n'], 
                            "dx": other['x'] - p['x'], 
                            "dy": other['y'] - p['y']
                        }, room=request.sid)

        if pos not in p['known_tiles']: p['known_tiles'].append(pos)
        
        if tile_type == "river":
            knows_start = any(maze[y][x]['tile'] == "river_start" and [x,y] in p['known_tiles'] for y in range(10) for x in range(10))
            if "boat" not in p['items'] and not knows_start:
                p['is_lost'] = True
                if "raft" not in p['items']: p['hp'] += 1
                for ry in range(10):
                    for rx in range(10):
                        if maze[ry][rx]['tile'] == "river_start": p['x'], p['y'] = rx, ry; break

        if tile_type == "black_hole":
            socketio.emit('bh_event', {"sid": request.sid, "n": p['n']})
    sync_all()

@socketio.on('save_maze')
def save_maze(data):
    global maze; maze = data['maze']; sync_all()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)
