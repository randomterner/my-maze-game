import os, random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'maze_secret_family'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)

# מצב המשחק
maze = [[{"tile": "empty", "walls": {"top": False, "left": False}} for _ in range(10)] for _ in range(10)]
players = {}
game_phase = 1 # 1: Build, 2: Spawn, 3: Start
game_logs = []
winner = None
river_start_pos = (0,0)

def add_log(msg):
    game_logs.insert(0, msg)
    if len(game_logs) > 40: game_logs.pop()

def sync_all():
    p_list = [p for p in players.values() if not p['is_man']]
    
    # בדיקת ניצחון (שורד אחרון)
    alive = [p for p in p_list if p['injuries'] < 5]
    global winner
    if len(p_list) > 1 and len(alive) == 1 and not winner and game_phase == 3:
        winner = alive[0]['n']
        add_log(f"🏆 {winner} הוא השורד האחרון וניצח במשחק!")

    socketio.emit('sync', {
        "maze": maze, "players": p_list, "phase": game_phase,
        "logs": game_logs, "winner": winner
    })

@app.route('/')
def index(): return render_template('index.html')

@app.route('/manager')
def manager(): return render_template('manager.html')

@socketio.on('join')
def on_join(data):
    players[request.sid] = {
        "id": request.sid, "n": data.get('name', 'שחקן'), "is_man": data.get('is_man', False),
        "x": 0, "y": 0, "injuries": 0, "bul": 3, "bom": 3, "items": [], 
        "has_spawned": False, "known_tiles": []
    }
    sync_all()

@socketio.on('move')
def on_move(data):
    global winner
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['injuries'] >= 5 or winner: return

    dx, dy = data['dx'], data['dy']
    nx, ny = p['x'] + dx, p['y'] + dy

    if 0 <= nx < 10 and 0 <= ny < 10:
        # בדיקת קירות
        if dx == 1 and maze[p['y']][nx]['walls']['left']: return
        if dx == -1 and maze[p['y']][p['x']]['walls']['left']: return
        if dy == 1 and maze[ny][p['x']]['walls']['top']: return
        if dy == -1 and maze[p['y']][p['x']]['walls']['top']: return

        p['x'], p['y'] = nx, ny
        tile = maze[ny][nx]['tile']

        # לוגיקת משבצות
        if tile == "river":
            if "boat" in p['items']:
                add_log(f"🛶 {p['n']} חצה את הנהר בבטחה עם סירה.")
            elif "raft" in p['items']:
                p['x'], p['y'] = river_start_pos
                add_log(f"🌊 הרפסודה הגנה על {p['n']} מפציעה, אך הוא נסחף להתחלה!")
            else:
                p['x'], p['y'] = river_start_pos
                p['injuries'] += 1
                add_log(f"🌊 {p['n']} נסחף בנהר ונפצע! (+1 פציעה)")

        elif tile == "devil":
            p['injuries'] += 1
            p['bul'] = max(0, p['bul'] - 1)
            p['bom'] = max(0, p['bom'] - 1)
            add_log(f"😈 {p['n']} פגש את השטן! -1 כדור, -1 פצצה, +1 פציעה.")

        elif tile == "monster":
            p['bul'] = min(5, p['bul'] + 1)
            p['bom'] = min(5, p['bom'] + 1)
            add_log(f"👾 {p['n']} פגש מפלצת וקיבל ציוד ותור נוסף!")
            # בגלל שהמשחק מבוסס אירועים, "תור נוסף" אומר שהוא פשוט לא מוגבל ויכול לזוז שוב.

        elif tile == "black_hole":
            p['x'], p['y'] = random.randint(0,9), random.randint(0,9)
            add_log(f"🕳️ {p['n']} נפל לחור שחור והשתגר למקום אקראי!")

        elif tile == "clinc" and p['injuries'] < 4:
            p['injuries'] = 0
            add_log(f"🏥 {p['n']} התרפא במרפאה.")

        elif tile == "er" and p['injuries'] == 4:
            p['injuries'] = 3
            add_log(f"🚑 {p['n']} ניצל במיון (פציעות ירדו ל-3).")

        elif tile == "exit" and "treasure" in p['items']:
            winner = p['n']
            add_log(f"🏆 {p['n']} יצא מהמבוך עם האוצר וניצח!")

        elif tile in ["treasure", "fake_treasure", "boat", "raft", "flashlight", "batteries"]:
            p['items'].append(tile)
            maze[ny][nx]['tile'] = "empty"
            item_name = tile.replace('_', ' ')
            add_log(f"🎒 {p['n']} מצא {item_name}!")

        # עדכון משבצות ידועות
        if [p['x'], p['y']] not in p['known_tiles']: p['known_tiles'].append([p['x'], p['y']])
        
    sync_all()

@socketio.on('update_maze')
def update_maze(data):
    global maze, river_start_pos
    maze = data
    for y in range(10):
        for x in range(10):
            if maze[y][x]['tile'] == "river_start": river_start_pos = (x,y)
    sync_all()

@socketio.on('set_phase')
def set_phase(p):
    global game_phase
    game_phase = p
    sync_all()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port)
