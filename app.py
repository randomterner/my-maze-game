from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import os, json

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Load maze or create a fresh 10x10 grid
def load_maze():
    if os.path.exists("maze.json"):
        with open("maze.json", "r") as f: return json.load(f)
    return [[{"tile": "empty", "walls": {"top": False, "left": False}} for _ in range(10)] for _ in range(10)]

maze_data = load_maze()
players = {}
game_started = False
turn_idx = 0

@app.route('/')
def index(): return render_template('index.html')

@app.route('/manager')
def manager(): return render_template('manager.html')

@socketio.on('join')
def on_join(data):
    players[request.sid] = {
        "n": data.get('name', 'Player'), "x": 0, "y": 0, "hp": 0, 
        "bullets": 3, "bombs": 3, "items": [], "is_man": (data.get('name') == "MANAGER")
    }
    sync()

@socketio.on('save_maze')
def save_maze(data):
    global maze_data
    maze_data = data['maze']
    with open("maze.json", "w") as f: json.dump(maze_data, f)
    sync()

@socketio.on('start_trigger')
def start():
    global game_started
    game_started = True
    sync()

def sync():
    # Only count actual players for the turn system
    active = [p for p in players.values() if not p['is_man']]
    curr_turn = active[turn_idx % len(active)]['n'] if active else "None"
    
    socketio.emit('sync', {
        "maze": maze_data,
        "players": [{"n":p['n'], "x":p['x'], "y":p['y'], "hp":p['hp']} for p in players.values()],
        "turn": curr_turn,
        "started": game_started
    })

@socketio.on('action')
def handle_action(data):
    global turn_idx
    p = players.get(request.sid)
    if not p or not game_started or p['is_man']: return
    
    # Simple movement for testing
    if data['type'] == 'move':
        p['x'] = max(0, min(9, p['x'] + data['dx']))
        p['y'] = max(0, min(9, p['y'] + data['dy']))
        turn_idx += 1
        sync()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8080, debug=True)
