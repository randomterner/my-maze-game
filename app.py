import os, random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'castle_maze_ultimate_2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Global Game State
maze = [[{
    "tile": "empty", 
    "collected": False, 
    "walls": {"top": False, "left": False},
    "ex_walls": {"top": {"broken": False, "by": ""}, "left": {"broken": False, "by": ""}},
    "visited_by": [],
    "dropped_items": [],
    "is_birthplace": False,
    "birth_owner_id": None,
    "birth_owner_name": None
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

def get_dir_name(dx, dy):
    if dy == -1: return "up"
    if dy == 1: return "down"
    if dx == -1: return "left"
    if dx == 1: return "right"
    return "unknown"

def sync_all():
    p_list = [p for p in players.values() if not p['is_man']]
    active_id = player_order[current_turn_idx] if (player_order and current_turn_idx < len(player_order)) else None
    socketio.emit('sync', {
        "maze": maze, "players": p_list, "phase": game_phase,
        "logs": game_logs, "winner": winner, "turn_id": active_id
    })

def clear_lost(p):
    if p['is_lost']:
        p['is_lost'] = False
        p['lost_by_river'] = False
        for t in p['post_lost_tiles']:
            if t not in p['known_tiles']: p['known_tiles'].append(t)
        p['post_lost_tiles'] = []
        add_log(f"🧠 {p['n']} recognized the area and is no longer lost!")

def on_next():
    global current_turn_idx
    if not player_order: return
    for _ in range(len(player_order)):
        current_turn_idx = (current_turn_idx + 1) % len(player_order)
        next_sid = player_order[current_turn_idx]
        p = players.get(next_sid)
        if p and p['injuries'] < 5 and p['has_spawned'] and not p['waiting_teleport']:
            break

def check_turn(p):
    if not p or game_phase != 3: return False
    return player_order and p['id'] == player_order[current_turn_idx]

def apply_tile(p):
    nx, ny = p['x'], p['y']
    tile = maze[ny][nx]

    # --- 1. BIRTHPLACE CAMERA ---
    if tile['is_birthplace']:
        add_log(f"✨ {p['n']} found {tile['birth_owner_name']}'s birthplace!")
        owner = players.get(tile['birth_owner_id'])
        if owner and owner['id'] != p['id']:
            for step in p['walked_path']:
                if step not in owner['known_tiles']: owner['known_tiles'].append(step)
            add_log(f"👁️ {owner['n']} sensed the intruder's path through home!")

    # --- 2. MAP LOGIC (LOST/UNLOST) ---
    if p['is_lost'] and (p['n'] in tile['visited_by'] or (tile['tile'] == "river_start" and p.get('lost_by_river'))):
        clear_lost(p)

    curr_c = [p['x'], p['y']]
    target_list = p['post_lost_tiles'] if p['is_lost'] else p['known_tiles']
    if curr_c not in target_list: target_list.append(curr_c)
    if curr_c not in p['walked_path']: p['walked_path'].append(curr_c)

    # 10x10 Rule
    if p['is_lost'] and len(p['post_lost_tiles']) > 0:
        xs = [t[0] for t in p['post_lost_tiles']]; ys = [t[1] for t in p['post_lost_tiles']]
        if (max(xs) - min(xs) >= 9) and (max(ys) - min(ys) >= 9):
            add_log(f"🧭 {p['n']} hit 10x10 limit and found their bearings!")
            clear_lost(p)

    # --- 3. TILE MECHANICS ---
    item = tile['tile']
    
    # Reset/Set River Immunity
    if item != "river" and item != "river_start": p['river_safe'] = False
    elif item == "river_start": p['knows_river_start'] = True; p['river_safe'] = True

    if item == "river":
        if not ("boat" in p['items'] or p.get('river_safe')):
            p['x'], p['y'] = river_start_pos
            if "raft" not in p['items']: p['injuries'] += 1
            p['is_lost'] = not p['knows_river_start']
            p['lost_by_river'] = p['is_lost']
            p['river_safe'] = True
            add_log(f"🌊 {p['n']} was swept away!")
            if [p['x'], p['y']] not in (p['post_lost_tiles'] if p['is_lost'] else p['known_tiles']):
                (p['post_lost_tiles'] if p['is_lost'] else p['known_tiles']).append([p['x'], p['y']])
            return False

    elif item == "black_hole":
        p['is_lost'] = True; p['waiting_teleport'] = True; p['post_lost_tiles'] = []
        add_log(f"🕳️ {p['n']} fell into a Black Hole!")

    elif item == "monster":
        p['bul'] = min(5, p['bul']+1); p['bom'] = min(5, p['bom']+1)
        add_log(f"👾 Monster gave {p['n']} gear and an extra turn!")
        return True

    elif item == "devil":
        p['injuries'] += 1; p['bul'] = max(0, p['bul']-1); p['bom'] = max(0, p['bom']-1)
        add_log(f"😈 Devil attacked {p['n']}!")

    elif item == "clinic":
        if p['injuries'] < 4: p['injuries'] = 0; add_log(f"🏥 {p['n']} was fully healed!")
    
    elif item == "er":
        if p['injuries'] == 4: p['injuries'] = 3; add_log(f"🚑 {p['n']} was saved from the brink!")

    elif item == "armory":
        p['bul'] = 3; p['bom'] = 3; add_log(f"⚔️ {p['n']} restocked at the armory!")

    elif item == "exit":
        if "treasure" in p['items']:
            global winner; winner = p['n']
            add_log(f"🏆 {p['n']} ESCAPED WITH THE TREASURE!")

    elif item in ["treasure", "fake_treasure", "boat", "raft", "flashlight", "batteries"]:
        if not tile['collected']:
            p['items'].append(item); tile['collected'] = True
            add_log(f"✨ {p['n']} picked up {item.replace('_', ' ')}.")
        else:
            add_log(f"👀 {p['n']} found an empty spot where {item} once was.")

    # Visited marking
    if p['n'] not in tile['visited_by'] and item != "empty": tile['visited_by'].append(p['n'])
    
    # Death check
    if p['injuries'] >= 5:
        add_log(f"💀 {p['n']} has died!"); tile['dropped_items'].extend(p['items']); p['items'] = []

    return False

@socketio.on('join')
def on_join(data):
    sid = request.sid
    players[sid] = {
        "id": sid, "n": data.get('name', 'Player'), "is_man": data.get('is_man', False),
        "x": 0, "y": 0, "injuries": 0, "bul": 3, "bom": 3, "items": [], 
        "has_spawned": False, "known_tiles": [], "post_lost_tiles": [], 
        "crossed_edges": [], "bumped_walls": [], "walked_path": [], 
        "is_lost": False, "river_safe": False, "knows_river_start": False, "waiting_teleport": False, "lost_by_river": False
    }
    if not players[sid]['is_man']: player_order.append(sid)
    sync_all()

@socketio.on('move')
def on_move(data):
    p = players.get(request.sid)
    if not check_turn(p) or p['waiting_teleport'] or p['injuries'] >= 5: return
    nx, ny = p['x'] + data['dx'], p['y'] + data['dy']
    blocked = False; bump = None
    if 0 <= nx < 10 and 0 <= ny < 10:
        if data['dx'] == 1 and maze[p['y']][nx]['walls']['left']: blocked = True; bump = {"x": nx, "y": p['y'], "dir": "left"}
        elif data['dx'] == -1 and maze[p['y']][p['x']]['walls']['left']: blocked = True; bump = {"x": p['x'], "y": p['y'], "dir": "left"}
        elif data['dy'] == 1 and maze[ny][p['x']]['walls']['top']: blocked = True; bump = {"x": p['x'], "y": ny, "dir": "top"}
        elif data['dy'] == -1 and maze[p['y']][p['x']]['walls']['top']: blocked = True; bump = {"x": p['x'], "y": p['y'], "dir": "top"}
    else: blocked = True

    if not blocked:
        edge = {"x": nx if data['dx']>=0 else p['x'], "y": ny if data['dy']>=0 else p['y'], "dir": 'top' if data['dy']!=0 else 'left'}
        if edge not in p['crossed_edges']: p['crossed_edges'].append(edge)
        p['x'], p['y'] = nx, ny
        if apply_tile(p): sync_all(); return 
        on_next()
    else:
        if bump and bump not in p['bumped_walls']: p['bumped_walls'].append(bump)
        emit('error_msg', "Blocked!"); sync_all(); return
    sync_all()

@socketio.on('shoot')
def on_shoot(data):
    p = players.get(request.sid)
    if not check_turn(p) or p['bul'] <= 0: return
    p['bul'] -= 1; dx, dy = data['dx'], data['dy']; sx, sy = p['x'], p['y']
    add_log(f"🔫 {p['n']} fired {get_dir_name(dx, dy)}!")
    for _ in range(10):
        if dx == 1 and (sx+1 >= 10 or maze[sy][sx+1]['walls']['left']): break
        if dx == -1 and maze[sy][sx]['walls']['left']: break
        if dy == 1 and (sy+1 >= 10 or maze[sy+1][sx]['walls']['top']): break
        if dy == -1 and maze[sy][sx]['walls']['top']: break
        sx += dx; sy += dy
        target = next((pl for pl in players.values() if not pl['is_man'] and pl['x'] == sx and pl['y'] == sy), None)
        if target: 
            target['injuries'] += 1; add_log(f"💥 {target['n']} hit!")
            if target['injuries'] >= 5: add_log(f"💀 {target['n']} eliminated!")
            break
    on_next(); sync_all()

@socketio.on('bomb')
def on_bomb(data):
    p = players.get(request.sid)
    if not check_turn(p) or p['bom'] <= 0: return
    dx, dy = data['dx'], data['dy']; tx, ty = p['x'], p['y']; p['bom'] -= 1
    if dx == 1: tx += 1
    if dy == 1: ty += 1
    wt = 'left' if dx != 0 else 'top'
    if 0 <= tx < 10 and 0 <= ty < 10 and maze[ty][tx]['walls'][wt]:
        maze[ty][tx]['walls'][wt] = False; add_log(f"💣 {p['n']} broke wall {get_dir_name(dx, dy)}!")
    else: add_log(f"💣 {p['n']} bombed {get_dir_name(dx, dy)}, but nothing was there!")
    on_next(); sync_all()

@socketio.on('use_flashlight')
def on_flash(data):
    p = players.get(request.sid)
    if not check_turn(p) or "flashlight" not in p['items'] or "batteries" not in p['items']:
        emit('error_msg', "Need Flashlight + Batteries!"); return
    dx, dy = data['dx'], data['dy']; fx, fy = p['x'], p['y']
    add_log(f"🔦 {p['n']} flashed {get_dir_name(dx, dy)}!")
    for _ in range(10):
        if dx == 1 and (fx+1 >= 10 or maze[fy][fx+1]['walls']['left']): break
        if dx == -1 and maze[fy][fx]['walls']['left']: break
        if dy == 1 and (fy+1 >= 10 or maze[fy+1][fx]['walls']['top']): break
        if dy == -1 and maze[fy][fx]['walls']['top']: break
        edge = {"x": fx+(1 if dx==1 else 0), "y": fy+(1 if dy==1 else 0), "dir": ("left" if dx!=0 else "top")}
        if edge not in p['crossed_edges']: p['crossed_edges'].append(edge)
        fx += dx; fy += dy
        t_list = p['post_lost_tiles'] if p['is_lost'] else p['known_tiles']
        if [fx, fy] not in t_list: t_list.append([fx, fy])
    on_next(); sync_all()

@socketio.on('set_spawn')
def on_sp(d):
    p = players.get(request.sid)
    if p and game_phase == 2:
        p['x'], p['y'] = d['x'], d['y']; p['has_spawned'] = True
        p['known_tiles'] = [[d['x'], d['y']]]
        p['walked_path'] = [[d['x'], d['y']]]
        maze[d['y']][d['x']]['is_birthplace'] = True
        maze[d['y']][d['x']]['birth_owner_id'] = p['id']
        maze[d['y']][d['x']]['birth_owner_name'] = p['n']
        add_log(f"👶 {p['n']} was born at {d['x']+1}, {d['y']+1}"); sync_all()

@socketio.on('update_maze')
def on_uz(d):
    global maze, river_start_pos
    if game_phase == 1:
        maze = d
        for y in range(10):
            for x in range(10):
                if maze[y][x]['tile'] == "river_start": river_start_pos = (x,y)
    sync_all()

@socketio.on('set_phase')
def on_ph(ph): 
    global game_phase; game_phase = int(ph.get('phase', ph) if isinstance(ph, dict) else ph); sync_all()

@socketio.on('host_teleport')
def on_h_tele(data):
    p_t = players.get(data['target_id'])
    if p_t: 
        p_t['x'], p_t['y'] = data['x'], data['y']
        p_t['waiting_teleport'] = False
        p_t['post_lost_tiles'].append([data['x'], data['y']])
        sync_all()

@socketio.on('next_turn')
def manual_next(): on_next(); sync_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
