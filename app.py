import os, json
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'maze_secret_123'
# Optimized for Render: Long timeouts to prevent disconnect freezes
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60, ping_interval=25)

# Game State
maze = [[{"tile": "empty", "walls": {"top": False, "left": False}} for _ in range(10)] for _ in range(10)]
players = {}
game_phase = 1 
game_logs = []
winner = None

def add_log(msg):
    # Adds a message to the top of the list
    game_logs.insert(0, msg)
    # Keep only the last 20 messages for performance
    if len(game_logs) > 20:
        game_logs.pop()

def sync_all():
    p_list = [p for p in players.values() if not p['is_man']]
    alive = [p for p in p_list if p['injuries'] < 5]
    
    global winner
    if len(alive) == 1 and len(p_list) > 1 and not winner:
        winner = alive[0]['n']
        add_log(f"🏆 {winner} הוא השורד האחרון!")

    socketio.emit('sync', {
        "maze": maze,
        "players": [{"n":pl['n'], "x":pl['x'], "y":pl['y'], "injuries":pl['injuries'], "dead":pl['injuries']>=5} for pl in players.values()],
        "phase": game_phase,
        "logs": game_logs,
        "winner": winner
    })

@app.route('/')
def index(): return render_template('index.html')

@app.route('/manager')
def manager(): return render_template('manager.html')

@socketio.on('join')
def on_join(data):
    name = data.get('name', 'Player')
    players[request.sid] = {
        "n": name, "x": 0, "y": 0, "has_spawned": False, 
        "injuries": 0, "bul": 3, "bom": 3, "items": [], 
        "is_man": (name == "MANAGER"), "known_tiles": [], "is_lost": False
    }
    add_log(f"📢 {name} הצטרף למשחק")
    sync_all()

@socketio.on('set_phase')
def set_phase(data):
    global game_phase
    try:
        new_p = int(data['phase'])
        if new_p > game_phase:
            game_phase = new_p
            add_log(f"🚩 שלב המשחק השתנה ל-{game_phase}")
            sync_all()
    except: pass

@socketio.on('save_maze')
def save_maze(data):
    global maze
    if game_phase == 1:
        maze = data['maze']
        sync_all()

@socketio.on('action')
def handle_action(data):
    global winner
    p = players.get(request.sid)
    if not p or game_phase != 3 or p['injuries'] >= 5 or p['is_man'] or winner: return
    
    act, dx, dy = data.get('type'), data.get('dx', 0), data.get('dy', 0)

    # --- SHOOTING ---
    if act == 'shoot' and p['bul'] > 0:
        p['bul'] -= 1
        tx, ty = p['x'], p['y']
        hit_name = None
        while 0 <= tx <= 9 and 0 <= ty <= 9:
            if dy == -1 and maze[ty][tx]['walls']['top']: break
            if dy == 1 and ty < 9 and maze[ty+1][tx]['walls']['top']: break
            if dx == -1 and maze[ty][tx]['walls']['left']: break
            if dx == 1 and tx < 9 and maze[ty][tx+1]['walls']['left']: break
            tx += dx; ty += dy
            target = next((pl for pl in players.values() if pl['x']==tx and pl['y']==ty and not pl['is_man']), None)
            if target: 
                target['injuries'] += 1
                hit_name = target['n']
                add_log(f"💥 {p['n']} ירה ופגע ב-{hit_name}!")
                if target['injuries'] >= 5: add_log(f"💀 {hit_name} הודח מהמשחק!")
                break
        if not hit_name: add_log(f"🔫 {p['n']} ירה והחטיא")

    # --- BOMB ---
    elif act == 'bomb' and p['bom'] > 0:
        p['bom'] -= 1
        wall_hit = False
        if dy == -1 and maze[p['y']][p['x']]['walls']['top']:
            maze[p['y']][p['x']]['walls']['top'] = False
            wall_hit = True
        elif dy == 1 and p['y'] < 9 and maze[p['y']+1][p['x']]['walls']['top']:
            maze[p['y']+1][p['x']]['walls']['top'] = False
            wall_hit = True
        elif dx == -1 and maze[p['y']][p['x']]['walls']['left']:
            maze[p['y']][p['x']]['walls']['left'] = False
            wall_hit = True
        elif dx == 1 and p['x'] < 9 and maze[p['y']][p['x']+1]['walls']['left']:
            maze[p['y']][p['x']+1]['walls']['left'] = False
            wall_hit = True
        
        if wall_hit: add_log(f"💣 {p['n']} פוצץ קיר!")
        else: add_log(f"🧨 {p['n']} הניח פצצה אך אין שם קיר")

    # --- MOVE ---
    elif act == 'move':
        blocked = (dy == -1 and maze[p['y']][p['x']]['walls']['top']) or \
                  (dy == 1 and p['y'] < 9 and maze[p['y']+1][p['x']]['walls']['top']) or \
                  (dx == -1 and maze[p['y']][p['x']]['walls']['left']) or \
                  (dx == 1 and p['x'] < 9 and maze[p['y']][p['x']+1]['walls']['left'])
        
        if not blocked:
            p['x'] += dx; p['y'] += dy
            tile = maze[p['y']][p['x']]['tile']
            
            if tile == "monster": 
                p['bul']+=1; p['bom']+=1
                add_log(f"👾 {p['n']} מצא מפלצת וקיבל ציוד!")
                sync_all(); return 
            elif tile == "devil": 
                p['injuries']+=1; p['bul']=max(0,p['bul']-1); p['bom']=max(0,p['bom']-1)
                add_log(f"😈 {p['n']} פגש את השטן ואיבד ציוד!")
            elif tile == "clinc" and p['injuries'] <= 3: 
                p['injuries'] = max(0, p['injuries']-1)
                add_log(f"🏥 {p['n']} החלים במרפאה")
            elif tile == "er" and p['injuries'] == 4: 
                p['injuries'] = 3
                add_log(f"🚑 {p['n']} ניצל בחדר מיון!")
            elif tile in ["tresure", "fake_tresure", "flashlight", "battaries", "boat", "raft"]:
                p['items'].append(tile)
                maze[p['y']][p['x']]['tile'] = "empty"
                add_log(f"📦 {p['n']} מצא {tile}!")
            elif tile == "exit" and "tresure" in p['items']: 
                winner = p['n']
                add_log(f"🎉 {winner} הגיע ליציאה עם האוצר וניצח!")
            
            if [p['x'], p['y']] not in p['known_tiles']: p['known_tiles'].append([p['x'], p['y']])
    sync_all()

@socketio.on('set_spawn')
def set_spawn(d):
    p = players.get(request.sid)
    if p and game_phase == 2:
        p['x'], p['y'] = d['x'], d['y']
        p['has_spawned'] = True
        p['known_tiles'] = [[d['x'], d['y']]]
        add_log(f"📍 {p['n']} בחר מיקום התחלה")
        sync_all()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)
