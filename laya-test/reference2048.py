"""Independent 2048 rules engine.

Written from the rules, not copied from js/game_manager.js, so it can act as the
differential oracle for the real game: same input board + direction must yield the
same output board and score delta.

Board representation: 4x4 list of ints, 0 = empty, rows top to bottom.
"""

import random

SIZE = 4
UP, RIGHT, DOWN, LEFT = 0, 1, 2, 3
VECTORS = {UP: (-1, 0), RIGHT: (0, 1), DOWN: (1, 0), LEFT: (0, -1)}


def new_board():
    return [[0] * SIZE for _ in range(SIZE)]


def clone(board):
    return [row[:] for row in board]


def from_rows(rows):
    board = new_board()
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            board[r][c] = value
    return board


def empty_cells(board):
    return [(r, c) for r in range(SIZE) for c in range(SIZE) if board[r][c] == 0]


def tiles(board):
    return [board[r][c] for r in range(SIZE) for c in range(SIZE) if board[r][c]]


def slide_line(line, reverse=False):
    """Slide one line toward index 0. Returns (new_line, score_gained, moved)."""
    cells = [v for v in line if v]
    if reverse:
        cells.reverse()
    out = []
    gained = 0
    i = 0
    while i < len(cells):
        if i + 1 < len(cells) and cells[i] == cells[i + 1]:
            merged = cells[i] * 2
            out.append(merged)
            gained += merged
            i += 2
        else:
            out.append(cells[i])
            i += 1
    out += [0] * (SIZE - len(out))
    if reverse:
        out.reverse()
    return out, gained, out != list(line)


def move(board, direction):
    """Apply a move. Returns (board, score_gained, moved)."""
    result = clone(board)
    gained_total = 0
    moved_any = False

    if direction == LEFT:
        for r in range(SIZE):
            new_row, gained, moved = slide_line(result[r])
            result[r] = new_row
            gained_total += gained
            moved_any = moved_any or moved
    elif direction == RIGHT:
        for r in range(SIZE):
            new_row, gained, moved = slide_line(result[r], reverse=True)
            result[r] = new_row
            gained_total += gained
            moved_any = moved_any or moved
    elif direction == UP:
        for c in range(SIZE):
            col = [result[r][c] for r in range(SIZE)]
            new_col, gained, moved = slide_line(col)
            for r in range(SIZE):
                result[r][c] = new_col[r]
            gained_total += gained
            moved_any = moved_any or moved
    elif direction == DOWN:
        for c in range(SIZE):
            col = [result[r][c] for r in range(SIZE)]
            new_col, gained, moved = slide_line(col, reverse=True)
            for r in range(SIZE):
                result[r][c] = new_col[r]
            gained_total += gained
            moved_any = moved_any or moved
    else:
        raise ValueError("bad direction %r" % (direction,))

    return result, gained_total, moved_any


def merge_exists(board):
    for r in range(SIZE):
        for c in range(SIZE):
            value = board[r][c]
            if value == 0:
                continue
            if c + 1 < SIZE and board[r][c + 1] == value:
                return True
            if r + 1 < SIZE and board[r + 1][c] == value:
                return True
    return False


def moves_available(board):
    return bool(empty_cells(board)) or merge_exists(board)


def spawn(board, rng):
    """Place a 2 (90%) or 4 (10%) in a uniformly random empty cell."""
    free = empty_cells(board)
    if not free:
        return None
    r, c = rng.choice(free)
    value = 2 if rng.random() < 0.9 else 4
    board[r][c] = value
    return (r, c, value)


def new_game(rng):
    board = new_board()
    spawned = [spawn(board, rng) for _ in range(2)]
    return board, spawned


def winning_tile(board):
    values = tiles(board)
    return max(values) if values else 0


def classify(board, score=0, message=None, keep_playing=False):
    """Ground-truth state class for a board + visible message."""
    message = message or ""
    lowered = message.lower()
    if "game over" in lowered:
        return "game_over_prompt"
    if "you win" in lowered:
        return "won_prompt"
    if not moves_available(board):
        return "dead_no_prompt"
    if len(tiles(board)) <= 2 and score == 0:
        return "fresh_start"
    return "in_progress"


def render_rows(board):
    return " ".join("[" + ",".join(str(v) for v in row) + "]" for row in board)
