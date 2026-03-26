import os
import random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'maze_secret_123'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Game State
maze = [[{"tile": "empty", "walls": {"top": False, "left": False}} for _ in range(10)] for _ in range(10)]
players = {}
game_phase = 1 # 1: Build, 2: Spawn, 3: Start
game_logs = []
winner = None

def add_log(msg):
    game_logs.insert(0, msg)
    if len(game_logs) > 25: game_logs.pop()

def sync_all():
    p_list = [p for p in players.values() if not p['is_man']]
    socketio.emit('sync', {
        "maze": maze,
        "players": p_list,
        "phase": game_phase,
        "logs": game_logs,
        "winner": winner
    })

@app.route('/')
def index(): return render_template('index.html')

@app.route('/manager')
def manager(): return render_template('manager.html')

@socketio.on('join')
def on_join(data):
    is_man = data.get('is_man', False)
    players[request.sid] = {
        "id": request.sid, "n": data.get('name', 'Guest'), "is_man": is_man,
        "x": 0, "y": 0, "injuries": 0, "bul": 3, "bom": 3, 
        "items": [], "has_spawned": False, "known_tiles": []
    }
    sync_all()

@socketio.on('move')
def on_move(data):
    global game_phase, winner
    if game_phase != 3 or winner: return
    p = players.get(request.sid)
    if not p or p['injuries'] >= 5: return

    dx, dy = data['dx'], data['dy']
    new_x, new_y = p['x'] + dx, p['y'] + dy

    if 0 <= new_x < 10 and 0 <= new_y < 10:
        # Check walls
        if dx == 1 and maze[p['y']][new_x]['walls']['left']: return
        if dx == -1 and maze[p['y']][p['x']]['walls']['left']: return
        if dy == 1 and maze[new_y][p['x']]['walls']['top']: return
        if dy == -1 and maze[p['y']][p['x']]['walls']['top']: return

        p['x'], p['y'] = new_x, new_y
        tile = maze[new_y][new_x]['tile']
        
        # --- Rule Logic ---
        if tile == "black_hole":
            p['x'], p['y'] = random.randint(0, 9), random.randint(0, 9)
            add_log(f"🕳️ {p['n']} fell into a Black Hole and teleported!")
        
        elif tile == "devil":
            p['injuries'] += 1
            p['bul'] = max(0, p['bul']-1)
            p['bom'] = max(0, p['bom']-1)
            add_log(f"😈 {p['n']} met the Devil! -1 Bul, -1 Bom, +1 Inj")

        elif tile == "armory":
            p['bul'] += 3
            p['bom'] += 3
            add_log(f"⚔️ {p['n']} restocked at the Armory!")

        elif tile == "exit" and "tresure" in p['items']:
            winner = p['n']
            add_log(f"🏆 {p['n']} reached the EXIT with the Treasure!")

        # Vision logic
        if [p['x'], p['y']] not in p['known_tiles']:
            p['known_tiles'].append([p['x'], p['y']])
        
    sync_all()

@socketio.on('update_maze')
def update_maze(data):
    global maze
    maze = data
    sync_all()

@socketio.on('set_phase')
def set_phase(p):
    global game_phase
    game_phase = p
    sync_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
