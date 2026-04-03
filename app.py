import os, random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'maze_2026_final_system'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# אתחול לוח
maze = [[{
    "tile": "empty", "was": None, 
    "walls": {"top": False, "left": False},
    "ex_walls": {"top": {"broken": False, "by": ""}, "left": {"broken": False, "by": ""}},
    "visited_by": [] # שמות שחקנים שעברו כאן
} for _ in range(10)] for _ in range(10)]

players = {}
player_order = []
current_turn_idx = 0
game_phase = 1 
game_logs = []
winner = None
river_start_pos = (-1, -1)

def add_log(msg):
    game_logs.insert(0, msg)
    if len(game_logs) > 60: game_logs.pop()

def get_rel_dir(p1, p2):
    dy, dx = p2['y'] - p1['y'], p2['x'] - p1['x']
    res = []
    if dy < 0: res.append("צפון")
    elif dy > 0: res.append("דרום")
    if dx < 0: res.append("מערב")
    elif dx > 0: res.append("מזרח")
    return "-".join(res) if res else "ממש כאן"

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
        "has_spawned": False, "known_tiles": [], "post_lost_tiles": [],
        "is_lost": False, "waiting_teleport": False, "knows_river_start": False
    }
    if not is_man and request.sid not in player_order: player_order.append(request.sid)
    sync_all()

@socketio.on('move')
def on_move(data):
    global winner
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['id'] != player_order[current_turn_idx] or winner or p['waiting_teleport']: return
    
    dx, dy = data['dx'], data['dy']
    nx, ny = p['x'] + dx, p['y'] + dy
    blocked = False
    wall_key = 'top' if dy != 0 else 'left'
    
    if 0 <= nx < 10 and 0 <= ny < 10:
        if dx == 1 and maze[p['y']][nx]['walls']['left']: blocked = True
        elif dx == -1 and maze[p['y']][p['x']]['walls']['left']: blocked = True
        elif dy == 1 and maze[ny][p['x']]['walls']['top']: blocked = True
        elif dy == -1 and maze[p['y']][p['x']]['walls']['top']: blocked = True
    else: blocked = True

    if not blocked:
        # לוגיקת קיר שבור יחיד
        target_w_cell = maze[ny][nx] if (dx==1 or dy==1) else maze[p['y']][p['x']]
        if target_w_cell['ex_walls'][wall_key]['broken']:
            broken_total = sum(1 for row in maze for c in row if c['ex_walls'][wall_key]['broken'])
            if broken_total == 1 and (not p['is_lost'] or p['knows_river_start']):
                breaker_n = target_w_cell['ex_walls'][wall_key]['by']
                b_obj = next((pl for pl in players.values() if pl['n'] == breaker_n), None)
                if b_obj: add_log(f"🔎 {p['n']} עבר בקיר השבור היחיד. {breaker_n} נמצא ב-{get_rel_dir(p, b_obj)}.")

        p['x'], p['y'] = nx, ny
        tile = maze[ny][nx]
        
        # יציאה מ-Lost אם חזר למקום מוכר
        if p['is_lost'] and p['n'] in tile['visited_by']:
            p['is_lost'] = False; add_log(f"🧠 {p['n']} זיהה את הדרך ויצא ממצב אבוד!")

        # Map Fusion & Visited logic
        t_name = tile['tile'] if tile['tile'] != "empty" else tile['was']
        if t_name and t_name not in ["empty", "river"]:
            if p['n'] not in tile['visited_by']: tile['visited_by'].append(p['n'])
            
            for other_id, other_p in players.items():
                if other_id != request.sid and not other_p['is_man']:
                    if other_p['n'] in tile['visited_by']:
                        # Fusion: Share info
                        source = p['post_lost_tiles'] if p['is_lost'] else p['known_tiles']
                        for t_coord in source:
                            if t_coord not in other_p['known_tiles']: other_p['known_tiles'].append(t_coord)
                        if not p['is_lost']:
                            for t_coord in other_p['known_tiles']:
                                if t_coord not in p['known_tiles']: p['known_tiles'].append(t_coord)
                        add_log(f"🤝 מפות של {p['n']} ו-{other_p['n']} אוחדו דרך ה-{t_name}!")

        # Tiles Effects
        if tile['tile'] == "river":
            p['x'], p['y'] = river_start_pos
            if not p['knows_river_start']: p['is_lost'] = True; p['post_lost_tiles'] = []
            if "boat" not in p['items'] and "raft" not in p['items']: p['injuries'] += 1
            add_log(f"🌊 {p['n']} נסחף בנהר!")
        elif tile['tile'] == "black_hole":
            p['is_lost'] = True; p['waiting_teleport'] = True; p['post_lost_tiles'] = []
            add_log(f"🕳️ {p['n']} נשאב לחור שחור! ממתין שהמנחה ישגר אותו...")
        elif tile['tile'] == "river_start": p['knows_river_start'] = True; add_log(f"📍 {p['n']} מצא את מקור הנהר.")
        elif tile['tile'] == "monster": 
            p['bul']=min(5, p['bul']+1); p['bom']=min(5, p['bom']+1); add_log(f"👾 {p['n']} קיבל ציוד ותור נוסף!"); return
        elif tile['tile'] == "devil": p['injuries']+=1; p['bul']=max(0,p['bul']-1); p['bom']=max(0,p['bom']-1); add_log(f"😈 {p['n']} פגש שטן!")
        elif tile['tile'] == "exit" and "treasure" in p['items']: winner = p['n']; add_log(f"🏆 {p['n']} ניצח!")
        elif tile['tile'] in ["treasure", "fake_treasure", "boat", "raft", "flashlight", "batteries", "clinic", "er", "armory"]:
            if tile['tile'] == "clinic" and p['injuries'] < 4: p['injuries'] = 0
            elif tile['tile'] == "er" and p['injuries'] == 4: p['injuries'] = 3
            elif tile['tile'] == "armory": p['bul']=3; p['bom']=3
            else: p['items'].append(tile['tile']); tile['was'] = tile['tile']; tile['tile'] = "empty"
            add_log(f"✨ {p['n']} הגיע ל-{tile['tile'] or tile['was']}.")

        if [p['x'], p['y']] not in p['known_tiles']:
            p['known_tiles'].append([p['x'], p['y']])
            if p['is_lost']: p['post_lost_tiles'].append([p['x'], p['y']])
    sync_all()

@socketio.on('host_teleport')
def on_host_teleport(data):
    # רק המנחה יכול להשתמש בזה
    p_host = players.get(request.sid)
    if not p_host or not p_host['is_man']: return
    
    target_id = data['target_id']
    tx, ty = data['x'], data['y']
    p_target = players.get(target_id)
    
    if p_target and maze[ty][tx]['tile'] == "empty":
        p_target['x'], p_target['y'] = tx, ty
        p_target['waiting_teleport'] = False
        if [tx, ty] not in p_target['known_tiles']: 
            p_target['known_tiles'].append([tx, ty])
            p_target['post_lost_tiles'].append([tx, ty])
        add_log(f"🪄 המנחה שיגר את {p_target['n']} למקום חדש.")
        sync_all()

@socketio.on('set_phase')
def on_ph(ph): global game_phase; game_phase=int(ph.get('phase',ph) if isinstance(ph,dict) else ph); sync_all()

@socketio.on('next_turn')
def on_next():
    global current_turn_idx
    if player_order: current_turn_idx = (current_turn_idx + 1) % len(player_order); sync_all()

@socketio.on('update_maze')
def on_uz(d):
    global maze, river_start_pos
    if game_phase == 1:
        maze = d
        for y in range(10):
            for x in range(10):
                if maze[y][x]['tile'] == "river_start": river_start_pos = (x,y)
    sync_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
