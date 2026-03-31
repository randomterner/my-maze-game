import os, random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'maze_final_v3'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)

# מצב המשחק
maze = [[{"tile": "empty", "walls": {"top": False, "left": False}} for _ in range(10)] for _ in range(10)]
players = {} 
player_order = [] 
current_turn_idx = 0
game_phase = 1 
game_logs = []
winner = None
river_start_pos = (0,0)

def add_log(msg):
    game_logs.insert(0, msg)
    if len(game_logs) > 30: game_logs.pop()

def sync_all():
    p_list = [p for p in players.values() if not p['is_man']]
    active_id = player_order[current_turn_idx] if player_order else None
    socketio.emit('sync', {
        "maze": maze, "players": p_list, "phase": game_phase,
        "logs": game_logs, "winner": winner, "turn_id": active_id
    })

@app.route('/')
def index(): return render_template('index.html')

@app.route('/manager')
def manager(): return render_template('manager.html')

@socketio.on('join')
def on_join(data):
    is_man = data.get('is_man', False)
    players[request.sid] = {
        "id": request.sid, "n": data.get('name', 'Player'), "is_man": is_man,
        "x": 0, "y": 0, "injuries": 0, "bul": 3, "bom": 3, "items": [], 
        "has_spawned": False, "known_tiles": []
    }
    if not is_man and request.sid not in player_order:
        player_order.append(request.sid)
    sync_all()

@socketio.on('set_phase')
def on_set_phase(ph):
    global game_phase
    game_phase = int(ph)
    sync_all()

@socketio.on('next_turn')
def on_next_turn():
    global current_turn_idx
    if not player_order: return
    current_turn_idx = (current_turn_idx + 1) % len(player_order)
    # דילוג על שחקנים מתים
    for _ in range(len(player_order)):
        p = players.get(player_order[current_turn_idx])
        if p and p['injuries'] < 5: break
        current_turn_idx = (current_turn_idx + 1) % len(player_order)
    sync_all()

@socketio.on('move')
def on_move(data):
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['id'] != player_order[current_turn_idx]: return
    dx, dy = data['dx'], data['dy']
    nx, ny = p['x'] + dx, p['y'] + dy
    if 0 <= nx < 10 and 0 <= ny < 10:
        if dx == 1 and maze[p['y']][nx]['walls']['left']: return
        if dx == -1 and maze[p['y']][p['x']]['walls']['left']: return
        if dy == 1 and maze[ny][p['x']]['walls']['top']: return
        if dy == -1 and maze[p['y']][p['x']]['walls']['top']: return
        
        p['x'], p['y'] = nx, ny
        tile = maze[ny][nx]['tile']
        
        if tile == "river":
            if "boat" in p['items']: add_log(f"🛶 {p['n']} crossed safely.")
            elif "raft" in p['items']: p['x'], p['y'] = river_start_pos; add_log(f"🌊 {p['n']} swept back (Raft protected).")
            else: p['x'], p['y'] = river_start_pos; p['injuries']+=1; add_log(f"🌊 {p['n']} swept and injured!")
        elif tile == "armory":
            p['bul'] = max(p['bul'], 3); p['bom'] = max(p['bom'], 3); add_log(f"⚔️ {p['n']} restocked.")
        elif tile == "monster":
            p['bul'] += 1; p['bom'] += 1; add_log(f"👾 {p['n']} met monster! +Ammo.")
        elif tile == "devil":
            p['injuries'] += 1; p['bul'] = max(0, p['bul']-1); p['bom'] = max(0, p['bom']-1); add_log(f"😈 {p['n']} met Devil!")
        elif tile == "black_hole":
            p['x'], p['y'] = random.randint(0,9), random.randint(0,9); add_log(f"🕳️ {p['n']} teleported!")
        elif tile == "clinc" and p['injuries'] <= 3: p['injuries'] = max(0, p['injuries']-1); add_log(f"🏥 {p['n']} healed.")
        elif tile == "er" and p['injuries'] == 4: p['injuries'] = 3; add_log(f"🚑 {p['n']} ER save.")
        elif tile == "exit" and "tresure" in p['items']:
            global winner; winner = p['n']; add_log(f"🏆 {p['n']} WON!")
        elif tile in ["tresure", "fake_tresure", "boat", "raft", "flashlight", "batteries"]:
            p['items'].append(tile); maze[ny][nx]['tile'] = "empty"; add_log(f"📦 {p['n']} found {tile}.")
        
        if [p['x'], p['y']] not in p['known_tiles']: p['known_tiles'].append([p['x'], p['y']])
    sync_all()

@socketio.on('shoot')
def on_shoot(data):
    p = players.get(request.sid); dx, dy = data['dx'], data['dy']
    if not p or p['bul'] <= 0 or p['id'] != player_order[current_turn_idx]: return
    p['bul'] -= 1; sx, sy = p['x'], p['y']
    for _ in range(10):
        if dx == 1 and (sx + 1 >= 10 or maze[sy][sx+1]['walls']['left']): break
        if dx == -1 and maze[sy][sx]['walls']['left']: break
        if dy == 1 and (sy + 1 >= 10 or maze[sy+1][sx]['walls']['top']): break
        if dy == -1 and maze[sy][sx]['walls']['top']: break
        sx += dx; sy += dy
        target = next((pl for pl in players.values() if not pl['is_man'] and pl['x'] == sx and pl['y'] == sy), None)
        if target: target['injuries'] += 1; add_log(f"💥 {p['n']} shot {target['n']}!"); break
    sync_all()

@socketio.on('bomb')
def on_bomb(data):
    p = players.get(request.sid); dx, dy = data['dx'], data['dy']
    if not p or p['bom'] <= 0 or p['id'] != player_order[current_turn_idx]: return
    tx, ty = p['x'], p['y']; wt = ""
    if dx == 1 and p['x'] < 9: tx += 1; wt = "left"
    elif dx == -1: wt = "left"
    elif dy == 1 and p['y'] < 9: ty += 1; wt = "top"
    elif dy == -1: wt = "top"
    if wt and maze[ty][tx]['walls'][wt]: maze[ty][tx]['walls'][wt] = False; p['bom'] -= 1; add_log(f"💣 {p['n']} broke a wall.")
    sync_all()

@socketio.on('set_spawn')
def on_set_spawn(d):
    p = players.get(request.sid)
    if p: p['x'], p['y'] = d['x'], d['y']; p['has_spawned'] = True; p['known_tiles'] = [[d['x'], d['y']]]; sync_all()

@socketio.on('update_maze')
def on_update_maze(d):
    global maze, river_start_pos
    if game_phase == 1:
        maze = d
        for y in range(10):
            for x in range(10):
                if maze[y][x]['tile'] == "river_start": river_start_pos = (x,y)
    sync_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
