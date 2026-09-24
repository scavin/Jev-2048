# game-test

Tests for the 2048 game in this repository.

The game itself is untouched: the suite drives the real page through real keyboard input and
observes only the rendered DOM and the `localStorage` the page writes. No game internals are
imported, so a bug in `GameManager` cannot hide behind the harness reading the same objects.

Every verdict comes from `reference2048.py`. Nothing here asks a model anything.

## What each file does

| File | Role |
|---|---|
| `reference2048.py` | Independent 2048 rules engine, written from the rules, used as the differential oracle |
| `game_client.py` | Black-box page client: reads the board, presses keys, clicks buttons, seeds a board through the page's own storage |
| `run_tests.py` | The suite: differential move checks, restart, persistence, game over, win / keep playing |
| `mutants.py` | Five real defects injected into private copies of the game; the suite must fail on every one |

## How the suite decides things

**Determinism without controlling randomness.** The game spawns a random tile after every
successful move. Rather than pinning `Math.random`, each move is asserted to produce exactly
the reference slide **plus one new tile of value 2 or 4 in a cell the slide left empty**. That
is stricter than a seeded run: it holds for every possible spawn.

**Three views must agree.** For every move the suite compares the reference engine, the board
recovered from rendered tiles, and the board the page serialized into `localStorage`. A
rendering bug and a model bug therefore cannot cancel out.

**Specific boards without playing thousands of moves.** Game-over and win states are reached
by writing `gameState` into `localStorage` and reloading — the page's own persistence
contract — then playing the one move that triggers the state. The game-over board is built so
the spawned tile can never create a new merge, making the verdict deterministic.

## Running it

Start the game:

```bash
python3 -m http.server 8792 --bind 127.0.0.1                     # serve this repo
```

Run the suite (needs `pip install playwright && playwright install chromium`):

```bash
python game-test/run_tests.py --url http://127.0.0.1:8792/index.html --plies 40
python game-test/run_tests.py --url … --mutants        # require the suite to fail on all 5 mutants
```

The suite exits non-zero if any check fails, or if any mutant survives.

## Notes on the game's observable contract

- `clearMessage()` removes the `game-won` / `game-over` class but leaves the text in the `<p>`.
  The message is hidden by CSS (`display: none`), so visibility — not `textContent` — is what a
  player observes, and what the suite asserts.
- A merged cell renders three elements (the merged tile plus both consumed sources, animated
  into the merge cell), so counting tile elements does not equal the number of tiles.
  `game_client.board_from_tiles` resolves a merged cell by its `tile-merged` marker.
- A dead board seeded with `over: false` never shows "Game over!", because `over` is only set
  after a successful move that leaves no moves available. The suite triggers it with a real
  move instead of asserting on the seeded state.
