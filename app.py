import os, random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'maze_rpg_ultimate'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# אתחול לוח: tile=נוכחי, was=חפץ שהיה, walls=קירות קיימים, ex_walls=קירות שנהרסו
maze = [[{
    "tile": "empty", 
    "was": None, 
    "walls": {"top": False, "left": False},
    "ex_walls": {"top": False, "left": False}
} for _ in range(10)] for _ in range(10)]

players = {}
player_order = []
current_turn_idx = 0
game_phase = 1 
game_logs = []
winner = None
river_start_pos = (0,0)

DIR_L = {(0, -1): "למעלה ↑", (0, 1): "למטה ↓", (-1, 0): "שמאלה ←", (1, 0): "ימינה →"}

def add_log(msg):
    game_logs.insert(0, msg)
    if len(game_logs) > 50: game_logs.pop()

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

@socketio.on('move')
def on_move(data):
    global winner
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['id'] != player_order[current_turn_idx] or winner: return
    
    dx, dy = data['dx'], data['dy']
    nx, ny = p['x'] + dx, p['y'] + dy
    dir_txt = DIR_L.get((dx,dy), "")

    # בדיקת קירות קיימים
    blocked = False
    passed_destroyed = False
    
    if 0 <= nx < 10 and 0 <= ny < 10:
        if dx == 1: 
            if maze[p['y']][nx]['walls']['left']: blocked = True
            if maze[p['y']][nx]['ex_walls']['left']: passed_destroyed = True
        if dx == -1: 
            if maze[p['y']][p['x']]['walls']['left']: blocked = True
            if maze[p['y']][p['x']]['ex_walls']['left']: passed_destroyed = True
        if dy == 1: 
            if maze[ny][p['x']]['walls']['top']: blocked = True
            if maze[ny][p['x']]['ex_walls']['top']: passed_destroyed = True
        if dy == -1: 
            if maze[p['y']][p['x']]['walls']['top']: blocked = True
            if maze[p['y']][p['x']]['ex_walls']['top']: passed_destroyed = True
    else: blocked = True

    if blocked:
        add_log(f"🧱 {p['n']} נתקע בקיר {dir_txt}.")
    else:
        if passed_destroyed:
            add_log(f"💨 {p['n']} עבר דרך הריסות של קיר שפוצץ.")
        
        p['x'], p['y'] = nx, ny
        tile_data = maze[ny][nx]
        curr = tile_data['tile']
        add_log(f"👣 {p['n']} זז {dir_txt}.")

        if curr == "empty" and tile_data['was']:
            add_log(f"👀 {p['n']} ראה איפה ה-{tile_data['was']} היה פעם.")
        
        elif curr == "river":
            if "boat" in p['items']: add_log(f"🛶 {p['n']} עבר את הנהר בבטחה.")
            elif "raft" in p['items']: p['x'], p['y'] = river_start_pos; add_log(f"🌊 {p['n']} נסחף להתחלה (מוגן).")
            else: p['x'], p['y'] = river_start_pos; p['injuries'] += 1; add_log(f"🌊 {p['n']} נסחף בנהר ונפצע!")
            
        elif curr == "exit" and "treasure" in p['items']:
            winner = p['n']; add_log(f"🏆 {p['n']} ניצח!")

        elif curr in ["treasure", "fake_treasure", "boat", "raft", "flashlight", "batteries", "armory", "monster", "devil", "clinic", "er", "black_hole"]:
            if curr == "armory": p['bul']=max(p['bul'],3); p['bom']=max(p['bom'],3); add_log(f"⚔️ {p['n']} התחמש.")
            elif curr == "black_hole": p['x'],p['y']=random.randint(0,9),random.randint(0,9); add_log(f"🕳️ {p['n']} השתגר!")
            elif curr == "devil": p['injuries']+=1; add_log(f"😈 {p['n']} נפגע מהשטן!")
            elif curr == "clinic": p['injuries']=0; add_log(f"🏥 {p['n']} התרפא.")
            else: 
                if curr not in ["monster", "er"]:
                    p['items'].append(curr); tile_data['was']=curr; tile_data['tile']="empty"; add_log(f"📦 {p['n']} אסף {curr}.")
                else: add_log(f"✨ {p['n']} הגיע למשבצת {curr}.")

        if [p['x'], p['y']] not in p['known_tiles']: p['known_tiles'].append([p['x'], p['y']])
    sync_all()

@socketio.on('bomb')
def on_bomb(data):
    p = players.get(request.sid)
    if not p or p['bom'] <= 0 or p['id'] != player_order[current_turn_idx]: return
    dx, dy = data['dx'], data['dy']; tx, ty = p['x'], p['y']; wt = ""
    if dx == 1 and p['x'] < 9: tx += 1; wt = "left"
    elif dx == -1: wt = "left"
    elif dy == 1 and p['y'] < 9: ty += 1; wt = "top"
    elif dy == -1: wt = "top"
    
    if wt and maze[ty][tx]['walls'][wt]:
        maze[ty][tx]['walls'][wt] = False
        maze[ty][tx]['ex_walls'][wt] = True # שמירה שהיה כאן קיר
        p['bom'] -= 1; add_log(f"💣 {p['n']} פוצץ קיר {DIR_L.get((dx,dy))}.")
    sync_all()

@socketio.on('shoot')
def on_shoot(data):
    p = players.get(request.sid)
    if not p or p['bul'] <= 0 or p['id'] != player_order[current_turn_idx]: return
    p['bul'] -= 1; dx, dy = data['dx'], data['dy']; sx, sy = p['x'], p['y']
    add_log(f"🔫 {p['n']} ירה {DIR_L.get((dx,dy))}.")
    for _ in range(10):
        if dx == 1 and (sx + 1 >= 10 or maze[sy][sx+1]['walls']['left']): break
        if dx == -1 and maze[sy][sx]['walls']['left']: break
        if dy == 1 and (sy + 1 >= 10 or maze[sy+1][sx]['walls']['top']): break
        if dy == -1 and maze[sy][sx]['walls']['top']: break
        sx += dx; sy += dy
        target = next((pl for pl in players.values() if not pl['is_man'] and pl['x'] == sx and pl['y'] == sy), None)
        if target: target['injuries'] += 1; add_log(f"💥 פגיעה ב-{target['n']}!"); break
    sync_all()

@socketio.on('next_turn')
def on_next():
    global current_turn_idx
    if player_order: current_turn_idx = (current_turn_idx + 1) % len(player_order); sync_all()

@socketio.on('set_phase')
def on_ph(ph): global game_phase; game_phase=int(ph); sync_all()

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
