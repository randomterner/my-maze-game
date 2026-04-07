from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random
import copy

app = Flask(__name__)
app.config["SECRET_KEY"] = "maze-secret-key"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

BOARD_SIZE = 10

TILE_TYPES = {
    "empty",
    "treasure",
    "fake_treasure",
    "exit",
    "river",
    "river_start",
    "boat",
    "raft",
    "clinic",
    "er",
    "monster",
    "devil",
    "black_hole",
    "flashlight",
    "batteries",
    "armory",
}

PICKUP_TILES = {
    "treasure",
    "fake_treasure",
    "boat",
    "raft",
    "flashlight",
    "batteries",
}

DIRECTIONS = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}

MANAGER_SID = None


def new_game_state():
    return {
        "board": {(x, y): "empty" for y in range(BOARD_SIZE) for x in range(BOARD_SIZE)},
        "consumed_tiles": set(),
        "inner_walls": set(),
        "players": {},
        "player_order": [],
        "current_turn_index": 0,
        "game_started": False,
        "game_over": False,
        "winner_sid": None,
        "winner_reason": "",
        "turn_number": 1,
        "logs": [],
        "pending_black_hole": None,
    }


GAME = new_game_state()


def log(message: str):
    GAME["logs"].append(message)
    if len(GAME["logs"]) > 400:
        GAME["logs"] = GAME["logs"][-400:]


def in_bounds(x, y):
    return 0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE


def is_edge_tile(x, y):
    return x == 0 or y == 0 or x == BOARD_SIZE - 1 or y == BOARD_SIZE - 1


def edge_key(a, b):
    return tuple(sorted([a, b]))


def serialize_edge(a, b):
    e = edge_key(a, b)
    return [list(e[0]), list(e[1])]


def remember_open_edge(player, a, b):
    edge = serialize_edge(a, b)
    if edge not in player["known_open_edges"]:
        player["known_open_edges"].append(edge)


def remember_broken_wall(player, a, b):
    edge = serialize_edge(a, b)
    if edge not in player["known_broken_walls"]:
        player["known_broken_walls"].append(edge)


def remember_wall_edge(player, a, b):
    edge = serialize_edge(a, b)
    if edge not in player["known_wall_edges"]:
        player["known_wall_edges"].append(edge)


def remember_visited_tile(player, pos):
    key = f"{pos[0]},{pos[1]}"
    if key not in player["visited_tiles"]:
        player["visited_tiles"].append(key)


def merge_map_knowledge(receiver, donor):
    for key, value in donor["known_tiles"].items():
        if key not in receiver["known_tiles"]:
            receiver["known_tiles"][key] = value

    for edge in donor["known_open_edges"]:
        if edge not in receiver["known_open_edges"]:
            receiver["known_open_edges"].append(copy.deepcopy(edge))

    for edge in donor["known_broken_walls"]:
        if edge not in receiver["known_broken_walls"]:
            receiver["known_broken_walls"].append(copy.deepcopy(edge))

    for edge in donor["known_wall_edges"]:
        if edge not in receiver["known_wall_edges"]:
            receiver["known_wall_edges"].append(copy.deepcopy(edge))


def is_birth_spot(pos):
    for p in GAME["players"].values():
        if p["birth_x"] == pos[0] and p["birth_y"] == pos[1]:
            return True
    return False


def tile_allows_map_fusion(pos):
    tile = GAME["board"].get(pos, "empty")
    return tile not in {"empty", "river"}


def set_relative_player_visibility(p1, p2):
    if p1["x"] is None or p1["y"] is None or p2["x"] is None or p2["y"] is None:
        return

    key2 = f"{p2['x']},{p2['y']}"
    p1["known_players"].setdefault(key2, [])
    if not any(pp["sid"] == p2["sid"] for pp in p1["known_players"][key2]):
        p1["known_players"][key2].append({
            "sid": p2["sid"],
            "name": p2["name"],
            "x": p2["x"],
            "y": p2["y"],
        })


def clear_relative_player_visibility(player):
    player["known_players"] = {}


def refresh_known_player_positions():
    for viewer in GAME["players"].values():
        updated = {}

        tracked_sids = set()
        for arr in viewer["known_players"].values():
            for pp in arr:
                tracked_sids.add(pp["sid"])

        for other in GAME["players"].values():
            if other["sid"] == viewer["sid"]:
                continue
            if other["sid"] not in tracked_sids:
                continue
            if other["x"] is None or other["y"] is None or not other["alive"]:
                continue

            key = f"{other['x']},{other['y']}"
            updated.setdefault(key, [])
            updated[key].append({
                "sid": other["sid"],
                "name": other["name"],
                "x": other["x"],
                "y": other["y"],
            })

        viewer["known_players"] = updated


def activate_map_fusion(player):
    if not GAME["game_started"]:
        return

    if player["x"] is None or player["y"] is None:
        return

    current_pos = (player["x"], player["y"])
    current_key = f"{player['x']},{player['y']}"

    if not tile_allows_map_fusion(current_pos) and not is_birth_spot(current_pos):
        return

    same_tile_players = []
    for other in GAME["players"].values():
        if other["sid"] == player["sid"]:
            continue
        if other["x"] is None or other["y"] is None:
            continue
        if other["alive"] and other["x"] == player["x"] and other["y"] == player["y"]:
            same_tile_players.append(other)

    if same_tile_players:
        involved = [player] + same_tile_players

        for a in involved:
            for b in involved:
                if a["sid"] == b["sid"]:
                    continue
                merge_map_knowledge(a, b)
                set_relative_player_visibility(a, b)

        for p in involved:
            p["lost"] = False
            reveal_current_position(p)

        other_names = ", ".join([p["name"] for p in same_tile_players])
        set_player_message(player, f"You met {other_names} → MAP FUSION!")
        for other in same_tile_players:
            set_player_message(other, f"You met {player['name']} → MAP FUSION!")

        if len(involved) == 2:
            log(f"{player['name']} met {same_tile_players[0]['name']} → MAP FUSION")
        else:
            log("MAP FUSION happened between players on the same tile.")
        return

    for other in GAME["players"].values():
        if other["sid"] == player["sid"]:
            continue
        if other["x"] is None or other["y"] is None:
            continue

        if current_key in other["visited_tiles"]:
            merge_map_knowledge(player, other)
            set_relative_player_visibility(player, other)
            player["lost"] = False
            reveal_current_position(player)
            set_player_message(player, f"You found traces of {other['name']} → MAP FUSION")
            return


def check_birth_spot_discovery(player):
    if player["x"] is None or player["y"] is None:
        return

    if (
        player["birth_x"] is not None
        and player["birth_y"] is not None
        and player["x"] == player["birth_x"]
        and player["y"] == player["birth_y"]
    ):
        if player["lost"]:
            player["lost"] = False
            reveal_current_position(player)
            set_player_message(player, "You found your birth spot and are no longer lost.")
            log(f"{player['name']} found their birth spot and is no longer lost.")
            return

    for other in GAME["players"].values():
        if other["sid"] == player["sid"]:
            continue
        if other["birth_x"] is None or other["birth_y"] is None:
            continue

        if player["x"] == other["birth_x"] and player["y"] == other["birth_y"]:
            set_player_message(player, f"You found {other['name']}'s birth spot.")
            log(f"{player['name']} found {other['name']}'s birth spot")
            return


def is_outer_wall(x, y, direction):
    if direction == "up":
        return y == 0
    if direction == "down":
        return y == BOARD_SIZE - 1
    if direction == "left":
        return x == 0
    if direction == "right":
        return x == BOARD_SIZE - 1
    return False


def has_inner_wall_between(a, b):
    return edge_key(a, b) in GAME["inner_walls"]


def wall_blocks(x, y, direction):
    if is_outer_wall(x, y, direction):
        return True
    dx, dy = DIRECTIONS[direction]
    nx, ny = x + dx, y + dy
    if not in_bounds(nx, ny):
        return True
    return has_inner_wall_between((x, y), (nx, ny))


def alive_players():
    return [p for p in GAME["players"].values() if p["alive"]]


def alive_player_sids_in_order():
    return [sid for sid in GAME["player_order"] if sid in GAME["players"] and GAME["players"][sid]["alive"]]


def current_turn_sid():
    order = alive_player_sids_in_order()
    if not order:
        return None
    if GAME["current_turn_index"] >= len(order):
        GAME["current_turn_index"] = 0
    return order[GAME["current_turn_index"]]


def current_player():
    sid = current_turn_sid()
    if sid is None:
        return None
    return GAME["players"][sid]


def all_spawned():
    if len(GAME["players"]) < 2:
        return False
    return all(p["spawned"] for p in GAME["players"].values())


def create_player(sid, name):
    return {
        "sid": sid,
        "name": name,
        "x": None,
        "y": None,
        "birth_x": None,
        "birth_y": None,
        "alive": True,
        "spawned": False,
        "injuries": 0,
        "bullets": 3,
        "bombs": 3,
        "items": {
            "treasure": False,
            "fake_treasure": False,
            "boat": False,
            "raft": False,
            "flashlight": False,
            "batteries": False,
        },
        "known_tiles": {},
        "known_players": {},
        "known_open_edges": [],
        "known_broken_walls": [],
        "known_wall_edges": [],
        "visited_tiles": [],
        "last_message": "Choose a spawn tile by tapping the board.",
        "extra_turn": False,
        "lost": False,
    }


def set_player_message(player, message):
    player["last_message"] = message


def effective_tile_at(pos):
    base = GAME["board"].get(pos, "empty")
    if pos in GAME["consumed_tiles"] and base in PICKUP_TILES:
        return f"used_{base}"
    return base


def add_known_tile(player, pos):
    if not in_bounds(pos[0], pos[1]):
        return
    player["known_tiles"][f"{pos[0]},{pos[1]}"] = effective_tile_at(pos)


def update_known_players_for_viewer(viewer):
    if not GAME["game_started"]:
        viewer["known_players"] = {}
        return

    preserved_sids = set()
    for arr in viewer["known_players"].values():
        for pp in arr:
            preserved_sids.add(pp["sid"])

    new_map = {}
    for other in GAME["players"].values():
        if not other["alive"] or other["x"] is None or other["y"] is None:
            continue
        if other["sid"] not in preserved_sids:
            continue
        if viewer["lost"] and other["sid"] == viewer["sid"]:
            continue

        key = f"{other['x']},{other['y']}"
        new_map.setdefault(key, [])
        new_map[key].append({
            "sid": other["sid"],
            "name": other["name"],
            "x": other["x"],
            "y": other["y"],
        })

    viewer["known_players"] = new_map


def reveal_position(player, pos):
    if player["lost"]:
        return
    add_known_tile(player, pos)
    remember_visited_tile(player, pos)
    update_known_players_for_viewer(player)


def reveal_current_position(player):
    if player["x"] is None or player["y"] is None:
        return
    reveal_position(player, (player["x"], player["y"]))


def check_death(player, reason=""):
    if player["alive"] and player["injuries"] >= 5:
        player["alive"] = False
        set_player_message(player, "You died.")
        if reason:
            log(f"{player['name']} died. {reason}")
        else:
            log(f"{player['name']} died.")
        check_last_player_win()
        return True
    return False


def check_last_player_win():
    if GAME["game_over"]:
        return
    alive = alive_players()
    if len(alive) == 1 and len(GAME["players"]) >= 2:
        winner = alive[0]
        GAME["game_over"] = True
        GAME["winner_sid"] = winner["sid"]
        GAME["winner_reason"] = "last_player_alive"
        log(f"{winner['name']} wins as the last player alive.")


def end_turn():
    if GAME["game_over"]:
        emit_full_state()
        return

    player = current_player()
    if player and player["alive"] and player["extra_turn"]:
        player["extra_turn"] = False
        GAME["turn_number"] += 1
        log(f"{player['name']} gets an extra turn.")
        emit_full_state()
        return

    order = alive_player_sids_in_order()
    if not order:
        emit_full_state()
        return

    GAME["current_turn_index"] += 1
    if GAME["current_turn_index"] >= len(order):
        GAME["current_turn_index"] = 0

    GAME["turn_number"] += 1
    emit_full_state()


def reset_game():
    global GAME
    old_players = GAME["players"]
    new_state = new_game_state()
    for sid, old_player in old_players.items():
        new_state["players"][sid] = create_player(sid, old_player["name"])
    GAME = new_state
    log("Game reset. Connected players were kept.")
    emit_full_state()


def find_river_start():
    starts = [pos for pos, tile in GAME["board"].items() if tile == "river_start"]
    if not starts:
        return None
    return starts[0]


def get_river_positions():
    return {pos for pos, tile in GAME["board"].items() if tile in {"river", "river_start"}}


def river_validation():
    river_positions = get_river_positions()

    if not river_positions:
        return {"ok": True, "message": "No river on board."}

    if len(river_positions) > 20:
        return {"ok": False, "message": "River may use at most 20 tiles including river_start."}

    river_starts = [pos for pos, tile in GAME["board"].items() if tile == "river_start"]
    if len(river_starts) != 1:
        return {"ok": False, "message": "River must contain exactly one river_start tile."}

    river_start = river_starts[0]

    orth_neighbors = {}
    for (x, y) in river_positions:
        neighbors = []
        for dx, dy in DIRECTIONS.values():
            nxt = (x + dx, y + dy)
            if nxt in river_positions:
                if not has_inner_wall_between((x, y), nxt):
                    neighbors.append(nxt)
        orth_neighbors[(x, y)] = neighbors

    for pos, neighbors in orth_neighbors.items():
        if len(neighbors) > 2:
            return {"ok": False, "message": "River cannot split at any point."}

    if len(river_positions) == 1:
        if len(orth_neighbors[river_start]) != 0:
            return {"ok": False, "message": "Single-tile river_start cannot connect to other river tiles."}
    else:
        if len(orth_neighbors[river_start]) != 1:
            return {"ok": False, "message": "river_start must connect to exactly one river tile."}

    stack = [river_start]
    seen = set()

    while stack:
        pos = stack.pop()
        if pos in seen:
            continue
        seen.add(pos)
        for nxt in orth_neighbors[pos]:
            if nxt not in seen:
                stack.append(nxt)

    if seen == river_positions:
        return {"ok": True, "message": "River is valid."}

    for (x, y) in river_positions:
        diagonal_neighbors = [
            (x - 1, y - 1), (x + 1, y - 1),
            (x - 1, y + 1), (x + 1, y + 1),
        ]
        for pos in diagonal_neighbors:
            if pos in river_positions:
                return {"ok": False, "message": "River tiles cannot connect diagonally."}

    return {"ok": False, "message": "All river tiles must be connected."}


def handle_pickup(player, pos, tile):
    if pos in GAME["consumed_tiles"]:
        if tile == "treasure":
            return "There was a treasure here."
        if tile == "fake_treasure":
            return "There was a fake treasure here."
        if tile == "boat":
            return "There was a boat here."
        if tile == "raft":
            return "There was a raft here."
        if tile == "flashlight":
            return "There was a flashlight here."
        if tile == "batteries":
            return "There were batteries here."
        return "This item was already taken."

    if tile == "treasure":
        player["items"]["treasure"] = True
        GAME["consumed_tiles"].add(pos)
        log(f"{player['name']} found the real treasure.")
        return "You found the real treasure!"

    if tile == "fake_treasure":
        player["items"]["fake_treasure"] = True
        GAME["consumed_tiles"].add(pos)
        return "You found a fake treasure."

    if tile == "boat":
        player["items"]["boat"] = True
        GAME["consumed_tiles"].add(pos)
        return "You picked up a boat."

    if tile == "raft":
        player["items"]["raft"] = True
        GAME["consumed_tiles"].add(pos)
        return "You picked up a raft."

    if tile == "flashlight":
        player["items"]["flashlight"] = True
        GAME["consumed_tiles"].add(pos)
        return "You picked up a flashlight."

    if tile == "batteries":
        player["items"]["batteries"] = True
        GAME["consumed_tiles"].add(pos)
        return "You picked up batteries."

    return ""


def apply_tile_effect(player):
    pos = (player["x"], player["y"])
    raw_tile = GAME["board"][pos]

    if not player["lost"]:
        reveal_current_position(player)

    if raw_tile in PICKUP_TILES:
        set_player_message(player, handle_pickup(player, pos, raw_tile))
        return "continue"

    if raw_tile == "empty":
        set_player_message(player, "Empty tile.")
        return "continue"

    if raw_tile == "exit":
        if player["items"]["treasure"]:
            GAME["game_over"] = True
            GAME["winner_sid"] = player["sid"]
            GAME["winner_reason"] = "treasure_exit"
            set_player_message(player, "You escaped with the real treasure and won!")
            log(f"{player['name']} escaped through the exit with the real treasure.")
            return "game_over"
        set_player_message(player, "You found the exit, but you do not have the real treasure.")
        return "continue"

    if raw_tile == "clinic":
        if player["injuries"] >= 3:
            player["injuries"] = 0
            set_player_message(player, "Clinic healed you to 0 injuries.")
        else:
            set_player_message(player, "Clinic did nothing.")
        return "continue"

    if raw_tile == "er":
        if player["injuries"] == 4:
            player["injuries"] = 3
            set_player_message(player, "ER reduced your injuries from 4 to 3.")
        else:
            set_player_message(player, "ER did nothing.")
        return "continue"

    if raw_tile == "monster":
        old_bullets = player["bullets"]
        old_bombs = player["bombs"]
        player["bullets"] = min(5, player["bullets"] + 1)
        player["bombs"] = min(5, player["bombs"] + 1)
        player["extra_turn"] = True
        set_player_message(
            player,
            f"Monster: bullets {old_bullets}->{player['bullets']}, bombs {old_bombs}->{player['bombs']}. Extra turn granted."
        )
        return "continue"

    if raw_tile == "devil":
        player["injuries"] += 1
        player["bullets"] = max(0, player["bullets"] - 1)
        player["bombs"] = max(0, player["bombs"] - 1)
        if check_death(player, "Killed by devil tile."):
            return "dead"
        set_player_message(player, "Devil: +1 injury, -1 bullet, -1 bomb.")
        return "continue"

    if raw_tile == "black_hole":
        GAME["pending_black_hole"] = {"player_sid": player["sid"]}
        set_player_message(player, "Black hole! Waiting for manager placement.")
        log(f"{player['name']} entered a black hole.")
        return "pending_black_hole"

    if raw_tile == "armory":
        old_bullets = player["bullets"]
        old_bombs = player["bombs"]
        player["bullets"] = max(player["bullets"], 3)
        player["bombs"] = max(player["bombs"], 3)
        set_player_message(
            player,
            f"Armory: bullets {old_bullets}->{player['bullets']}, bombs {old_bombs}->{player['bombs']}."
        )
        return "continue"

    if raw_tile == "river_start":
        set_player_message(player, "River start.")
        return "continue"

    if raw_tile == "river":
        river_start = find_river_start()

        if player["items"]["boat"]:
            set_player_message(player, "You crossed the river safely with the boat.")
            return "continue"

        if player["items"]["raft"]:
            if river_start is not None:
                if not player["lost"]:
                    remember_open_edge(player, pos, river_start)
                player["x"], player["y"] = river_start
                if not player["lost"]:
                    reveal_current_position(player)
            set_player_message(player, "You used the raft. No injury, but you drifted to the river start.")
            return "continue"

        player["injuries"] += 1
        if check_death(player, "Killed by river injury."):
            return "dead"

        if river_start is not None:
            if not player["lost"]:
                remember_open_edge(player, pos, river_start)
            player["x"], player["y"] = river_start
            if not player["lost"]:
                reveal_current_position(player)

        set_player_message(player, "The river injured you and dragged you to the river start.")
        return "continue"

    set_player_message(player, f"You stepped on: {raw_tile}")
    return "continue"


def reveal_line(player, direction):
    if player["lost"]:
        return []

    dx, dy = DIRECTIONS[direction]
    x, y = player["x"], player["y"]
    revealed = []
    prev = (x, y)

    while True:
        if wall_blocks(x, y, direction):
            if not is_outer_wall(x, y, direction):
                nx, ny = x + dx, y + dy
                if in_bounds(nx, ny):
                    remember_wall_edge(player, (x, y), (nx, ny))
            break

        x += dx
        y += dy
        if not in_bounds(x, y):
            break

        current = (x, y)
        remember_open_edge(player, prev, current)
        reveal_position(player, current)
        revealed.append(current)
        prev = current

    return revealed


def validate_turn_action():
    if not GAME["game_started"]:
        return False, "Game has not started."
    if GAME["game_over"]:
        return False, "Game is over."
    if request.sid not in GAME["players"]:
        return False, "Player not found."

    player = GAME["players"][request.sid]
    if not player["alive"]:
        return False, "You are dead."
    if current_turn_sid() != request.sid:
        return False, "It is not your turn."
    if GAME["pending_black_hole"] is not None:
        return False, "Waiting for manager to resolve a black hole."

    return True, ""


def serialize_player_public(player):
    return {
        "sid": player["sid"],
        "name": player["name"],
        "x": player["x"],
        "y": player["y"],
        "birth_x": player["birth_x"],
        "birth_y": player["birth_y"],
        "alive": player["alive"],
        "spawned": player["spawned"],
        "injuries": player["injuries"],
        "bullets": player["bullets"],
        "bombs": player["bombs"],
        "items": copy.deepcopy(player["items"]),
        "known_open_edges": copy.deepcopy(player["known_open_edges"]),
        "known_broken_walls": copy.deepcopy(player["known_broken_walls"]),
        "known_wall_edges": copy.deepcopy(player["known_wall_edges"]),
        "last_message": player["last_message"],
        "lost": player["lost"],
    }


def serialize_manager_state():
    return {
        "board": {f"{x},{y}": effective_tile_at((x, y)) for (x, y) in GAME["board"].keys()},
        "raw_board": {f"{x},{y}": GAME["board"][(x, y)] for (x, y) in GAME["board"].keys()},
        "inner_walls": [[list(a), list(b)] for (a, b) in GAME["inner_walls"]],
        "players": [serialize_player_public(p) for p in GAME["players"].values()],
        "player_order": GAME["player_order"],
        "current_turn_sid": current_turn_sid(),
        "game_started": GAME["game_started"],
        "game_over": GAME["game_over"],
        "winner_sid": GAME["winner_sid"],
        "winner_reason": GAME["winner_reason"],
        "turn_number": GAME["turn_number"],
        "logs": GAME["logs"][-80:],
        "pending_black_hole": GAME["pending_black_hole"],
        "river_validation": river_validation(),
    }


def serialize_player_state_for(sid):
    player = GAME["players"].get(sid)
    if not player:
        return {}

    turn_sid = current_turn_sid()

    return {
        "you": serialize_player_public(player),
        "your_known_tiles": copy.deepcopy(player["known_tiles"]),
        "your_known_players": copy.deepcopy(player["known_players"]),
        "your_known_open_edges": copy.deepcopy(player["known_open_edges"]),
        "your_known_broken_walls": copy.deepcopy(player["known_broken_walls"]),
        "your_known_wall_edges": copy.deepcopy(player["known_wall_edges"]),
        "board_size": BOARD_SIZE,
        "current_turn_sid": turn_sid,
        "current_turn_name": GAME["players"][turn_sid]["name"] if turn_sid in GAME["players"] else None,
        "is_your_turn": turn_sid == sid,
        "game_started": GAME["game_started"],
        "game_over": GAME["game_over"],
        "winner_sid": GAME["winner_sid"],
        "winner_reason": GAME["winner_reason"],
        "turn_number": GAME["turn_number"],
        "logs": GAME["logs"][-30:],
        "pending_black_hole": GAME["pending_black_hole"],
    }


def emit_full_state():
    socketio.emit("manager_state", serialize_manager_state(), room="manager_room")
    for sid in list(GAME["players"].keys()):
        socketio.emit("player_state", serialize_player_state_for(sid), room=sid)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/manager")
def manager():
    return render_template("manager.html")


@socketio.on("connect")
def on_connect():
    emit("connected", {"sid": request.sid})


@socketio.on("disconnect")
def on_disconnect():
    global MANAGER_SID
    sid = request.sid

    if sid == MANAGER_SID:
        MANAGER_SID = None

    if sid in GAME["players"]:
        player_name = GAME["players"][sid]["name"]
        del GAME["players"][sid]
        GAME["player_order"] = [p_sid for p_sid in GAME["player_order"] if p_sid != sid]

        if GAME["pending_black_hole"] and GAME["pending_black_hole"]["player_sid"] == sid:
            GAME["pending_black_hole"] = None

        log(f"{player_name} disconnected.")
        check_last_player_win()

    emit_full_state()


@socketio.on("join_player")
def join_player(data):
    sid = request.sid
    name = (data.get("name") or "").strip()

    if not name:
        emit("error_message", {"message": "Name is required."})
        return

    if sid not in GAME["players"]:
        GAME["players"][sid] = create_player(sid, name)
        log(f"{name} joined the game.")
    else:
        GAME["players"][sid]["name"] = name

    socketio.server.enter_room(sid, sid)
    emit("joined_as_player", {"sid": sid, "name": name})
    emit_full_state()


@socketio.on("join_manager")
def join_manager():
    global MANAGER_SID
    MANAGER_SID = request.sid
    socketio.server.enter_room(request.sid, "manager_room")
    emit("joined_as_manager", {"sid": request.sid})
    emit_full_state()


@socketio.on("manager_set_tile")
def manager_set_tile(data):
    if request.sid != MANAGER_SID:
        emit("error_message", {"message": "Only the manager can edit the board."})
        return

    try:
        x = int(data["x"])
        y = int(data["y"])
        tile = data["tile"]
    except Exception:
        emit("error_message", {"message": "Invalid tile data."})
        return

    if not in_bounds(x, y):
        emit("error_message", {"message": "Tile out of bounds."})
        return

    if tile not in TILE_TYPES:
        emit("error_message", {"message": "Invalid tile type."})
        return

    if tile == "exit" and not is_edge_tile(x, y):
        emit("error_message", {"message": "Exit must be placed on an outer edge tile."})
        return

    GAME["board"][(x, y)] = tile
    GAME["consumed_tiles"].discard((x, y))
    emit_full_state()


@socketio.on("manager_toggle_inner_wall")
def manager_toggle_inner_wall(data):
    if request.sid != MANAGER_SID:
        emit("error_message", {"message": "Only the manager can edit walls."})
        return

    try:
        x = int(data["x"])
        y = int(data["y"])
        direction = data["direction"]
    except Exception:
        emit("error_message", {"message": "Invalid wall data."})
        return

    if direction not in DIRECTIONS:
        emit("error_message", {"message": "Invalid direction."})
        return

    if not in_bounds(x, y):
        emit("error_message", {"message": "Coordinates out of bounds."})
        return

    if is_outer_wall(x, y, direction):
        emit("error_message", {"message": "Outer walls cannot be edited."})
        return

    dx, dy = DIRECTIONS[direction]
    nx, ny = x + dx, y + dy
    if not in_bounds(nx, ny):
        emit("error_message", {"message": "Invalid inner wall edge."})
        return

    ek = edge_key((x, y), (nx, ny))
    if ek in GAME["inner_walls"]:
        GAME["inner_walls"].remove(ek)
    else:
        GAME["inner_walls"].add(ek)

    emit_full_state()


@socketio.on("manager_clear_board")
def manager_clear_board():
    if request.sid != MANAGER_SID:
        emit("error_message", {"message": "Only the manager can clear the board."})
        return

    for pos in GAME["board"]:
        GAME["board"][pos] = "empty"
    GAME["consumed_tiles"].clear()
    GAME["inner_walls"].clear()
    emit_full_state()


@socketio.on("manager_reset_game")
def manager_reset_game():
    if request.sid != MANAGER_SID:
        emit("error_message", {"message": "Only the manager can reset the game."})
        return
    reset_game()


@socketio.on("manager_start_game")
def manager_start_game():
    if request.sid != MANAGER_SID:
        emit("error_message", {"message": "Only the manager can start the game."})
        return

    if GAME["game_started"]:
        emit("error_message", {"message": "Game already started."})
        return

    if not all_spawned():
        emit("error_message", {"message": "Need at least 2 spawned players."})
        return

    GAME["player_order"] = list(GAME["players"].keys())
    random.shuffle(GAME["player_order"])
    GAME["current_turn_index"] = 0
    GAME["game_started"] = True
    GAME["game_over"] = False
    GAME["winner_sid"] = None
    GAME["winner_reason"] = ""
    GAME["turn_number"] = 1
    GAME["pending_black_hole"] = None

    for player in GAME["players"].values():
        player["lost"] = False
        reveal_current_position(player)
        start_tile = GAME["board"][(player["x"], player["y"])]
        if start_tile != "empty":
            result = apply_tile_effect(player)
            if result == "pending_black_hole":
                pass
            elif result == "game_over":
                emit_full_state()
                return
        else:
            set_player_message(player, f"Game started. You spawned on: {effective_tile_at((player['x'], player['y']))}")

    for player in GAME["players"].values():
        activate_map_fusion(player)
        check_birth_spot_discovery(player)

    refresh_known_player_positions()

    log("Game started.")
    turn_sid = current_turn_sid()
    if turn_sid in GAME["players"]:
        log(f"First turn: {GAME['players'][turn_sid]['name']}")

    emit_full_state()


@socketio.on("player_spawn")
def player_spawn(data):
    sid = request.sid
    if sid not in GAME["players"]:
        emit("error_message", {"message": "Join first."})
        return

    if GAME["game_started"]:
        emit("error_message", {"message": "Game already started."})
        return

    try:
        x = int(data["x"])
        y = int(data["y"])
    except Exception:
        emit("error_message", {"message": "Invalid spawn coordinates."})
        return

    if not in_bounds(x, y):
        emit("error_message", {"message": "Spawn out of bounds."})
        return

    player = GAME["players"][sid]
    player["x"] = x
    player["y"] = y
    player["birth_x"] = x
    player["birth_y"] = y
    player["spawned"] = True
    player["lost"] = False

    player["known_tiles"] = {}
    player["known_players"] = {}
    player["known_open_edges"] = []
    player["known_broken_walls"] = []
    player["known_wall_edges"] = []
    player["visited_tiles"] = [f"{x},{y}"]

    set_player_message(player, "Spawn selected. Your starting tile will be revealed when the game begins.")
    log(f"{player['name']} chose a spawn tile.")
    emit_full_state()


@socketio.on("player_move")
def player_move(data):
    ok, msg = validate_turn_action()
    if not ok:
        emit("error_message", {"message": msg})
        return

    direction = data.get("direction")
    if direction not in DIRECTIONS:
        emit("error_message", {"message": "Invalid direction."})
        return

    player = GAME["players"][request.sid]
    x, y = player["x"], player["y"]

    if wall_blocks(x, y, direction):
        if not player["lost"] and not is_outer_wall(x, y, direction):
            dx, dy = DIRECTIONS[direction]
            nx, ny = x + dx, y + dy
            if in_bounds(nx, ny):
                remember_wall_edge(player, (x, y), (nx, ny))
        set_player_message(player, "You hit a wall and stayed in place. Turn ended.")
        log(f"{player['name']} hit a wall while moving {direction}.")
        emit_full_state()
        end_turn()
        return

    dx, dy = DIRECTIONS[direction]
    new_pos = (x + dx, y + dy)

    if not player["lost"]:
        remember_open_edge(player, (x, y), new_pos)

    player["x"] = new_pos[0]
    player["y"] = new_pos[1]
    remember_visited_tile(player, new_pos)
    log(f"{player['name']} moved {direction}.")

    result = apply_tile_effect(player)

    if result == "game_over":
        emit_full_state()
        return

    if result == "pending_black_hole":
        emit_full_state()
        return

    if result == "dead":
        emit_full_state()
        end_turn()
        return

    activate_map_fusion(player)
    check_birth_spot_discovery(player)
    refresh_known_player_positions()

    emit_full_state()
    end_turn()


@socketio.on("player_shoot")
def player_shoot(data):
    ok, msg = validate_turn_action()
    if not ok:
        emit("error_message", {"message": msg})
        return

    direction = data.get("direction")
    if direction not in DIRECTIONS:
        emit("error_message", {"message": "Invalid direction."})
        return

    shooter = GAME["players"][request.sid]
    if shooter["bullets"] <= 0:
        emit("error_message", {"message": "You have no bullets."})
        return

    shooter["bullets"] -= 1

    x, y = shooter["x"], shooter["y"]
    dx, dy = DIRECTIONS[direction]
    hit_target = None

    while True:
        if wall_blocks(x, y, direction):
            if not shooter["lost"] and not is_outer_wall(x, y, direction):
                nx, ny = x + dx, y + dy
                if in_bounds(nx, ny):
                    remember_wall_edge(shooter, (x, y), (nx, ny))
            break

        x += dx
        y += dy
        if not in_bounds(x, y):
            break

        targets_here = []
        for other in GAME["players"].values():
            if not other["alive"]:
                continue
            if other["sid"] == shooter["sid"]:
                continue
            if other["x"] == x and other["y"] == y:
                targets_here.append(other)

        if targets_here:
            hit_target = random.choice(targets_here)
            break

    if hit_target is None:
        set_player_message(shooter, "Your bullet hit nothing.")
        log(f"{shooter['name']} shot {direction} and hit nothing.")
        emit_full_state()
        end_turn()
        return

    hit_target["injuries"] += 1
    set_player_message(shooter, f"You hit {hit_target['name']}.")
    set_player_message(hit_target, f"You were shot by {shooter['name']}.")
    log(f"{shooter['name']} shot {hit_target['name']}.")

    check_death(hit_target, "Killed by a bullet.")

    emit_full_state()
    end_turn()


@socketio.on("player_bomb")
def player_bomb(data):
    ok, msg = validate_turn_action()
    if not ok:
        emit("error_message", {"message": msg})
        return

    direction = data.get("direction")
    if direction not in DIRECTIONS:
        emit("error_message", {"message": "Invalid direction."})
        return

    player = GAME["players"][request.sid]
    if player["bombs"] <= 0:
        emit("error_message", {"message": "You have no bombs."})
        return

    player["bombs"] -= 1
    x, y = player["x"], player["y"]

    if is_outer_wall(x, y, direction):
        set_player_message(player, "The wall did not explode.")
        log(f"{player['name']} tried to bomb an outer wall.")
        emit_full_state()
        end_turn()
        return

    dx, dy = DIRECTIONS[direction]
    nx, ny = x + dx, y + dy
    ek = edge_key((x, y), (nx, ny))

    if ek in GAME["inner_walls"]:
        GAME["inner_walls"].remove(ek)
        if not player["lost"]:
            remember_broken_wall(player, (x, y), (nx, ny))
        set_player_message(player, "The wall exploded.")
        log(f"{player['name']} destroyed an inner wall.")
    else:
        set_player_message(player, "There was no wall there.")
        log(f"{player['name']} used a bomb, but there was no wall.")

    emit_full_state()
    end_turn()


@socketio.on("player_flashlight")
def player_flashlight(data):
    ok, msg = validate_turn_action()
    if not ok:
        emit("error_message", {"message": msg})
        return

    direction = data.get("direction")
    if direction not in DIRECTIONS:
        emit("error_message", {"message": "Invalid direction."})
        return

    player = GAME["players"][request.sid]
    if not (player["items"]["flashlight"] and player["items"]["batteries"]):
        emit("error_message", {"message": "You need both flashlight and batteries."})
        return

    revealed = reveal_line(player, direction)
    if revealed:
        set_player_message(player, f"Flashlight revealed {len(revealed)} tile(s) {direction}.")
    else:
        set_player_message(player, "Flashlight revealed nothing.")

    log(f"{player['name']} used flashlight {direction}.")
    emit_full_state()
    end_turn()


@socketio.on("manager_resolve_black_hole")
def manager_resolve_black_hole(data):
    if request.sid != MANAGER_SID:
        emit("error_message", {"message": "Only the manager can resolve black hole placement."})
        return

    if GAME["pending_black_hole"] is None:
        emit("error_message", {"message": "No pending black hole."})
        return

    try:
        x = int(data["x"])
        y = int(data["y"])
    except Exception:
        emit("error_message", {"message": "Invalid coordinates."})
        return

    if not in_bounds(x, y):
        emit("error_message", {"message": "Coordinates out of bounds."})
        return

    if GAME["board"][(x, y)] != "empty":
        emit("error_message", {"message": "Black hole destination must be an empty tile."})
        return

    player_sid = GAME["pending_black_hole"]["player_sid"]
    if player_sid not in GAME["players"]:
        GAME["pending_black_hole"] = None
        emit_full_state()
        return

    player = GAME["players"][player_sid]
    clear_relative_player_visibility(player)
    player["lost"] = True
    player["x"] = x
    player["y"] = y
    remember_visited_tile(player, (x, y))

    activate_map_fusion(player)
    check_birth_spot_discovery(player)
    refresh_known_player_positions()

    if (
        "MAP FUSION" not in player["last_message"]
        and "birth spot" not in player["last_message"]
        and "no longer lost" not in player["last_message"]
    ):
        set_player_message(player, "You are lost after the black hole.")

    log(f"Manager placed {player['name']} after black hole.")
    GAME["pending_black_hole"] = None
    emit_full_state()
    end_turn()


if __name__ == "__main__":
    log("Server started.")
    socketio.run(app, host="0.0.0.0", port=10000)
