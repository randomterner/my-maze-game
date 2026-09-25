"""Foundation for a future generator; not connected to manager controls yet.

This first version makes a seeded, legal open-board candidate: one of every
required single tile, an edge exit, and a straight river. It does not select
spawns, add interior walls, rate difficulty, or guarantee a win from every
spawn. Future search/validation can build on GeneratedMap without touching
the running game's state.
"""

from dataclasses import dataclass, field
import random
from typing import Iterable


@dataclass
class GeneratedMap:
    seed: int | None
    board: dict[tuple[int, int], str]
    inner_walls: set = field(default_factory=set)


def generate_candidate(required_single_tiles: Iterable[str], *, seed: int | None = None,
                       river_length: int = 5) -> GeneratedMap:
    """Return a new 10x10 candidate; river_length includes river_start.

    Pass the game's REQUIRED_SINGLE_TILES so this foundation does not keep
    a second, potentially outdated copy of the tile rules.
    """
    if not isinstance(river_length, int) or isinstance(river_length, bool) or not 1 <= river_length <= 10:
        raise ValueError("This initial generator supports a straight river of 1 to 10 tiles.")
    required = set(required_single_tiles)
    if "exit" not in required or required & {"empty", "river", "river_start"}:
        raise ValueError("Supply the required single-use tile types, including exit.")
    if len(required) + river_length > 100:
        raise ValueError("Too many required tiles for a 10x10 map.")

    rng = random.Random(seed)
    board = {(x, y): "empty" for y in range(10) for x in range(10)}
    horizontal = rng.choice([True, False])
    lane, offset = rng.randrange(10), rng.randrange(11 - river_length)
    river = [(offset + n, lane) if horizontal else (lane, offset + n) for n in range(river_length)]
    if rng.choice([True, False]):
        river.reverse()
    for index, pos in enumerate(river):
        board[pos] = "river_start" if index == 0 else "river"

    edge_spaces = [pos for pos, tile in board.items()
                   if tile == "empty" and (pos[0] in (0, 9) or pos[1] in (0, 9))]
    board[rng.choice(edge_spaces)] = "exit"
    spaces = [pos for pos, tile in board.items() if tile == "empty"]
    rng.shuffle(spaces)
    for tile, pos in zip(sorted(required - {"exit"}), spaces):
        board[pos] = tile
    return GeneratedMap(seed=seed, board=board)
