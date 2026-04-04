import os, random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'castle_maze_ultimate_2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

maze = [[{
    "tile": "empty", 
    "collected": False, 
    "walls": {"top": False, "left": False},
    "ex_walls": {"top": {"broken": False, "by": ""}, "left": {"broken": False, "by": ""}},
    "visited_by": [],
    "dropped_items": [] 
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

def sync_all():
    p_list = [p for p in players.values() if not p['is_man']]
    alive = [p for p in p_list if p['injuries'] < 5]
    global winner
    if not winner and len(p_list) > 1 and len(alive) == 1:
        winner = alive[0]['n']
        add_log(f"🏆 {winner} is the Last Survivor and wins!")

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

def share_visuals(p1, p2, p1_dest, p2_dest):
    """Shares all visual tracking data between two players based on their lost/not-lost status."""
    for t in p1[p1_dest]:
        if t not in p2[p2_dest]: p2[p2_dest].append(t)
    for t in p2[p2_dest]:
        if t not in p1[p1_dest]: p1[p1_dest].append(t)
    
    # Share paths, safe lines, and bumped walls
    for k in ['walked_path', 'crossed_edges', 'bumped_walls']:
        for item in p1[k]:
            if item not in p2[k]: p2[k].append(item)
        for item in p2[k]:
            if item not in p1[k]: p1[k].append(item)

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
    if not p: return False
    if game_phase != 3: 
        emit('error_msg', "Game has not started yet!")
        return False
    if not player_order or p['id'] != player_order[current_turn_idx]:
        emit('error_msg', "Not your turn!")
        return False
    return True

def apply_tile(p):
    nx, ny = p['x'], p['y']
    tile = maze[ny][nx]

    if tile['dropped_items']:
        for item in tile['dropped_items']:
            p['items'].append(item)
            add_log(f"🎒 {p['n']} picked up a dropped {item}!")
        tile['dropped_items'] = []

    # 1. Un-Lose Check (Must happen BEFORE Map Fusion)
    if p['is_lost']:
        if p['n'] in tile['visited_by']:
            clear_lost(p)
        elif tile['tile'] == "river_start" and p.get('lost_by_river'):
            clear_lost(p)

    # 2. Realistic Map Fusion
    for other in [pl for pl in players.values() if not pl['is_man'] and pl['id'] != p['id']]:
        if other['x'] == nx and other['y'] == ny and other['has_spawned'] and other['injuries'] < 5:
            if not p['is_lost'] and not other['is_lost']:
                share_visuals(p, other, 'known_tiles', 'known_tiles')
                add_log(f"🤝 {p['n']} and {other['n']} met and shared maps!")
            elif p['is_lost'] and not other['is_lost']:
                share_visuals(p, other, 'post_lost_tiles', 'known_tiles')
                add_log(f"🤝 {p['n']} (Lost) copied {other['n']}'s map into their void!")
            elif not p['is_lost'] and other['is_lost']:
                share_visuals(p, other, 'known_tiles', 'post_lost_tiles')
                add_log(f"🤝 {other['n']} (Lost) copied {p['n']}'s map into their void!")
            else:
                share_visuals(p, other, 'post_lost_tiles', 'post_lost_tiles')
                add_log(f"🤝 {p['n']} and {other['n']} bumped into each other and merged their void maps!")

    # 3. Mark Visited
    if p['n'] not in tile['visited_by'] and tile['tile'] not in ["empty", "river"]:
        tile['visited_by'].append(p['n'])

    # 4. Process Item/Tile Effects
    item_name = tile['tile']
    
    if item_name == "river":
        # Immune if they have a boat OR if they are safely continuing from the start
        if "boat" in p['items'] or p.get('river_safe'):
            add_log(f"🛶 {p['n']} navigated the river safely.")
            p['river_safe'] = True 
        else:
            p['x'], p['y'] = river_start_pos
            if "raft" not in p['items']: p['injuries'] += 1
            if not p['knows_river_start']:
                p['is_lost'] = True
                p['lost_by_river'] = True
                p['post_lost_tiles'] = []
            else: 
                clear_lost(p)
                p['lost_by_river'] = False
            p['river_safe'] = True # Grants immunity to continue path next turn
            add_log(f"🌊 {p['n']} was swept away to the start!")
            maze[river_start_pos[1]][river_start_pos[0]]['visited_by'].append(p['n'])

    elif item_name == "river_start":
        p['knows_river_start'] = True
        p['river_safe'] = True # Starting here gives immunity to walk on the river
    else:
        p['river_safe'] = False # Lose river immunity if stepping on land
        
        if item_name == "black_hole":
            p['is_lost'] = True; p['waiting_teleport'] = True; p['post_lost_tiles'] = []
            p['lost_by_river'] = False
            add_log(f"🕳️ {p['n']} fell into a Black Hole!")
        elif item_name == "monster":
            p['bul'] = min(5, p['bul']+1); p['bom'] = min(5, p['bom']+1)
            add_log(f"👾 Monster gave {p['n']} gear and an extra turn!")
            return True # Extra turn
        elif item_name == "devil":
            p['injuries'] += 1; p['bul'] = max(0, p['bul']-1); p['bom'] = max(0, p['bom']-1)
            add_log(f"😈 Devil attacked {p['n']}!")
        elif item_name == "exit":
            if "treasure" in p['items']:
                global winner; winner = p['n']
                add_log(f"🏆 {p['n']} escaped with the treasure and won!")
        elif item_name in ["treasure", "fake_treasure", "boat", "raft", "flashlight", "batteries", "clinic", "er", "armory"]:
            if item_name == "clinic" and p['injuries'] < 4: p['injuries'] = 0; add_log(f"✨ {p['n']} reached {item_name}.")
            elif item_name == "er" and p['injuries'] == 4: p['injuries'] = 3; add_log(f"✨ {p['n']} reached {item_name}.")
            elif item_name == "armory": p['bul']=3; p['bom']=3; add_log(f"✨ {p['n']} reached {item_name}.")
            else:
                if tile['collected']:
                    add_log(f"👀 {p['n']} found where {item_name} used to be.")
                else:
                    p['items'].append(item_name)
                    tile['collected'] = True
                    add_log(f"✨ {p['n']} collected {item_name}.")

    if p['injuries'] >= 5:
        add_log(f"💀 {p['n']} has died!")
        tile['dropped_items'].extend(p['items'])
        p['items'] = []

    # 5. Visual Path Tracking
    curr_c = [p['x'], p['y']]
    if curr_c not in (p['post_lost_tiles'] if p['is_lost'] else p['known_tiles']):
        (p['post_lost_tiles'] if p['is_lost'] else p['known_tiles']).append(curr_c)
        
    if curr_c not in p['walked_path']:
        p['walked_path'].append(curr_c)

    # 6. THE 10x10 RULE (Now checks BOTH horizontal AND vertical boundaries!)
    if p['is_lost'] and len(p['post_lost_tiles']) > 0:
        xs = [t[0] for t in p['post_lost_tiles']]
        ys = [t[1] for t in p['post_lost_tiles']]
        if (max(xs) - min(xs) >= 9) and (max(ys) - min(ys) >= 9):
            add_log(f"🧭 {p['n']}'s map stretched 10x10. They figured out the boundaries!")
            clear_lost(p)

    return False

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
        "has_spawned": False, "known_tiles": [], "post_lost_tiles": [], "crossed_edges": [],
        "bumped_walls": [], "walked_path": [],
        "is_lost": False, "lost_by_river": False, "river_safe": False, "waiting_teleport": False, "knows_river_start": False
    }
    if not is_man and request.sid not in player_order: player_order.append(request.sid)
    sync_all()

@socketio.on('move')
def on_move(data):
    p = players.get(request.sid)
    if not check_turn(p): return
    if p['waiting_teleport']: 
        emit('error_msg', "You fell into a Black Hole! Wait for the Host.")
        return
    if p['injuries'] >= 5:
        emit('error_msg', "You are dead!")
        return
    
    nx, ny = p['x'] + data['dx'], p['y'] + data['dy']
    blocked = False
    wall_key = 'top' if data['dy'] != 0 else 'left'
    bump = None
    
    if 0 <= nx < 10 and 0 <= ny < 10:
        if data['dx'] == 1 and maze[p['y']][nx]['walls']['left']: 
            blocked = True; bump = {"x": nx, "y": p['y'], "dir": "left"}
        elif data['dx'] == -1 and maze[p['y']][p['x']]['walls']['left']: 
            blocked = True; bump = {"x": p['x'], "y": p['y'], "dir": "left"}
        elif data['dy'] == 1 and maze[ny][p['x']]['walls']['top']: 
            blocked = True; bump = {"x": p['x'], "y": ny, "dir": "top"}
        elif data['dy'] == -1 and maze[p['y']][p['x']]['walls']['top']: 
            blocked = True; bump = {"x": p['x'], "y": p['y'], "dir": "top"}
    else: 
        blocked = True

    if not blocked:
        target_w = maze[ny][nx] if (data['dx']==1 or data['dy']==1) else maze[p['y']][p['x']]
        if target_w['ex_walls'][wall_key]['broken']:
            add_log(f"🕵️ {p['n']} passed through a broken wall.")

        edge = None
        if data['dy'] == 1: edge = {"x": nx, "y": ny, "dir": "top"}
        elif data['dy'] == -1: edge = {"x": p['x'], "y": p['y'], "dir": "top"}
        elif data['dx'] == 1: edge = {"x": nx, "y": ny, "dir": "left"}
        elif data['dx'] == -1: edge = {"x": p['x'], "y": p['y'], "dir": "left"}
        
        if edge and edge not in p['crossed_edges']:
            p['crossed_edges'].append(edge)

        p['x'], p['y'] = nx, ny
        
        extra_turn = apply_tile(p)
        if extra_turn:
            sync_all()
            return 
        on_next()
    else:
        if bump and bump not in p['bumped_walls']:
            p['bumped_walls'].append(bump)
        emit('error_msg', "Blocked by a wall!")
        sync_all()
        return
    sync_all()

@socketio.on('shoot')
def on_shoot(data):
    p = players.get(request.sid)
    if not check_turn(p): return
    if p['bul'] <= 0:
        emit('error_msg', "Out of bullets!")
        return
        
    p['bul'] -= 1; dx, dy = data['dx'], data['dy']; sx, sy = p['x'], p['y']
    add_log(f"🔫 {p['n']} fired a shot!")
    for _ in range(10):
        if dx == 1 and (sx+1 >= 10 or maze[sy][sx+1]['walls']['left']): break
        if dx == -1 and maze[sy][sx]['walls']['left']: break
        if dy == 1 and (sy+1 >= 10 or maze[sy+1][sx]['walls']['top']): break
        if dy == -1 and maze[sy][sx]['walls']['top']: break
        sx += dx; sy += dy
        target = next((pl for pl in players.values() if not pl['is_man'] and pl['x'] == sx and pl['y'] == sy), None)
        if target: 
            target['injuries'] += 1
            add_log(f"💥 {target['n']} was hit!")
            if target['injuries'] >= 5:
                add_log(f"💀 {target['n']} was eliminated by a shot!")
                maze[sy][sx]['dropped_items'].extend(target['items'])
                target['items'] = []
            break
    on_next()
    sync_all()

@socketio.on('bomb')
def on_bomb(data):
    p = players.get(request.sid)
    if not check_turn(p): return
    if p['bom'] <= 0:
        emit('error_msg', "Out of bombs!")
        return
        
    dx, dy = data['dx'], data['dy']; tx, ty = p['x'], p['y']
    wt = 'left' if dx != 0 else 'top'
    if dx == 1: tx += 1
    if dy == 1: ty += 1
    if 0 <= tx < 10 and 0 <= ty < 10 and maze[ty][tx]['walls'][wt]:
        maze[ty][tx]['walls'][wt] = False
        maze[ty][tx]['ex_walls'][wt] = {"broken": True, "by": p['n']}
        p['bom'] -= 1
        add_log(f"💣 {p['n']} broke a wall.")
        on_next()
    else:
        emit('error_msg', "No wall there to break!")
        return
    sync_all()

@socketio.on('use_flashlight')
def on_flash(data):
    p = players.get(request.sid)
    if not check_turn(p): return
    if "flashlight" not in p['items'] or "batteries" not in p['items']:
        emit('error_msg', "You need both a Flashlight and Batteries!")
        return
        
    dx, dy = data['dx'], data['dy']; fx, fy = p['x'], p['y']
    add_log(f"🔦 {p['n']} used the flashlight!")
    for _ in range(10):
        if dx == 1 and (fx+1 >= 10 or maze[fy][fx+1]['walls']['left']): break
        if dx == -1 and maze[fy][fx]['walls']['left']: break
        if dy == 1 and (fy+1 >= 10 or maze[fy+1][fx]['walls']['top']): break
        if dy == -1 and maze[fy][fx]['walls']['top']: break
        fx += dx; fy += dy
        if [fx, fy] not in p['known_tiles']: p['known_tiles'].append([fx, fy])
    on_next()
    sync_all()

@socketio.on('host_teleport')
def on_h_tele(data):
    p_t = players.get(data['target_id'])
    if p_t:
        p_t['x'], p_t['y'] = data['x'], data['y']; p_t['waiting_teleport'] = False
        p_t['post_lost_tiles'].append([data['x'], data['y']])
        if [data['x'], data['y']] not in p_t['walked_path']:
            p_t['walked_path'].append([data['x'], data['y']])
        sync_all()

@socketio.on('set_phase')
def on_ph(ph): 
    global game_phase, current_turn_idx
    game_phase = int(ph.get('phase', ph) if isinstance(ph, dict) else ph)
    if game_phase == 3 and player_order:
        for pid in player_order:
            p = players.get(pid)
            if p and p['has_spawned'] and p['injuries'] < 5:
                apply_tile(p)
        for i in range(len(player_order)):
            p = players.get(player_order[i])
            if p and p['injuries'] < 5 and p['has_spawned']:
                current_turn_idx = i
                break
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
        p['x'], p['y'] = d['x'], d['y']; p['has_spawned'] = True; 
        p['known_tiles'] = [[d['x'], d['y']]]
        p['walked_path'] = [[d['x'], d['y']]]
        sync_all()

@socketio.on('next_turn')
def manual_next(): on_next(); sync_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
