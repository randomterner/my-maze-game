import os, random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'castle_maze_2026_pro'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# אתחול לוח 10x10
maze = [[{
    "tile": "empty", "was": None, 
    "walls": {"top": False, "left": False},
    "ex_walls": {"top": {"broken": False, "by": ""}, "left": {"broken": False, "by": ""}},
    "visited_by": [] 
} for _ in range(10)] for _ in range(10)]

players = {}
player_order = []
current_turn_idx = 0
game_phase = 1 
game_logs = []
winner = None
river_start_pos = (0, 0)

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

def check_win():
    global winner
    if winner: return
    p_list = [p for p in players.values() if not p['is_man']]
    alive = [p for p in p_list if p['injuries'] < 5]
    if len(p_list) > 1 and len(alive) == 1:
        winner = alive[0]['n']
        add_log(f"🏆 {winner} הוא השורד האחרון וניצח!")

def sync_all():
    check_win()
    p_list = [p for p in players.values() if not p['is_man']]
    active_id = player_order[current_turn_idx] if (player_order and current_turn_idx < len(player_order)) else None
    socketio.emit('sync', {
        "maze": maze, "players": p_list, "phase": game_phase,
        "logs": game_logs, "winner": winner, "turn_id": active_id
    })

def clear_lost(p):
    if p['is_lost']:
        p['is_lost'] = False
        for t in p['post_lost_tiles']:
            if t not in p['known_tiles']: p['known_tiles'].append(t)
        p['post_lost_tiles'] = []
        add_log(f"🧠 {p['n']} זיהה את מיקומו וחזר למפה!")

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
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['id'] != player_order[current_turn_idx] or p['waiting_teleport'] or p['injuries'] >= 5: return
    
    nx, ny = p['x'] + data['dx'], p['y'] + data['dy']
    blocked = False
    wall_key = 'top' if data['dy'] != 0 else 'left'
    
    if 0 <= nx < 10 and 0 <= ny < 10:
        if data['dx'] == 1 and maze[p['y']][nx]['walls']['left']: blocked = True
        elif data['dx'] == -1 and maze[p['y']][p['x']]['walls']['left']: blocked = True
        elif data['dy'] == 1 and maze[ny][p['x']]['walls']['top']: blocked = True
        elif data['dy'] == -1 and maze[p['y']][p['x']]['walls']['top']: blocked = True
    else: blocked = True

    if not blocked:
        # קיר שבור יחיד
        target_w = maze[ny][nx] if (data['dx']==1 or data['dy']==1) else maze[p['y']][p['x']]
        if target_w['ex_walls'][wall_key]['broken']:
            broken_total = sum(1 for r in maze for c in r if c['ex_walls'][wall_key]['broken'])
            if broken_total == 1 and (not p['is_lost'] or p['knows_river_start']):
                b_name = target_w['ex_walls'][wall_key]['by']
                b_obj = next((pl for pl in players.values() if pl['n'] == b_name), None)
                if b_obj: add_log(f"🕵️ {p['n']} עבר בקיר ש-{b_name} שבר. הוא ב-{get_rel_dir(p, b_obj)}.")

        p['x'], p['y'] = nx, ny
        tile = maze[ny][nx]
        curr_pos = [nx, ny]

        # יציאה מ-Lost: מפגש או זיהוי
        for other in [pl for pl in players.values() if not pl['is_man'] and pl['id'] != p['id']]:
            if other['x'] == nx and other['y'] == ny and p['is_lost'] and curr_pos in p['known_tiles']:
                clear_lost(p)
        if p['is_lost'] and p['n'] in tile['visited_by']: clear_lost(p)

        # Map Fusion
        t_name = tile['tile'] if tile['tile'] != "empty" else tile['was']
        if t_name and t_name not in ["empty", "river"]:
            if p['n'] not in tile['visited_by']: tile['visited_by'].append(p['n'])
            for other in [pl for pl in players.values() if not pl['is_man'] and pl['n'] in tile['visited_by']]:
                src = p['post_lost_tiles'] if p['is_lost'] else p['known_tiles']
                for t in src:
                    if t not in other['known_tiles']: other['known_tiles'].append(t)
                if not p['is_lost']:
                    for t in other['known_tiles']:
                        if t not in p['known_tiles']: p['known_tiles'].append(t)

        # אפקטים
        if tile['tile'] == "river":
            p['x'], p['y'] = river_start_pos
            if not p['knows_river_start']: p['is_lost'] = True; p['post_lost_tiles'] = []
            if "boat" not in p['items'] and "raft" not in p['items']: p['injuries'] += 1
            add_log(f"🌊 {p['n']} נסחף!")
        elif tile['tile'] == "black_hole":
            p['is_lost'] = True; p['waiting_teleport'] = True; p['post_lost_tiles'] = []
            add_log(f"🕳️ {p['n']} נשאב לחור שחור!")
        elif tile['tile'] == "monster": 
            p['bul']=min(5,p['bul']+1); p['bom']=min(5,p['bom']+1)
            add_log(f"👾 {p['n']} קיבל ציוד ותור נוסף!"); return 
        elif tile['tile'] == "devil": 
            p['injuries']+=1; p['bul']=max(0,p['bul']-1); p['bom']=max(0,p['bom']-1)
        elif tile['tile'] == "exit" and "treasure" in p['items']: global winner; winner = p['n']
        elif tile['tile'] == "river_start": p['knows_river_start'] = True
        elif tile['tile'] in ["treasure", "fake_treasure", "boat", "raft", "flashlight", "batteries", "clinic", "er", "armory"]:
            if tile['tile'] == "clinic" and p['injuries'] < 4: p['injuries'] = 0
            elif tile['tile'] == "er" and p['injuries'] == 4: p['injuries'] = 3
            elif tile['tile'] == "armory": p['bul']=3; p['bom']=3
            else: p['items'].append(tile['tile']); tile['was'] = tile['tile']; tile['tile'] = "empty"

        if curr_pos not in (p['post_lost_tiles'] if p['is_lost'] else p['known_tiles']):
            (p['post_lost_tiles'] if p['is_lost'] else p['known_tiles']).append(curr_pos)
    sync_all()

@socketio.on('shoot')
def on_shoot(data):
    p = players.get(request.sid)
    if not p or p['bul'] <= 0 or p['id'] != player_order[current_turn_idx]: return
    p['bul'] -= 1; dx, dy = data['dx'], data['dy']; sx, sy = p['x'], p['y']
    for _ in range(10):
        if dx == 1 and (sx+1 >= 10 or maze[sy][sx+1]['walls']['left']): break
        if dx == -1 and maze[sy][sx]['walls']['left']: break
        if dy == 1 and (sy+1 >= 10 or maze[sy+1][sx]['walls']['top']): break
        if dy == -1 and maze[sy][sx]['walls']['top']: break
        sx += dx; sy += dy
        t = next((pl for pl in players.values() if not pl['is_man'] and pl['x'] == sx and pl['y'] == sy), None)
        if t: t['injuries'] += 1; add_log(f"💥 פגיעה ב-{t['n']}!"); break
    sync_all()

@socketio.on('bomb')
def on_bomb(data):
    p = players.get(request.sid)
    if not p or p['bom'] <= 0 or p['id'] != player_order[current_turn_idx]: return
    dx, dy = data['dx'], data['dy']; tx, ty = p['x'], p['y']
    wt = 'left' if dx != 0 else 'top'
    if dx == 1: tx += 1
    if dy == 1: ty += 1
    if 0 <= tx < 10 and 0 <= ty < 10 and maze[ty][tx]['walls'][wt]:
        maze[ty][tx]['walls'][wt] = False
        maze[ty][tx]['ex_walls'][wt] = {"broken": True, "by": p['n']}
        p['bom'] -= 1; add_log(f"💣 {p['n']} פוצץ קיר.")
    sync_all()

@socketio.on('host_teleport')
def on_host_tele(data):
    p_t = players.get(data['target_id'])
    if p_t and maze[data['y']][data['x']]['tile'] == "empty":
        p_t['x'], p_t['y'] = data['x'], data['y']
        p_t['waiting_teleport'] = False
        p_t['post_lost_tiles'].append([p_t['x'], p_t['y']])
        sync_all()

@socketio.on('set_phase')
def on_set_ph(ph):
    global game_phase; game_phase = int(ph.get('phase', ph) if isinstance(ph, dict) else ph)
    sync_all()

@socketio.on('update_maze')
def on_uz(d):
    global maze, river_start_pos
    if game_phase == 1:
        maze = d
        for y in range(10):
            for x in range(10):
                if maze[y][x]['tile'] == "river_start": river_start_pos = (x,y)
    sync_all()

@socketio.on('set_spawn')
def on_sp(d):
    p = players.get(request.sid)
    if p and game_phase == 2:
        p['x'], p['y'] = d['x'], d['y']; p['has_spawned'] = True; p['known_tiles'] = [[d['x'], d['y']]]
        sync_all()

@socketio.on('next_turn')
def on_next():
    global current_turn_idx
    if player_order: current_turn_idx = (current_turn_idx + 1) % len(player_order); sync_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
