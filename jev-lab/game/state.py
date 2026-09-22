"""What the harness observes: a board plus the page's own score and message.

Every fact in here is read from outside the game's code (rendered tiles, the score
element, the message element, and the gameState the page persists). Nothing imports
GameManager, so a bug in the game cannot hide behind the harness reading the same object.
"""

import hashlib
from dataclasses import dataclass, field

import labpaths  # noqa: F401  (puts the reused 2048 modules on sys.path)

import reference2048 as ref

DIRECTIONS = ("up", "right", "down", "left")
SIZE = 4
CORNERS = {"tl": (0, 0), "tr": (0, 3), "bl": (3, 0), "br": (3, 3)}


def board_hash(board):
    """Exact identity of a board, short and stable across processes."""
    payload = ";".join(",".join(str(int(v)) for v in row) for row in board)
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def _rotate(board):
    return [list(row) for row in zip(*board[::-1])]


def _mirror(board):
    return [row[::-1] for row in board]


def symmetry_key(board):
    """Canonical form under the eight board symmetries.

    Two boards that are rotations or mirrors of each other share a key. A policy that
    only reacts to a shape will repeat itself here, which is what makes this a useful
    "equivalent state" signal next to the exact hash.
    """
    forms = []
    current = [list(row) for row in board]
    for _ in range(4):
        forms.append(current)
        forms.append(_mirror(current))
        current = _rotate(current)
    return min(tuple(tuple(row) for row in form) for form in forms)


@dataclass
class Observation:
    """One settled read of the live page."""

    board: list
    score: int = 0
    best: int = 0
    message: str = ""
    model_board: list | None = None
    tiles: int = 0
    read_ms: float = 0.0
    source_note: str = ""
    # 0 up, 1 right, 2 down, 3 left — the game's own index, kept for logging only.
    source: str = "page"

    @property
    def max_tile(self):
        return max((v for row in self.board for v in row), default=0)

    @property
    def empty_cells(self):
        return sum(1 for row in self.board for v in row if v == 0)

    @property
    def board_hash(self):
        return board_hash(self.board)

    @property
    def symmetry_key(self):
        return symmetry_key(self.board)

    @property
    def state_hash(self):
        """Short identity of the board up to rotation and mirroring.

        Two positions that are the same shape share this, which is what makes it a useful
        "this looks familiar" signal next to the exact `board_hash`.
        """
        return hashlib.sha1(repr(self.symmetry_key).encode()).hexdigest()[:12]

    @property
    def won(self):
        return self.message == "You win!"

    @property
    def over(self):
        return self.message == "Game over!"

    @property
    def legal_moves(self):
        return [name for name, index in ref_index().items() if ref.move(self.board, index)[2]]

    @property
    def dead(self):
        return not ref.moves_available(self.board)

    @property
    def well_formed(self):
        """A board is readable only if every cell is empty or a power of two.

        `game_client` writes -1 into a cell where it cannot tell which tile is authoritative
        — that happens when a read lands mid-animation — so -1 means "read it again".
        """
        for row in self.board:
            for value in row:
                if value != 0 and (value < 2 or value & (value - 1)):
                    return False
        return True

    def rows(self):
        return [row[:] for row in self.board]


def from_snapshot(snap, read_ms=0.0):
    """Turn a raw `game_client` snapshot into an Observation.

    The board comes from the page's own persisted `gameState` when it is available, because
    that is the one source that is never mid-animation: `GameManager.actuate` writes it
    synchronously, while the tiles are rendered inside a `requestAnimationFrame` and a moved
    tile keeps its *old* position class for one frame after the move. A read that lands in
    that frame would otherwise report the position before the move — with the score already
    updated — and, on a loaded machine where a frame can outlast the read interval, two
    agreeing reads can both land there.

    The rendered tiles remain the fallback for the one moment the page has no persisted
    board (it clears `gameState` when the game ends) and remain the cross-check: a cell that
    merged holds three elements and `game_client` refuses to guess there, writing -1.
    """
    dom = [row[:] for row in snap["board"]]
    model = snap.get("modelBoard")
    note = ""
    ambiguous = any(v == -1 for row in dom for v in row)
    model_ok = bool(model) and all(v >= 0 for row in model for v in row)
    if model_ok:
        board = [row[:] for row in model]
        if ambiguous:
            note = "ambiguous_tiles_repaired_from_model"
        elif dom != model:
            # One frame of lag between the persisted grid and the painted tiles.
            note = "dom_behind_model"
    else:
        board = dom
        if ambiguous:
            note = "ambiguous_tiles"
    return Observation(
        board=board,
        score=int(snap["score"]),
        best=int(snap["best"]),
        message=snap.get("visibleMessage", "") or "",
        model_board=model,
        tiles=len(snap.get("tiles", ())),
        read_ms=read_ms,
        source_note=note,
    )

