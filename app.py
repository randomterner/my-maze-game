import os, random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'maze_combat_final'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)

maze = [[{"tile": "empty", "walls": {"top": False, "left": False}} for _ in range(10)] for _ in range(10)]
players = {}
game_phase = 1 
game_logs = []
winner = None

def add_log(key, name, extra=""):
    game_logs.insert(0, {"key": key, "n": name, "e": extra})
    if len(game_logs) > 40: game_logs.pop()

def sync_all():
    p_list = [p for p in players.values() if not p['is_man']]
    socketio.emit('sync', {"maze": maze, "players": p_list, "phase": game_phase, "logs": game_logs, "winner": winner})

@app.route('/')
def index(): return render_template('index.html')

@app.route('/manager')
def manager(): return render_template('manager.html')

@socketio.on('join')
def on_join(data):
    players[request.sid] = {
        "id": request.sid, "n": data.get('name', 'Player'), "is_man": data.get('is_man', False),
        "x": 0, "y": 0, "injuries": 0, "bul": 3, "bom": 3, "items": [], "known_tiles": []
    }
    sync_all()

# --- לוגיקת ירייה ---
@socketio.on('shoot')
def on_shoot(data):
    p = players.get(request.sid)
    if not p or p['bul'] <= 0 or game_phase != 3: return
    p['bul'] -= 1
    dx, dy = data['dx'], data['dy']
    sx, sy = p['x'], p['y']
    
    # הכדור נע בקו ישר עד קיר או פגיעה
    hit_name = "Nothing"
    for _ in range(10):
        # בדיקת קיר לפני תנועת הכדור
        if dx == 1 and (sx + 1 >= 10 or maze[sy][sx+1]['walls']['left']): break
        if dx == -1 and maze[sy][sx]['walls']['left']: break
        if dy == 1 and (sy + 1 >= 10 or maze[sy+1][sx]['walls']['top']): break
        if dy == -1 and maze[sy][sx]['walls']['top']: break
        
        sx += dx; sy += dy
        # בדיקה אם פגע בשחקן
        target = next((pl for pl in players.values() if not pl['is_man'] and pl['x'] == sx and pl['y'] == sy), None)
        if target:
            target['injuries'] += 1
            hit_name = target['n']
            add_log("LOG_SHOT_HIT", p['n'], target['n'])
            break
    if hit_name == "Nothing": add_log("LOG_SHOT_MISS", p['n'])
    sync_all()

# --- לוגיקת פצצה ---
@socketio.on('bomb')
def on_bomb(data):
    p = players.get(request.sid)
    if not p or p['bom'] <= 0 or game_phase != 3: return
    dx, dy = data['dx'], data['dy']
    
    target_x, target_y = p['x'], p['y']
    wall_type = ""
    
    if dx == 1 and p['x'] < 9: target_x += 1; wall_type = "left"
    elif dx == -1: wall_type = "left"
    elif dy == 1 and p['y'] < 9: target_y += 1; wall_type = "top"
    elif dy == -1: wall_type = "top"

    if wall_type and maze[target_y][target_x]['walls'][wall_type]:
        maze[target_y][target_x]['walls'][wall_type] = False
        p['bom'] -= 1
        add_log("LOG_BOMB_WALL", p['n'])
    sync_all()

@socketio.on('move')
def on_move(data):
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['injuries'] >= 5: return
    dx, dy = data['dx'], data['dy']
    nx, ny = p['x'] + dx, p['y'] + dy
    if 0 <= nx < 10 and 0 <= ny < 10:
        if dx == 1 and maze[p['y']][nx]['walls']['left']: return
        if dx == -1 and maze[p['y']][p['x']]['walls']['left']: return
        if dy == 1 and maze[ny][p['x']]['walls']['top']: return
        if dy == -1 and maze[p['y']][p['x']]['walls']['top']: return
        p['x'], p['y'] = nx, ny
        # (שאר לוגיקת המשבצות מהגרסאות הקודמות...)
        tile = maze[ny][nx].get('tile', 'empty')
        if tile == "armory":
            p['bul'] = max(p['bul'], 3); p['bom'] = max(p['bom'], 3); add_log("LOG_ARMORY", p['n'])
        elif tile in ["treasure", "boat", "raft", "flashlight", "batteries"]:
            p['items'].append(tile); maze[ny][nx]['tile'] = "empty"; add_log("LOG_PICKUP", p['n'], tile)
        if [p['x'], p['y']] not in p['known_tiles']: p['known_tiles'].append([p['x'], p['y']])
    sync_all()

@socketio.on('set_phase')
def on_set_phase(ph): global game_phase; game_phase=int(ph); sync_all()
@socketio.on('set_spawn')
def on_spawn(d):
    p=players.get(request.sid)
    if p: p['x'],p['y']=d['x'],d['y']; p['has_spawned']=True; p['known_tiles']=[[d['x'],d['y']]]; sync_all()
@socketio.on('update_maze')
def on_maze(d): global maze; maze=d; sync_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
