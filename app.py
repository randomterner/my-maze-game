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

# All of these tiles are required exactly once before a game can begin.
# Empty tiles and the river are the only repeatable board tiles.  A river_start
# is part of the river, but has its own one-start rule in river_validation().
REQUIRED_SINGLE_TILES = TILE_TYPES - {"empty", "river", "river_start"}

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
DEFAULT_PLAYER_COLOR = "#55e4ff"


def normalize_player_color(value):
    if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
        hex_digits = value[1:]
        if all(char in "0123456789abcdefABCDEF" for char in hex_digits):
            return f"#{hex_digits.lower()}"
    return DEFAULT_PLAYER_COLOR


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
        "river_lost_map": {
            "tiles": {},
            "open_edges": [],
            "broken_walls": [],
            "wall_edges": [],
        },
        "public_revealed_positions": {},
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


def lost_relative_position_for(player, actual_pos):
    """Convert a server-only board position into the lost map's coordinates."""
    return (
        player["lost_relative_x"] + actual_pos[0] - player["x"],
        player["lost_relative_y"] + actual_pos[1] - player["y"],
    )


def remember_lost_edge(player, field, actual_a, actual_b):
    relative_a = lost_relative_position_for(player, actual_a)
    relative_b = lost_relative_position_for(player, actual_b)
    edge = serialize_edge(relative_a, relative_b)
    if edge not in player[field]:
        player[field].append(edge)
    if player.get("lost_kind") == "river":
        river_field = {
            "lost_known_open_edges": "open_edges",
            "lost_known_broken_walls": "broken_walls",
            "lost_known_wall_edges": "wall_edges",
        }.get(field)
        if river_field and edge not in GAME["river_lost_map"][river_field]:
            GAME["river_lost_map"][river_field].append(copy.deepcopy(edge))


def remember_lost_outer_wall_bomb(player, direction):
    """Record a bomb-confirmed outer edge without exposing normal coordinates."""
    x, y = player["x"], player["y"]
    dx, dy = DIRECTIONS[direction]
    remember_lost_edge(player, "lost_known_wall_edges", (x, y), (x + dx, y + dy))

    relative_key = f"{player['lost_relative_x']},{player['lost_relative_y']}"
    clues = player["lost_outer_wall_bomb_clues"].setdefault(relative_key, [])
    if direction not in clues:
        clues.append(direction)


def lost_outer_wall_axes(player):
    """Return which absolute axes the player has anchored with bomb attempts."""
    directions = {
        direction
        for clues in player.get("lost_outer_wall_bomb_clues", {}).values()
        for direction in clues
    }
    return {
        "x": bool(directions & {"left", "right"}),
        "y": bool(directions & {"up", "down"}),
    }


def lost_map_completion_message(player, known_x, known_y):
    """Apply the 10x10 escape rule, including information from outer-wall bombs."""
    has_all_columns = len(known_x) >= BOARD_SIZE
    has_all_rows = len(known_y) >= BOARD_SIZE
    axes = lost_outer_wall_axes(player)

    if has_all_columns and has_all_rows:
        return "You mapped all 10 relative rows and columns and are no longer lost."
    if axes["x"] and axes["y"]:
        return "Outer-wall bomb hits fixed both map axes, so you are no longer lost."
    if axes["y"] and has_all_columns:
        return "A north/south outer edge and 10 mapped columns revealed your position. You are no longer lost."
    if axes["x"] and has_all_rows:
        return "An east/west outer edge and 10 mapped rows revealed your position. You are no longer lost."
    return None


def reveal_players_at_lost_special_tile(player, pos):
    """Show players who previously found this special tile, in relative space."""
    tile_key = f"{pos[0]},{pos[1]}"
    for other in GAME["players"].values():
        if (
            other["sid"] == player["sid"]
            or not other["alive"]
            or other["lost"]
            or other["x"] is None
            or other["y"] is None
            or tile_key not in other["visited_tiles"]
        ):
            continue

        relative_other = lost_relative_position_for(player, (other["x"], other["y"]))
        relative_key = f"{relative_other[0]},{relative_other[1]}"
        player["lost_known_players"].setdefault(relative_key, [])
        if not any(item["sid"] == other["sid"] for item in player["lost_known_players"][relative_key]):
            player["lost_known_players"][relative_key].append({
                "sid": other["sid"],
                "name": other["name"],
                "color": other.get("color", DEFAULT_PLAYER_COLOR),
            })


def check_lost_map_completion(player):
    tiles = player["lost_known_tiles"] if player["lost"] else player["known_tiles"]
    coordinates = [
        tuple(int(value) for value in key.split(","))
        for key in tiles
    ]
    if not coordinates:
        return False

    known_x = {x for x, _ in coordinates}
    known_y = {y for _, y in coordinates}
    if player["lost"]:
        message = lost_map_completion_message(player, known_x, known_y)
        if message:
            share_lost_section_with_everyone(player)
            recover_from_lost(
                player,
                message,
                reveal_position_to_everyone=True,
            )
            return True
    elif len(known_x) >= BOARD_SIZE and len(known_y) >= BOARD_SIZE:
        share_current_section_with_everyone(player)
        reveal_player_position_to_everyone(player)
        return True
    return False


def remember_lost_tile(player, pos, source="revealed"):
    relative_pos = lost_relative_position_for(player, pos)
    key = f"{relative_pos[0]},{relative_pos[1]}"
    is_new = key not in player["lost_known_tiles"]
    player["lost_known_tiles"][key] = effective_tile_at(pos)
    player["lost_manual_tiles"].pop(key, None)

    if player.get("lost_kind") == "river":
        GAME["river_lost_map"]["tiles"][key] = effective_tile_at(pos)

    # A flashlight can reveal a special tile that is already drawn on the
    # persistent river map.  It still counts as discovering that tile now.
    if tile_allows_map_fusion(pos):
        reveal_players_at_lost_special_tile(player, pos)

    log_special_tile_reveal(player, pos, source)

    check_lost_map_completion(player)
    return is_new


def start_lost_relative_map(player):
    """Start at 0,0; river loss also restores the persistent shared river map."""
    player["lost_relative_x"] = 0
    player["lost_relative_y"] = 0
    if player.get("lost_kind") == "river":
        player["lost_known_tiles"] = copy.deepcopy(GAME["river_lost_map"]["tiles"])
        player["lost_known_open_edges"] = copy.deepcopy(GAME["river_lost_map"]["open_edges"])
        player["lost_known_broken_walls"] = copy.deepcopy(GAME["river_lost_map"]["broken_walls"])
        player["lost_known_wall_edges"] = copy.deepcopy(GAME["river_lost_map"]["wall_edges"])
    else:
        player["lost_known_tiles"] = {}
        player["lost_known_open_edges"] = []
        player["lost_known_broken_walls"] = []
        player["lost_known_wall_edges"] = []
    player["lost_known_players"] = {}
    player["lost_manual_tiles"] = {}
    player["lost_river_players"] = {}
    player["lost_outer_wall_bomb_clues"] = {}
    if player["x"] is not None and player["y"] is not None:
        remember_lost_tile(player, (player["x"], player["y"]))


def reveal_player_position_to_everyone(player):
    """Publish a current location until that player becomes lost again."""
    was_already_public = player["sid"] in GAME["public_revealed_positions"]
    GAME["public_revealed_positions"][player["sid"]] = {
        "sid": player["sid"],
        "name": player["name"],
        "color": player.get("color", DEFAULT_PLAYER_COLOR),
        "x": player["x"],
        "y": player["y"],
    }
    return not was_already_public


def append_unique_edge(target, edge):
    if edge not in target:
        target.append(copy.deepcopy(edge))


def share_map_with_everyone(tiles, open_edges, broken_walls, wall_edges):
    """Add a completed section of map knowledge to every player's normal map."""
    for recipient in GAME["players"].values():
        for key, tile in tiles.items():
            recipient["known_tiles"][key] = tile
            recipient["manual_tiles"].pop(key, None)
        for edge in open_edges:
            append_unique_edge(recipient["known_open_edges"], edge)
        for edge in broken_walls:
            append_unique_edge(recipient["known_broken_walls"], edge)
        for edge in wall_edges:
            append_unique_edge(recipient["known_wall_edges"], edge)


def share_current_section_with_everyone(player):
    """Share only discoveries made after this player's most recent lost state."""
    previous_tiles = player.get("last_lost_known_tiles", {})
    tiles = {
        key: value for key, value in player["known_tiles"].items()
        if key not in previous_tiles
    }
    share_map_with_everyone(
        tiles,
        player["known_open_edges"],
        player["known_broken_walls"],
        player["known_wall_edges"],
    )


def share_lost_section_with_everyone(player):
    """Share the new section, plus the old section too when the two overlap."""
    previous_tiles = player.get("known_tiles_before_lost", {})
    tiles = {}
    overlaps_previous_section = False

    def actual_position(relative_position):
        return (
            player["x"] + relative_position[0] - player["lost_relative_x"],
            player["y"] + relative_position[1] - player["lost_relative_y"],
        )

    for relative_key, tile in player["lost_known_tiles"].items():
        relative = tuple(int(value) for value in relative_key.split(","))
        actual = actual_position(relative)
        actual_key = f"{actual[0]},{actual[1]}"
        if in_bounds(*actual) and actual_key in previous_tiles:
            overlaps_previous_section = True
        if in_bounds(*actual):
            tiles[actual_key] = tile

    def translate_edges(relative_edges):
        translated = []
        for edge in relative_edges:
            actual_a = actual_position(tuple(edge[0]))
            actual_b = actual_position(tuple(edge[1]))
            key_a = f"{actual_a[0]},{actual_a[1]}"
            key_b = f"{actual_b[0]},{actual_b[1]}"
            if (
                in_bounds(*actual_a)
                and in_bounds(*actual_b)
                and key_a not in previous_tiles
                and key_b not in previous_tiles
            ):
                append_unique_edge(translated, serialize_edge(actual_a, actual_b))
        return translated

    new_open_edges = translate_edges(player["lost_known_open_edges"])
    new_broken_walls = translate_edges(player["lost_known_broken_walls"])
    new_wall_edges = translate_edges(player["lost_known_wall_edges"])

    if overlaps_previous_section:
        tiles = {**previous_tiles, **tiles}
        new_open_edges = [*player.get("known_open_edges_before_lost", []), *new_open_edges]
        new_broken_walls = [*player.get("known_broken_walls_before_lost", []), *new_broken_walls]
        new_wall_edges = [*player.get("known_wall_edges_before_lost", []), *new_wall_edges]

    share_map_with_everyone(tiles, new_open_edges, new_broken_walls, new_wall_edges)
    return overlaps_previous_section


def merge_map_knowledge(receiver, donor):
    for key, value in donor["known_tiles"].items():
        if key not in receiver["known_tiles"]:
            receiver["known_tiles"][key] = value
        receiver["manual_tiles"].pop(key, None)

    for edge in donor["known_open_edges"]:
        if edge not in receiver["known_open_edges"]:
            receiver["known_open_edges"].append(copy.deepcopy(edge))

    for edge in donor["known_broken_walls"]:
        if edge not in receiver["known_broken_walls"]:
            receiver["known_broken_walls"].append(copy.deepcopy(edge))

    for edge in donor["known_wall_edges"]:
        if edge not in receiver["known_wall_edges"]:
            receiver["known_wall_edges"].append(copy.deepcopy(edge))

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


def is_special_tile(pos):
    """A tile worth announcing when it is revealed.

    River squares are included here because they are meaningful discoveries,
    even though they do not trigger normal special-tile map sharing.
    """
    return GAME["board"].get(pos, "empty") != "empty"


def log_special_tile_reveal(player, pos, source):
    if not is_special_tile(pos):
        return
    tile = GAME["board"].get(pos, "empty")
    log(f"{player['name']} {source} special tile: {tile}.")


def add_special_tile_information_to_map(player, pos):
    """Copy map information supplied by a normally discovered special tile.

    A player who sees a special tile—by stepping on it or by flashlight—has
    made the same discovery.  Other non-lost players who previously visited
    that tile can therefore contribute their map knowledge.  Lost players use
    their relative special-tile map instead, so their hidden location is never
    exposed through this normal-map path.
    """
    if not GAME["game_started"] or player["lost"] or not tile_allows_map_fusion(pos):
        return []

    tile_key = f"{pos[0]},{pos[1]}"
    contributors = []
    for other in GAME["players"].values():
        if (
            other["sid"] == player["sid"]
            or not other["alive"]
            or other["lost"]
            or other["x"] is None
            or other["y"] is None
            or tile_key not in other["visited_tiles"]
        ):
            continue

        merge_map_knowledge(player, other)
        set_relative_player_visibility(player, other)
        contributors.append(other["name"])

    if contributors:
        log(
            f"{player['name']} added map information from "
            f"{', '.join(contributors)} through {GAME['board'][pos]}."
        )
    return contributors


def player_is_on_your_map(viewer, other_sid):
    for arr in viewer["known_players"].values():
        for pp in arr:
            if pp["sid"] == other_sid:
                return True
    return False


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
    """Only show players who are currently sharing the viewer's tile.

    Players have separate maps. Seeing somebody must not reveal their past
    discoveries or let a player track them after they walk away.
    """
    for viewer in GAME["players"].values():
        viewer["known_players"] = {}
        if not viewer["alive"] or viewer["x"] is None or viewer["y"] is None:
            continue

        for other in GAME["players"].values():
            current_key = f"{other['x']},{other['y']}"
            exited_lost_here = (
                other.get("lost_exit_visible_position") == (other["x"], other["y"])
                and current_key in viewer["visited_tiles"]
            )
            if (
                other["sid"] != viewer["sid"]
                and other["alive"]
                and other["x"] == viewer["x"]
                and other["y"] == viewer["y"]
            ) or (
                other["sid"] != viewer["sid"]
                and other["alive"]
                and exited_lost_here
            ):
                set_relative_player_visibility(viewer, other)


def refresh_lost_river_player_positions():
    """River-lost players share the river-start-relative map with each other."""
    river_lost_players = [
        player for player in GAME["players"].values()
        if player["alive"] and player["lost"] and player.get("lost_kind") == "river"
    ]

    for viewer in river_lost_players:
        viewer["lost_river_players"] = {}
        for other in river_lost_players:
            if other["sid"] == viewer["sid"]:
                continue
            key = f"{other['lost_relative_x']},{other['lost_relative_y']}"
            viewer["lost_river_players"].setdefault(key, []).append({
                "sid": other["sid"],
                "name": other["name"],
                "color": other.get("color", DEFAULT_PLAYER_COLOR),
            })


def announce_players_on_tile(player):
    """Notify all players when they discover one another on the same tile."""
    companions = [
        other for other in GAME["players"].values()
        if other["sid"] != player["sid"]
        and other["alive"]
        and other["x"] == player["x"]
        and other["y"] == player["y"]
    ]
    if not companions:
        return

    names = ", ".join(other["name"] for other in companions)
    set_player_message(player, f"You found {names}.")
    for other in companions:
        set_player_message(other, f"{player['name']} found you.")
    log(f"{player['name']} found {names}.")


def enter_lost_state(player, lost_kind):
    if not player["lost"]:
        player["known_tiles_before_lost"] = copy.deepcopy(player["known_tiles"])
        player["known_open_edges_before_lost"] = copy.deepcopy(player["known_open_edges"])
        player["known_broken_walls_before_lost"] = copy.deepcopy(player["known_broken_walls"])
        player["known_wall_edges_before_lost"] = copy.deepcopy(player["known_wall_edges"])
        player["last_lost_known_tiles"] = copy.deepcopy(player["known_tiles"])
    player["lost"] = True
    player["lost_kind"] = lost_kind
    GAME["public_revealed_positions"].pop(player["sid"], None)
    clear_relative_player_visibility(player)


def previously_known_tile_ends_lost(player, pos=None):
    if pos is None:
        if player["x"] is None or player["y"] is None:
            return False
        pos = (player["x"], player["y"])
    if pos is None:
        return False
    key = f"{pos[0]},{pos[1]}"
    return key in player.get("known_tiles_before_lost", {})


def recover_from_lost(player, message, reveal_position_to_everyone=False):
    player["lost"] = False
    player["lost_kind"] = None
    player["lost_exit_visible_position"] = (player["x"], player["y"])
    reveal_current_position(player)
    player["known_tiles_before_lost"] = {}
    if reveal_position_to_everyone:
        reveal_player_position_to_everyone(player)
    set_player_message(player, message)
    log(f"{player['name']} is no longer lost.")


def activate_map_fusion(player):
    if not GAME["game_started"]:
        return

    if player["x"] is None or player["y"] is None:
        return

    current_pos = (player["x"], player["y"])
    current_key = f"{player['x']},{player['y']}"

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

        if player["lost"]:
            if any(player_is_on_your_map(player, other["sid"]) for other in same_tile_players):
                recover_from_lost(player, f"You met {', '.join([p['name'] for p in same_tile_players])} → MAP FUSION!")
        else:
            reveal_current_position(player)
            set_player_message(player, f"You met {', '.join([p['name'] for p in same_tile_players])} → MAP FUSION!")

        for other in same_tile_players:
            if other["lost"]:
                if player_is_on_your_map(other, player["sid"]):
                    recover_from_lost(other, f"You met {player['name']} → MAP FUSION!")
            else:
                reveal_current_position(other)
                set_player_message(other, f"You met {player['name']} → MAP FUSION!")

        if len(involved) == 2:
            log(f"{player['name']} met {same_tile_players[0]['name']} → MAP FUSION")
        else:
            log("MAP FUSION happened between players on the same tile.")
        return

    if not tile_allows_map_fusion(current_pos) and not is_birth_spot(current_pos):
        return

    for other in GAME["players"].values():
        if other["sid"] == player["sid"]:
            continue
        if other["x"] is None or other["y"] is None:
            continue

        if current_key in other["visited_tiles"]:
            merge_map_knowledge(player, other)
            set_relative_player_visibility(player, other)

            if player["lost"]:
                if player_is_on_your_map(player, other["sid"]):
                    recover_from_lost(player, f"You found traces of {other['name']} → MAP FUSION")
                else:
                    set_player_message(player, f"You found traces of {other['name']} → MAP FUSION")
            else:
                reveal_current_position(player)
                set_player_message(player, f"You found traces of {other['name']} → MAP FUSION")
            return


def check_birth_spot_discovery(player):
    if player["x"] is None or player["y"] is None:
        return False

    if (
        player["birth_x"] is not None
        and player["birth_y"] is not None
        and player["x"] == player["birth_x"]
        and player["y"] == player["birth_y"]
    ):
        if player["lost"]:
            recover_from_lost(player, "You found your birth spot and are no longer lost.")
            return True
        return False

    for other in GAME["players"].values():
        if other["sid"] == player["sid"]:
            continue
        if other["birth_x"] is None or other["birth_y"] is None:
            continue

        if player["x"] == other["birth_x"] and player["y"] == other["birth_y"]:
            set_player_message(player, f"You found {other['name']}'s birth spot.")
            log(f"{player['name']} found {other['name']}'s birth spot")
            return False

    return False


def check_previously_known_recovery(player, pos=None, discovered_by_flashlight=False):
    if player["lost"] and previously_known_tile_ends_lost(player, pos):
        message = (
            "Your flashlight revealed a familiar tile and you are no longer lost."
            if discovered_by_flashlight
            else "You reached a familiar tile and are no longer lost."
        )
        recover_from_lost(player, message)
        return True
    return False


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


def create_player(sid, name, color=DEFAULT_PLAYER_COLOR):
    return {
        "sid": sid,
        "name": name,
        "color": normalize_player_color(color),
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
        "manual_tiles": {},
        "known_tiles_before_lost": {},
        "known_open_edges_before_lost": [],
        "known_broken_walls_before_lost": [],
        "known_wall_edges_before_lost": [],
        "last_lost_known_tiles": {},
        "known_players": {},
        "known_open_edges": [],
        "known_broken_walls": [],
        "known_wall_edges": [],
        "visited_tiles": [],
        "lost_relative_x": 0,
        "lost_relative_y": 0,
        "lost_known_tiles": {},
        "lost_manual_tiles": {},
        "lost_known_players": {},
        "lost_known_open_edges": [],
        "lost_known_broken_walls": [],
        "lost_known_wall_edges": [],
        "lost_river_players": {},
        "lost_outer_wall_bomb_clues": {},
        "lost_kind": None,
        "lost_exit_visible_position": None,
        "last_message": "Choose a spawn tile by tapping the board.",
        "extra_turn": False,
        "lost": False,
    }


def set_player_message(player, message):
    player["last_message"] = message
    # The shared expedition log is the history everyone can see.  Keep every
    # player's latest result there as well as on their own player panel.
    log(f"{player['name']}: {message}")


def effective_tile_at(pos):
    base = GAME["board"].get(pos, "empty")
    if pos in GAME["consumed_tiles"] and base in PICKUP_TILES:
        return f"used_{base}"
    return base


def add_known_tile(player, pos):
    if not in_bounds(pos[0], pos[1]):
        return
    key = f"{pos[0]},{pos[1]}"
    player["known_tiles"][key] = effective_tile_at(pos)
    player["manual_tiles"].pop(key, None)


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


def reveal_position(player, pos, source="revealed"):
    add_known_tile(player, pos)
    remember_visited_tile(player, pos)
    log_special_tile_reveal(player, pos, source)
    add_special_tile_information_to_map(player, pos)
    update_known_players_for_viewer(player)
    if not player["lost"]:
        check_lost_map_completion(player)


def reveal_current_position(player, source="revealed"):
    if player["x"] is None or player["y"] is None:
        return
    pos = (player["x"], player["y"])
    if player["lost"]:
        remember_visited_tile(player, pos)
        remember_lost_tile(player, pos, source)
        return
    reveal_position(player, pos, source)


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
    elif len(alive) == 0 and len(GAME["players"]) >= 2:
        GAME["game_over"] = True
        GAME["winner_sid"] = None
        GAME["winner_reason"] = "all_players_dead"
        log("All players died. The game ended with no winner.")


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
        new_state["players"][sid] = create_player(
            sid, old_player["name"], old_player.get("color")
        )
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
        return {
            "ok": False,
            "message": "The board needs at least one river tile (river_start counts).",
        }

    if len(river_positions) > 20:
        return {"ok": False, "message": "River may use at most 20 tiles including river_start."}

    river_starts = [pos for pos, tile in GAME["board"].items() if tile == "river_start"]
    if len(river_starts) != 1:
        return {"ok": False, "message": "River must contain exactly one river_start tile."}

    river_start = river_starts[0]

    # A river may turn a corner. A diagonal pair is invalid only when it is
    # not joined by a river tile on either side of that diagonal.
    for (x, y) in river_positions:
        diagonal_neighbors = [
            (x - 1, y - 1), (x + 1, y - 1),
            (x - 1, y + 1), (x + 1, y + 1),
        ]
        for diagonal in diagonal_neighbors:
            if diagonal not in river_positions:
                continue
            dx, dy = diagonal[0] - x, diagonal[1] - y
            connecting_tiles = [(x + dx, y), (x, y + dy)]
            if not any(pos in river_positions for pos in connecting_tiles):
                return {
                    "ok": False,
                    "message": "Diagonal river tiles must connect through a river tile.",
                }

    orth_neighbors = {}
    for (x, y) in river_positions:
        neighbors = []
        for dx, dy in DIRECTIONS.values():
            nxt = (x + dx, y + dy)
            if nxt in river_positions and not has_inner_wall_between((x, y), nxt):
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

    return {"ok": False, "message": "All river tiles must be connected."}


def required_tile_validation():
    """Check the one-of-each-tile rule used when starting a game."""
    counts = {
        tile: sum(board_tile == tile for board_tile in GAME["board"].values())
        for tile in REQUIRED_SINGLE_TILES
    }
    missing = sorted(tile for tile, count in counts.items() if count == 0)
    duplicates = sorted(tile for tile, count in counts.items() if count > 1)

    if missing:
        return {
            "ok": False,
            "message": f"The board is missing: {', '.join(missing)}.",
        }
    if duplicates:
        return {
            "ok": False,
            "message": f"Only one of each is allowed: {', '.join(duplicates)}.",
        }
    return {"ok": True, "message": "All required tile types are placed exactly once."}


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


def apply_tile_effect(player, discovery_source="stepped onto"):
    pos = (player["x"], player["y"])
    raw_tile = GAME["board"][pos]

    reveal_current_position(player, discovery_source)

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
        if 0 < player["injuries"] < 4:
            player["injuries"] = 0
            set_player_message(player, "Clinic healed all of your injuries.")
        elif player["injuries"] == 4:
            set_player_message(player, "Clinic cannot treat 4 injuries. Go to the ER.")
        else:
            set_player_message(player, "Clinic did nothing because you have no injuries.")
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
                river_start_key = f"{river_start[0]},{river_start[1]}"
                player_knows_river_start = river_start_key in player["known_tiles"]

                player["x"], player["y"] = river_start

                if player_knows_river_start:
                    remember_visited_tile(player, river_start)
                    reveal_current_position(player, "arrived at")
                    remember_open_edge(player, pos, river_start)
                    set_player_message(player, "You used the raft. No injury, and you drifted to the known river start.")
                else:
                    enter_lost_state(player, "river")
                    start_lost_relative_map(player)
                    set_player_message(player, "You used the raft. No injury, but you were dragged to an unknown river start and became lost.")
            else:
                set_player_message(player, "You used the raft.")
            return "continue"

        player["injuries"] += 1
        if check_death(player, "Killed by river injury."):
            return "dead"

        enter_lost_state(player, "river")

        if river_start is not None:
            player["x"], player["y"] = river_start
            start_lost_relative_map(player)

        set_player_message(player, "The river injured you, dragged you to the river start, and you are now lost.")
        return "continue"

    set_player_message(player, f"You stepped on: {raw_tile}")
    return "continue"


def reveal_line(player, direction):
    dx, dy = DIRECTIONS[direction]
    x, y = player["x"], player["y"]
    revealed = []
    prev = (x, y)

    while True:
        if wall_blocks(x, y, direction):
            if not is_outer_wall(x, y, direction):
                nx, ny = x + dx, y + dy
                if in_bounds(nx, ny):
                    if player["lost"]:
                        remember_lost_edge(player, "lost_known_wall_edges", (x, y), (nx, ny))
                    else:
                        remember_wall_edge(player, (x, y), (nx, ny))
            break

        x += dx
        y += dy
        if not in_bounds(x, y):
            break

        current = (x, y)
        was_lost = player["lost"]
        if was_lost:
            remember_lost_edge(player, "lost_known_open_edges", prev, current)
            remember_visited_tile(player, current)
            remember_lost_tile(player, current, "used a flashlight on")
            recovered = check_previously_known_recovery(
                player,
                current,
                discovered_by_flashlight=True,
            )
        else:
            remember_open_edge(player, prev, current)
            reveal_position(player, current, "used a flashlight on")
            recovered = False
        revealed.append(current)
        if recovered or (was_lost and not player["lost"]):
            break
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
        "color": player.get("color", DEFAULT_PLAYER_COLOR),
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

    # A river or black hole hides the player's current position, not the map
    # they already made.  Each player always keeps their own discoveries.
    if player["lost"]:
        known_tiles = copy.deepcopy(player["lost_known_tiles"])
        manual_tiles = copy.deepcopy(player["lost_manual_tiles"])
        known_players = copy.deepcopy(player["lost_known_players"])
        for key, players in player["lost_river_players"].items():
            known_players.setdefault(key, [])
            for other in players:
                if not any(existing["sid"] == other["sid"] for existing in known_players[key]):
                    known_players[key].append(copy.deepcopy(other))
        known_open_edges = copy.deepcopy(player["lost_known_open_edges"])
        known_broken_walls = copy.deepcopy(player["lost_known_broken_walls"])
        known_wall_edges = copy.deepcopy(player["lost_known_wall_edges"])
    else:
        known_tiles = copy.deepcopy(player["known_tiles"])
        manual_tiles = copy.deepcopy(player["manual_tiles"])
        known_players = copy.deepcopy(player["known_players"])
        known_open_edges = copy.deepcopy(player["known_open_edges"])
        known_broken_walls = copy.deepcopy(player["known_broken_walls"])
        known_wall_edges = copy.deepcopy(player["known_wall_edges"])
    player_view = serialize_player_public(player)

    # The manager remains the only client who receives a lost player's actual
    # location.  The game server still uses it to validate every action.
    if player["lost"]:
        player_view["x"] = None
        player_view["y"] = None

    return {
        "you": player_view,
        "public_revealed_players": list(GAME["public_revealed_positions"].values()),
        "lost_relative_position": {
            "x": player["lost_relative_x"],
            "y": player["lost_relative_y"],
        } if player["lost"] else None,
        "your_known_tiles": known_tiles,
        "your_manual_tiles": manual_tiles,
        "your_known_players": known_players,
        "your_known_open_edges": known_open_edges,
        "your_known_broken_walls": known_broken_walls,
        "your_known_wall_edges": known_wall_edges,
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
    GAME["public_revealed_positions"] = {
        sid: {
            "sid": player["sid"],
            "name": player["name"],
            "color": player.get("color", DEFAULT_PLAYER_COLOR),
            "x": player["x"],
            "y": player["y"],
        }
        for sid in GAME["public_revealed_positions"]
        if (player := GAME["players"].get(sid))
        and player["alive"]
        and not player["lost"]
        and player["x"] is not None
        and player["y"] is not None
    }
    refresh_lost_river_player_positions()
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
    color = normalize_player_color(data.get("color"))

    if not name:
        emit("error_message", {"message": "Name is required."})
        return

    if GAME["game_started"] and sid not in GAME["players"]:
        emit("error_message", {"message": "A game is already in progress. Join the next game after a reset."})
        return

    if any(p_sid != sid and p["name"].casefold() == name.casefold() for p_sid, p in GAME["players"].items()):
        emit("error_message", {"message": "That player name is already in use."})
        return

    if sid not in GAME["players"]:
        GAME["players"][sid] = create_player(sid, name, color)
        log(f"{name} joined the game.")
    else:
        GAME["players"][sid]["name"] = name
        GAME["players"][sid]["color"] = color

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

    if GAME["game_started"]:
        emit("error_message", {"message": "The board is locked while a game is in progress. Reset the game to edit it."})
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

    current_tile = GAME["board"][(x, y)]
    if tile in REQUIRED_SINGLE_TILES:
        duplicate_exists = any(
            pos != (x, y) and board_tile == tile
            for pos, board_tile in GAME["board"].items()
        )
        if duplicate_exists:
            emit("error_message", {"message": f"Only one {tile} tile is allowed."})
            return

    if tile == "river_start":
        duplicate_start_exists = any(
            pos != (x, y) and board_tile == "river_start"
            for pos, board_tile in GAME["board"].items()
        )
        if duplicate_start_exists:
            emit("error_message", {"message": "Only one river_start tile is allowed."})
            return

    if tile in {"river", "river_start"} and current_tile not in {"river", "river_start"}:
        if len(get_river_positions()) >= 20:
            emit("error_message", {"message": "River may use at most 20 tiles including river_start."})
            return

    GAME["board"][(x, y)] = tile
    GAME["consumed_tiles"].discard((x, y))
    emit_full_state()


@socketio.on("manager_toggle_inner_wall")
def manager_toggle_inner_wall(data):
    if request.sid != MANAGER_SID:
        emit("error_message", {"message": "Only the manager can edit walls."})
        return

    if GAME["game_started"]:
        emit("error_message", {"message": "The board is locked while a game is in progress. Reset the game to edit it."})
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

    if GAME["game_started"]:
        emit("error_message", {"message": "The board is locked while a game is in progress. Reset the game to edit it."})
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

    validation = river_validation()
    if not validation["ok"]:
        emit("error_message", {"message": f"Cannot start: {validation['message']}"})
        return

    required_tiles = required_tile_validation()
    if not required_tiles["ok"]:
        emit("error_message", {"message": f"Cannot start: {required_tiles['message']}"})
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
        player["lost_kind"] = None
        player["lost_exit_visible_position"] = None
        player["known_tiles_before_lost"] = {}
        player["known_open_edges_before_lost"] = []
        player["known_broken_walls_before_lost"] = []
        player["known_wall_edges_before_lost"] = []
        player["last_lost_known_tiles"] = {}
        player["lost_known_tiles"] = {}
        player["lost_known_players"] = {}
        player["lost_known_open_edges"] = []
        player["lost_known_broken_walls"] = []
        player["lost_known_wall_edges"] = []
        spawn_tile = GAME["board"][(player["x"], player["y"])]
        apply_tile_effect(player, "spawned on")
        set_player_message(player, f"Spawned on {spawn_tile}. {player['last_message']}")

    for player in GAME["players"].values():
        check_birth_spot_discovery(player)
        check_previously_known_recovery(player)
        activate_map_fusion(player)

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
    player["manual_tiles"] = {}
    player["known_tiles_before_lost"] = {}
    player["known_open_edges_before_lost"] = []
    player["known_broken_walls_before_lost"] = []
    player["known_wall_edges_before_lost"] = []
    player["last_lost_known_tiles"] = {}
    player["known_players"] = {}
    player["known_open_edges"] = []
    player["known_broken_walls"] = []
    player["known_wall_edges"] = []
    player["visited_tiles"] = [f"{x},{y}"]
    player["lost_known_tiles"] = {}
    player["lost_manual_tiles"] = {}
    player["lost_known_players"] = {}
    player["lost_known_open_edges"] = []
    player["lost_known_broken_walls"] = []
    player["lost_known_wall_edges"] = []
    player["lost_river_players"] = {}
    player["lost_kind"] = None
    player["lost_exit_visible_position"] = None

    set_player_message(player, "Spawn selected. Your starting tile will be revealed when the game begins.")
    log(f"{player['name']} chose a spawn tile.")
    emit_full_state()


@socketio.on("player_set_map_note")
def player_set_map_note(data):
    """Let a player mark a personal map guess without changing the board."""
    if request.sid not in GAME["players"]:
        emit("error_message", {"message": "Player not found."})
        return
    if not GAME["game_started"]:
        emit("error_message", {"message": "Map notes are available after the game starts."})
        return

    try:
        x = int(data["x"])
        y = int(data["y"])
    except (KeyError, TypeError, ValueError):
        emit("error_message", {"message": "Invalid map-note coordinates."})
        return

    tile = data.get("tile", "")
    if tile not in TILE_TYPES and tile != "":
        emit("error_message", {"message": "Invalid map-note tile."})
        return

    player = GAME["players"][request.sid]
    key = f"{x},{y}"
    if player["lost"]:
        if not (-100 <= x <= 100 and -100 <= y <= 100):
            emit("error_message", {"message": "That relative map square is too far away."})
            return
        known_tiles = player["lost_known_tiles"]
        manual_tiles = player["lost_manual_tiles"]
    else:
        if not in_bounds(x, y):
            emit("error_message", {"message": "Map-note coordinates are out of bounds."})
            return
        known_tiles = player["known_tiles"]
        manual_tiles = player["manual_tiles"]

    if key in known_tiles:
        emit("error_message", {"message": "That square is already confirmed on your map."})
        return

    if tile:
        manual_tiles[key] = tile
        set_player_message(player, f"Map note: marked {tile} at {x},{y} as an unconfirmed guess.")
    else:
        manual_tiles.pop(key, None)
        set_player_message(player, f"Map note cleared at {x},{y}.")
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
        if player["lost"]:
            dx, dy = DIRECTIONS[direction]
            remember_lost_edge(player, "lost_known_wall_edges", (x, y), (x + dx, y + dy))
        elif not is_outer_wall(x, y, direction):
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

    was_lost = player["lost"]
    if not was_lost:
        remember_open_edge(player, (x, y), new_pos)
    player["x"] = new_pos[0]
    player["y"] = new_pos[1]
    if was_lost:
        player["lost_relative_x"] += dx
        player["lost_relative_y"] += dy
        remember_lost_edge(player, "lost_known_open_edges", (x, y), new_pos)
        remember_visited_tile(player, new_pos)
        remember_lost_tile(player, new_pos, "stepped onto")
    else:
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

    check_birth_spot_discovery(player)
    check_previously_known_recovery(player)
    announce_players_on_tile(player)
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
            if not is_outer_wall(x, y, direction):
                nx, ny = x + dx, y + dy
                if in_bounds(nx, ny):
                    if shooter["lost"]:
                        remember_lost_edge(shooter, "lost_known_wall_edges", (x, y), (nx, ny))
                    else:
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
        if player["lost"]:
            remember_lost_outer_wall_bomb(player, direction)
            if not check_lost_map_completion(player):
                edge_name = {
                    "up": "north",
                    "down": "south",
                    "left": "west",
                    "right": "east",
                }[direction]
                set_player_message(player, f"The wall did not explode. You found the {edge_name} outer edge.")
        else:
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
        if player["lost"]:
            remember_lost_edge(player, "lost_known_broken_walls", (x, y), (nx, ny))
        else:
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

    was_lost = player["lost"]
    revealed = reveal_line(player, direction)
    seen_tiles = [effective_tile_at(pos).replace("used_", "used ") for pos in revealed]
    seen_description = ", ".join(seen_tiles)
    if was_lost and not player["lost"]:
        recovery_message = player["last_message"]
        set_player_message(
            player,
            f"Flashlight looked {direction} and saw: {seen_description}. {recovery_message}",
        )
    elif revealed:
        set_player_message(
            player,
            f"Flashlight looked {direction} and saw {len(revealed)} tile(s): {seen_description}.",
        )
    else:
        set_player_message(player, f"Flashlight looked {direction} but a wall blocked the beam.")

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
    enter_lost_state(player, "black_hole")
    player["x"] = x
    player["y"] = y
    start_lost_relative_map(player)

    set_player_message(player, "You are lost after the black hole.")
    log(f"Manager placed {player['name']} after black hole.")

    GAME["pending_black_hole"] = None
    check_birth_spot_discovery(player)
    check_previously_known_recovery(player)
    announce_players_on_tile(player)
    refresh_known_player_positions()
    emit_full_state()
    end_turn()


if __name__ == "__main__":
    log("Server started.")
    socketio.run(app, host="0.0.0.0", port=10000)
