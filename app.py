import os, random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'maze_rpg_system'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# מצב המשחק
maze = [[{"tile": "empty", "was": None, "walls": {"top": False, "left": False}} for _ in range(10)] for _ in range(10)]
players = {}
player_order = []
current_turn_idx = 0
game_phase = 1 
game_logs = []
winner = None
river_start_pos = (0,0)

# מפת כיוונים ללוג
DIR_MAP = {(0, -1): "למעלה (Up)", (0, 1): "למטה (Down)", (-1, 0): "שמאלה (Left)", (1, 0): "ימינה (Right)"}

def add_log(msg):
    game_logs.insert(0, msg)
    if len(game_logs) > 40: game_logs.pop()

def check_win_conditions():
    global winner
    if winner: return

    p_list = [p for p in players.values() if not p['is_man']]
    alive_players = [p for p in p_list if p['injuries'] < 5]

    # תנאי 1: שורד אחרון
    if len(p_list) > 1 and len(alive_players) == 1:
        winner = alive_players[0]['n']
        add_log(f"🏆 {winner} הוא השורד האחרון וניצח במשחק!")
    
    # תנאי 2: אוצר + יציאה נבדק בתוך פונקציית התנועה

def sync_all():
    check_win_conditions()
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
    dir_name = DIR_MAP.get((dx, dy), "לא ידוע")
    nx, ny = p['x'] + dx, p['y'] + dy

    # בדיקת קירות
    blocked = False
    if 0 <= nx < 10 and 0 <= ny < 10:
        if dx == 1 and maze[p['y']][nx]['walls']['left']: blocked = True
        if dx == -1 and maze[p['y']][p['x']]['walls']['left']: blocked = True
        if dy == 1 and maze[ny][p['x']]['walls']['top']: blocked = True
        if dy == -1 and maze[p['y']][p['x']]['walls']['top']: blocked = True
    else: blocked = True

    if blocked:
        add_log(f"🧱 {p['n']} ניסה לזוז {dir_name} אך נתקע בקיר.")
    else:
        p['x'], p['y'] = nx, ny
        tile_data = maze[ny][nx]
        tile_type = tile_data['tile']

        add_log(f"👣 {p['n']} זז {dir_name}.")

        # לוגיקה של משבצות עם זיכרון
        if tile_type == "empty" and tile_data['was']:
            add_log(f"👀 {p['n']} עבר במקום שבו ה-{tile_data['was']} היה פעם.")

        elif tile_type == "river":
            if "boat" in p['items']: add_log(f"🛶 {p['n']} חצה את הנהר עם סירה.")
            elif "raft" in p['items']: p['x'], p['y'] = river_start_pos; add_log(f"🌊 {p['n']} נסחף להתחלה (הרפסודה הגנה מפציעה).")
            else: p['x'], p['y'] = river_start_pos; p['injuries'] += 1; add_log(f"🌊 {p['n']} נסחף בנהר ונפצע!")

        elif tile_type == "armory":
            p['bul'] = max(p['bul'], 3); p['bom'] = max(p['bom'], 3)
            add_log(f"⚔️ {p['n']} נכנס לנשקייה והתחמש.")

        elif tile_type == "exit":
            if "treasure" in p['items']:
                winner = p['n']
                add_log(f"🏆 {p['n']} יצא מהמבוך עם האוצר וניצח!")
            else:
                add_log(f"🚪 {p['n']} הגיע ליציאה, אך אין לו את האוצר.")

        elif tile_type in ["treasure", "fake_treasure", "boat", "raft", "flashlight", "batteries"]:
            p['items'].append(tile_type)
            tile_data['was'] = tile_type # שמירת זיכרון מה היה כאן
            tile_data['tile'] = "empty"
            add_log(f"🎁 {p['n']} מצא {tile_type}!")

        if [p['x'], p['y']] not in p['known_tiles']: p['known_tiles'].append([p['x'], p['y']])
    sync_all()

@socketio.on('shoot')
def on_shoot(data):
    p = players.get(request.sid)
    if not p or p['bul'] <= 0 or p['id'] != player_order[current_turn_idx]: return
    p['bul'] -= 1
    dx, dy = data['dx'], data['dy']
    dir_name = DIR_MAP.get((dx, dy), "לא ידוע")
    add_log(f"🔫 {p['n']} ירה לכיוון {dir_name}.")
    
    sx, sy = p['x'], p['y']
    for _ in range(10):
        if dx == 1 and (sx + 1 >= 10 or maze[sy][sx+1]['walls']['left']): break
        if dx == -1 and maze[sy][sx]['walls']['left']: break
        if dy == 1 and (sy + 1 >= 10 or maze[sy+1][sx]['walls']['top']): break
        if dy == -1 and maze[sy][sx]['walls']['top']: break
        sx += dx; sy += dy
        target = next((pl for pl in players.values() if not pl['is_man'] and pl['x'] == sx and pl['y'] == sy), None)
        if target:
            target['injuries'] += 1
            add_log(f"💥 הפגיעה! {target['n']} ספג פציעה מ-{p['n']}.")
            break
    sync_all()

@socketio.on('bomb')
def on_bomb(data):
    p = players.get(request.sid)
    if not p or p['bom'] <= 0 or p['id'] != player_order[current_turn_idx]: return
    dx, dy = data['dx'], data['dy']
    dir_name = DIR_MAP.get((dx, dy), "לא ידוע")
    
    tx, ty = p['x'], p['y']
    wt = ""
    if dx == 1 and p['x'] < 9: tx += 1; wt = "left"
    elif dx == -1: wt = "left"
    elif dy == 1 and p['y'] < 9: ty += 1; wt = "top"
    elif dy == -1: wt = "top"

    if wt and maze[ty][tx]['walls'][wt]:
        maze[ty][tx]['walls'][wt] = False
        p['bom'] -= 1
        add_log(f"💣 {p['n']} פוצץ את הקיר {dir_name}.")
    else:
        add_log(f"🧨 {p['n']} ניסה לפוצץ קיר {dir_name} אך אין שם קיר.")
    sync_all()

@socketio.on('next_turn')
def on_next_turn():
    global current_turn_idx
    if not player_order: return
    current_turn_idx = (current_turn_idx + 1) % len(player_order)
    sync_all()

@socketio.on('update_maze')
def on_update_maze(d):
    global maze
    if game_phase == 1: maze = d
    sync_all()

@socketio.on('set_phase')
def on_set_phase(ph):
    global game_phase; game_phase = int(ph); sync_all()

@socketio.on('set_spawn')
def on_set_spawn(d):
    p = players.get(request.sid)
    if p: p['x'],p['y']=d['x'],d['y']; p['has_spawned']=True; p['known_tiles']=[[d['x'],d['y']]]; sync_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
