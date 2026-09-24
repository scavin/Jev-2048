"""Mutation testing: does the suite actually fail when the game is broken?

A green suite proves nothing on its own. Each mutation below is a real defect in
js/game_manager.js, applied to a private copy of the game so the checked-out source is
never touched. The suite must fail on every one of them.

The mutation names double as the subsystem each defect belongs to, which is what
`--mutants` reports when it says the suite caught it.
"""

import pathlib
import shutil

SOURCE = pathlib.Path(__file__).resolve().parent.parent

# name -> (exact source text, replacement)
MUTATIONS = {
    # Score credited with the pre-merge tile value instead of the merged value.
    "scoring": ("self.score += merged.value;", "self.score += tile.value;"),
    # Drops the "a tile may merge at most once per move" guard.
    "merge": ("if (next && next.value === tile.value && !next.mergedFrom) {",
              "if (next && next.value === tile.value) {"),
    # Removes the reverse traversal that right moves depend on.
    "movement": ("if (vector.x === 1) traversals.x = traversals.x.reverse();", ""),
    # Spawns two tiles after every successful move.
    "spawn": ("  if (moved) {\n    this.addRandomTile();",
              "  if (moved) {\n    this.addRandomTile();\n    this.addRandomTile();"),
    # Declares the game over exactly when moves are still available.
    "game_over_detection": ("if (!this.movesAvailable()) {", "if (this.movesAvailable()) {"),
}

ASSETS = ("index.html", "js", "style", "meta", "favicon.ico")


def build_mutant_tree(dest, source=SOURCE):
    """Copy the game once per mutation and apply exactly one edit to each copy."""
    dest = pathlib.Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    for name, (old, new) in MUTATIONS.items():
        target_dir = dest / name
        target_dir.mkdir(parents=True)
        for item in ASSETS:
            origin = pathlib.Path(source) / item
            if origin.is_dir():
                shutil.copytree(origin, target_dir / item)
            else:
                shutil.copy2(origin, target_dir / item)
        game_manager = target_dir / "js" / "game_manager.js"
        text = game_manager.read_text()
        if text.count(old) != 1:
            raise RuntimeError("mutation %r matched %d times in %s"
                               % (name, text.count(old), game_manager))
        game_manager.write_text(text.replace(old, new))
    return dest
