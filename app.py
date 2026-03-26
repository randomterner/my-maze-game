import os
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'maze_secret_123'
# Increased heartbeat to prevent Render from killing the connection
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60, ping_interval=25)

maze = [[{"tile": "empty", "walls": {"top": False, "left": False}} for _ in range(10)] for _ in range(10)]
players = {}
game_phase = 1 
game_logs = []
winner = None

def add_log(msg):
    game_logs.insert(0, msg)
    if len(game_logs) > 20: game_logs.pop()

def sync_all():
    p_list = [p for p in players.values() if not p['is_man']]
    alive = [p for p in p_list if p['injuries'] < 5]
    
    global winner
    if len(alive) == 1 and len(p_list) > 1 and not winner:
        winner = alive[0]['n']
        add_log(f"🏆 {winner} הוא השורד האחרון!")

    socketio.emit('sync', {
        "maze": maze,
        "players": [{"n":pl['n'], "x":pl['x'], "y":pl['y'], "injuries":pl['injuries'], "dead":pl['injuries']>=5} for pl in players.values()],
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
    name = data.get('name', 'Player')
    players[request.sid] = {
        "n": name, "x": 0, "y": 0, "has_spawned": False, 
        "injuries": 0, "bul": 3, "bom": 3, "items": [], 
        "is_man": (name == "MANAGER"), "known_tiles": [], "is_lost": False
    }
    add_log(f"📢 {name} הצטרף")
    sync_all()

@socketio.on('set_phase')
def set_phase(data):
    global game_phase
    try:
        val = int(data['phase'])
        if val > game_phase: # Lock: Forward only
            game_phase = val
            add_log(f"🚩 שלב {game_phase}")
            sync_all()
    except: pass

@socketio.on('save_maze')
def save_maze(data):
    global maze
    if game_phase == 1:
        maze = data['maze']
        sync_all()

@socketio.on('action')
def handle_action(data):
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['injuries'] >= 5 or p['is_man']: return
    
    act, dx, dy = data.get('type'), data.get('dx', 0), data.get('dy', 0)
    # [Movement/Combat logic same as previous - clipped for brevity]
    # Ensure you keep the movement/shooting logic here
    sync_all()

@socketio.on('set_spawn')
def set_spawn(d):
    p = players.get(request.sid)
    if p and game_phase == 2:
        p['x'], p['y'] = d['x'], d['y']
        p['has_spawned'] = True
        p['known_tiles'] = [[d['x'], d['y']]]
        sync_all()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)
