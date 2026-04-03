import os, random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'maze_fusion_system_2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# maze[y][x] structure
maze = [[{
    "tile": "empty", 
    "was": None, 
    "walls": {"top": False, "left": False},
    "visited_by": [] # רשימת שמות שחקנים שביקרו כאן
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
        "has_spawned": False, 
        "known_tiles": [], # List of [x, y]
        "post_lost_tiles": [], # ידע שנצבר רק בזמן שהיה אבוד
        "is_lost": False,
        "knows_river_start": False
    }
    if not is_man and request.sid not in player_order: player_order.append(request.sid)
    sync_all()

@socketio.on('move')
def on_move(data):
    global winner
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['id'] != player_order[current_turn_idx] or winner: return
    
    dx, dy = data['dx'], data['dy']
    nx, ny = p['x'] + dx, p['y'] + dy
    
    blocked = False
    if 0 <= nx < 10 and 0 <= ny < 10:
        if dx == 1 and maze[p['y']][nx]['walls']['left']: blocked = True
        if dx == -1 and maze[p['y']][p['x']]['walls']['left']: blocked = True
        if dy == 1 and maze[ny][p['x']]['walls']['top']: blocked = True
        if dy == -1 and maze[p['y']][p['x']]['walls']['top']: blocked = True
    else: blocked = True

    if not blocked:
        p['x'], p['y'] = nx, ny
        tile = maze[ny][nx]
        tile_name = tile['tile'] if tile['tile'] != "empty" else tile['was']

        # 1. בדיקת יציאה ממצב Lost (אם ביקר כאן בעבר)
        if p['is_lost'] and p['n'] in tile['visited_by']:
            p['is_lost'] = False
            add_log(f"🧠 {p['n']} זיהה את האזור ויצא ממצב אבוד!")

        # 2. עדכון רשימת מבקרים (רק למשבצות שאינן ריקות/נהר)
        if tile_name and tile_name not in ["empty", "river"]:
            if p['n'] not in tile['visited_by']:
                tile['visited_by'].append(p['n'])

        # 3. מנגנון מיזוג מפות (Map Fusion)
        if tile_name and tile_name not in ["empty", "river"]:
            for other_id, other_p in players.items():
                if other_id != request.sid and not other_p['is_man']:
                    # אם השחקן השני כבר ביקר כאן בעבר
                    if other_p['n'] in tile['visited_by']:
                        # מיזוג ידע: השני מקבל את כל מה שהנוכחי גילה
                        # אם הנוכחי אבוד, הוא מעביר רק את מה שגילה מאז שהלך לאיבוד
                        tiles_to_share = p['post_lost_tiles'] if p['is_lost'] else p['known_tiles']
                        
                        # הוספת הידע לשחקן השני
                        for t in tiles_to_share:
                            if t not in other_p['known_tiles']: other_p['known_tiles'].append(t)
                        
                        # אם הנוכחי לא אבוד, הוא מקבל גם את הידע של השני
                        if not p['is_lost']:
                            for t in other_p['known_tiles']:
                                if t not in p['known_tiles']: p['known_tiles'].append(t)
                        
                        add_log(f"🔗 מפות מוזגו! {p['n']} ו-{other_p['n']} חולקים מידע דרך ה-{tile_name}.")

        # 4. אפקטים מיוחדים
        if tile['tile'] == "river":
            p['x'], p['y'] = river_start_pos
            if not p['knows_river_start']:
                p['is_lost'] = True
                p['post_lost_tiles'] = [] # איפוס ידע אבוד חדש
            if "boat" not in p['items']: p['injuries'] += 1
            add_log(f"🌊 {p['n']} נסחף בנהר!")

        elif tile['tile'] == "black_hole":
            p['x'], p['y'] = random.randint(0,9), random.randint(0,9)
            p['is_lost'] = True
            p['post_lost_tiles'] = []
            add_log(f"🕳️ {p['n']} נשאב לחור שחור ואבד!")

        elif tile['tile'] == "river_start":
            p['knows_river_start'] = True
            add_log(f"📍 {p['n']} גילה את מקור הנהר.")

        # איסוף חפצים (לוגיקה רגילה)
        if tile['tile'] in ["treasure", "fake_treasure", "boat", "raft", "flashlight", "batteries"]:
            p['items'].append(tile['tile'])
            tile['was'] = tile['tile']
            tile['tile'] = "empty"

        # עדכון ידע מפה
        current_pos = [p['x'], p['y']]
        if current_pos not in p['known_tiles']:
            p['known_tiles'].append(current_pos)
            if p['is_lost']:
                p['post_lost_tiles'].append(current_pos)

    sync_all()

@socketio.on('set_phase')
def on_set_ph(d):
    global game_phase; game_phase = int(d.get('phase', d) if isinstance(d, dict) else d); sync_all()

@socketio.on('update_maze')
def on_uz(d):
    global maze, river_start_pos
    if game_phase == 1:
        maze = d
        for y in range(10):
            for x in range(10):
                if maze[y][x]['tile'] == "river_start": river_start_pos = (x,y)
    sync_all()

@socketio.on('next_turn')
def on_next():
    global current_turn_idx
    if player_order: current_turn_idx = (current_turn_idx + 1) % len(player_order); sync_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)
