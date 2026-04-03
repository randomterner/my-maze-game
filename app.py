import os, random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'maze_ultimate_fusion_2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# אתחול הלוח לפי החוקים 
maze = [[{
    "tile": "empty", "was": None, 
    "walls": {"top": False, "left": False},
    "ex_walls": {"top": {"broken": False, "by": ""}, "left": {"broken": False, "by": ""}},
    "visited_by": [] # רשימת שמות השחקנים שביקרו כאן
} for _ in range(10)] for _ in range(10)]

players = {}
player_order = []
current_turn_idx = 0
game_phase = 1 # 1: Build, 2: Spawn, 3: Play
game_logs = []
winner = None
river_start_pos = (-1, -1)

DIR_MAP = {(0, -1): "צפון", (0, 1): "דרום", (-1, 0): "מערב", (1, 0): "מזרח"}

def add_log(msg):
    game_logs.insert(0, msg)
    if len(game_logs) > 50: game_logs.pop()

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
        "is_lost": False, "knows_river": False
    }
    if not is_man and request.sid not in player_order: player_order.append(request.sid)
    sync_all()

@socketio.on('move')
def on_move(data):
    global winner
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['id'] != player_order[current_turn_idx] or winner or p['injuries'] >= 5: return
    
    dx, dy = data['dx'], data['dy']
    nx, ny = p['x'] + dx, p['y'] + dy
    
    # בדיקת קירות (חיצוניים ופנימיים) 
    blocked = False
    wall_type = None
    if 0 <= nx < 10 and 0 <= ny < 10:
        if dx == 1 and maze[p['y']][nx]['walls']['left']: blocked = True; wall_type = 'left'
        elif dx == -1 and maze[p['y']][p['x']]['walls']['left']: blocked = True; wall_type = 'left'
        elif dy == 1 and maze[ny][p['x']]['walls']['top']: blocked = True; wall_type = 'top'
        elif dy == -1 and maze[p['y']][p['x']]['walls']['top']: blocked = True; wall_type = 'top'
    else: blocked = True

    if blocked:
        add_log(f"🧱 {p['n']} נתקע בקיר.")
    else:
        # לוגיקת עקבות על קיר שבור
        target_cell = maze[ny][nx] if dx == 1 or dy == 1 else maze[p['y']][p['x']]
        w_key = 'left' if dx != 0 else 'top'
        if target_cell['ex_walls'][w_key]['broken']:
            count = sum(1 for row in maze for c in row if c['ex_walls'][w_key]['broken'])
            if count == 1 and (not p['is_lost'] or p['knows_river']):
                breaker = target_cell['ex_walls'][w_key]['by']
                b_obj = next((pl for pl in players.values() if pl['n'] == breaker), None)
                if b_obj: add_log(f"🔎 {p['n']} עבר בקיר ש-{breaker} שבר. הוא נמצא ב-{get_rel_dir(p, b_obj)}.")

        p['x'], p['y'] = nx, ny
        tile = maze[ny][nx]
        
        # יציאה ממצב אבוד אם זיהה משבצת שביקר בה 
        if p['is_lost'] and p['n'] in tile['visited_by']: p['is_lost'] = False

        # רישום ביקור ומיזוג מפות
        tile_name = tile['tile'] if tile['tile'] != "empty" else tile['was']
        if tile_name and tile_name not in ["empty", "river"]:
            if p['n'] not in tile['visited_by']: tile['visited_by'].append(p['n'])
            for other in [pl for pl in players.values() if not pl['is_man'] and pl['n'] in tile['visited_by'] and pl['n'] != p['n']]:
                # Fusion
                source = p['post_lost_tiles'] if p['is_lost'] else p['known_tiles']
                for t in source:
                    if t not in other['known_tiles']: other['known_tiles'].append(t)
                if not p['is_lost']:
                    for t in other['known_tiles']:
                        if t not in p['known_tiles']: p['known_tiles'].append(t)
                add_log(f"🤝 מפות של {p['n']} ו-{other['n']} מוזגו!")

        # אפקטים של משבצות 
        if tile['tile'] == "river":
            p['x'], p['y'] = river_start_pos
            if not p['knows_river']: p['is_lost'] = True; p['post_lost_tiles'] = []
            if "boat" not in p['items'] and "raft" not in p['items']: p['injuries'] += 1; add_log(f"🌊 {p['n']} נסחף ונפצע!")
            elif "raft" in p['items']: add_log(f"🌊 {p['n']} נסחף (מוגן ע\"י רפסודה).")
            else: p['x'], p['y'] = nx, ny; add_log(f"🛶 {p['n']} עבר בנהר עם סירה.")
        
        elif tile['tile'] == "black_hole":
            p['x'], p['y'] = random.randint(0,9), random.randint(0,9); p['is_lost'] = True; p['post_lost_tiles'] = []
            add_log(f"🕳️ {p['n']} נשאב לחור שחור ואבד!")
        
        elif tile['tile'] == "river_start": p['knows_river'] = True; add_log(f"📍 {p['n']} מצא את מקור הנהר.")
        elif tile['tile'] == "monster": 
            p['bul'] = min(5, p['bul']+1); p['bom'] = min(5, p['bom']+1); add_log(f"👾 {p['n']} קיבל ציוד ותור נוסף!"); return 
        elif tile['tile'] == "devil": p['injuries']+=1; p['bul']=max(0,p['bul']-1); p['bom']=max(0,p['bom']-1); add_log(f"😈 {p['n']} פגש שטן!")
        elif tile['tile'] == "clinic" and p['injuries'] < 4: p['injuries'] = 0; add_log(f"🏥 {p['n']} התרפא.")
        elif tile['tile'] == "er" and p['injuries'] == 4: p['injuries'] = 3; add_log(f"🚑 {p['n']} קיבל עזרה ראשונה.")
        elif tile['tile'] == "armory": p['bul']=3; p['bom']=3; add_log(f"⚔️ {p['n']} התחמש.")
        elif tile['tile'] == "exit" and "treasure" in p['items']: winner = p['n']; add_log(f"🏆 {p['n']} ניצח!")
        
        elif tile['tile'] in ["treasure", "fake_treasure", "boat", "raft", "flashlight", "batteries"]:
            p['items'].append(tile['tile']); tile['was'] = tile['tile']; tile['tile'] = "empty"; add_log(f"📦 {p['n']} אסף {tile['was']}.")

        curr_pos = [p['x'], p['y']]
        if curr_pos not in p['known_tiles']: 
            p['known_tiles'].append(curr_pos)
            if p['is_lost']: p['post_lost_tiles'].append(curr_pos)
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
        target = next((pl for pl in players.values() if not pl['is_man'] and pl['x'] == sx and pl['y'] == sy), None)
        if target: target['injuries'] += 1; add_log(f"💥 פגיעה ב-{target['n']}!"); break
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

@socketio.on('next_turn')
def on_next():
    global current_turn_idx
    if player_order: current_turn_idx = (current_turn_idx + 1) % len(player_order); sync_all()

@socketio.on('set_phase')
def on_ph(ph): global game_phase; game_phase=int(ph.get('phase',ph) if isinstance(ph,dict) else ph); sync_all()

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
    p=players.get(request.sid)
    if p: p['x'],p['y']=d['x'],d['y']; p['has_spawned']=True; p['known_tiles']=[[d['x'],d['y']]]; sync_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
