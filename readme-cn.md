**English → [readme.md](readme.md)**

# Jev-2048 — 用 2048 实测 Jev 能力边界的实验场

看 Jev 自动玩 2048：默认打开新面板，也可以切换到复古游戏窗口。


## 0. 快速开始

1. 安装 [Python 3.10+](https://www.python.org/downloads/)，准备一个有效的 [TypeSafe API Key](https://typesafe.ai)。
2. Fork 后下载代码并解压，或克隆自己的 fork。
3. 在包含 `start.py` 的文件夹中打开终端，执行：

| 想看哪个界面 | macOS / Linux | Windows |
|---|---|---|
| 新面板（默认） | `python3 start.py` | `py -3 start.py` |
| 复古 2048 窗口 | `python3 start.py --retro` | `py -3 start.py --retro` |

首次启动只补齐缺的部分：机器上已有的依赖和 Chromium 会直接复用，缺失的才安装或下载。
等待完成后，按提示输入 API Key，输入时不显示字符。询问是否保存时，输入 `y` 可供下次使用；
Key 会以明文保存在仓库外的本机配置目录。需要联网，API 调用可能产生费用。

启动后 Jev 会自动开始，一局结束后继续下一局。默认的新面板地址是
[http://127.0.0.1:8799/](http://127.0.0.1:8799/)。

### 常用操作

- **暂停、继续、单步、调速**：在新面板上操作。“单步”让 Jev 再走一步。
- **自己玩**：点 “Play myself”，或直接按方向键，面板就会等你操作。方向键或 W A S D 每按一次走一步，
  和模型走子一样会被记录；在你点 “Jev plays” 之前，Jev 不再调用模型。
  只有新面板提供操作界面，`--retro` 只显示游戏窗口。
- **界面语言**：面板跟随浏览器的语言列表，提供中文和英文，其它语言回退到英文。
  游戏窗口是上游原版游戏，文字不随之改变。
- **停止**：在终端按 `Ctrl-C`。复古模式也可以关闭游戏窗口；关闭新面板标签页不会停止后台游戏。
- **下次启动**：执行同一条命令。环境会复用；保存过 Key 就不用再次输入。
  每次启动都从自动模式开始：上一次的模式和你没走完的按键不会被继承。

macOS 已实测；Windows/Linux 尚未实跑验证。安装位置、Key 管理等细节见 [环境要求](#12-环境要求)。

---

## 实验说明

一个 harness 实验，不是 2048 bot。

游戏是 Gabriele Cirulli 的上游 [2048](https://github.com/gabrielecirulli/2048)，MIT 许可，
原样保留 —— 它自己的署名见 [LICENSE.txt](LICENSE.txt) 和
[README-2048.md](README-2048.md)。`jev-lab/` 下面才是加在上面的实验：它没有重写游戏，
也没有改动游戏的文件，而是从外部驱动它，走渲染后的 DOM 和键盘，完全按人的方式来。

本次实验所依据的原始任务说明保存在 [prompt.md](prompt.md)：它就是这个仓库要回答的问题，
建议和 §10 对照着读 —— 看当初要求了什么、数据实际说了什么。

模型始终不变。这里每个 jev 模式用的都是同一个模型、同一个 endpoint、同一段 rules 文本、
同一组四个候选标签。唯一变化的是 **harness 给它看什么**：

| 模式 | harness 交给 jev 的状态 |
|---|---|
| `jev-board` | 只有 4×4 棋盘，别的什么都没有 |
| `jev-state` | + 分数、最大方块、空格数、上一步、最近几步、步数、无效尝试次数 |
| `jev-history` | + 最近 16 个动作、最近的棋盘摘要、这个形状出现过多少次 |
| `jev-features` | + harness 自己对四个方向做的 one-ply 模拟 |
| `jev-state-history` | `jev-state` **加** `jev-history`，两者同时给 |

第五个条件的由来：四个必需模式之间没法干净地对比。模式 3 的定义是棋盘加历史，
所以从模式 2 走到模式 3，既加进了历史，*又丢掉了模式 2 的计数器* —— 一次改了两件事。
`jev-state-history` 把计数器固定住，再在上面叠历史，这样才能单独隔离出历史本身的效果。

三个确定性基线（`random`、`greedy`、`heuristic`）跑同样的对局，好让 jev 的数字有东西可比。

整个实验存在的目的就是回答一个问题：

> 随着 harness 把越来越多的工作交给 jev，它的能力在哪里停止提升 —— 又在哪一点上，
> 更多上下文不再能替代规划？

本仓库里没有任何地方预设了赢家。对比表是从日志生成的；如果某个 jev 模式输给了 `greedy`，
表里就这么写。

---

## 1. 哪些是复用的，哪些不是

2048 本身没有任何一部分被重写。游戏就是本仓库里已有的上游
[gabrielecirulli/2048](https://github.com/gabrielecirulli/2048)，以静态文件方式伺服：

```bash
# from the repository root; `demo.py` does this for you if you skip it
python3 -m http.server 8792 --bind 127.0.0.1
```

原样复用：

* **`game-test/game_client.py`** —— 黑盒页面客户端。它读取渲染出来的
  `.tile-container .tile` 元素、分数元素，以及页面持久化的 `gameState`，
  并通过真实的指针序列点击游戏自己的重开锚点。不导入任何游戏内部结构，
  所以 `GameManager` 里的 bug 没法躲在「harness 读的是同一张对象图」后面。
* **`game-test/reference2048.py`** —— 独立的规则引擎，本仓库早已把它当作对照页面的差分
  oracle。实验把它用作模拟器，这样「harness 认为这步合法」和「页面同意」始终是两句独立的话。
* **`jev-test/jev_client.py`** —— 加载器，导入 `jev_ultrafast/model.py` 而不会连带拉起浏览器
  agent。
* **`browser-use/jev-ultrafast`** —— `model.post_json` 和 `model.validate_choice`。
  实验里的每一次决策都走这两个函数，和已发布的浏览器 agent 用的是同一对。

实验新增的部分：带种子的浏览器会话、状态构造器、基线、失败检测器、指标、dashboard 和
runner。

### 页面是怎么被控制的

方向键。游戏自己的 `KeyboardInputManager` 把 `ArrowUp/Right/Down/Left` 映射到四个移动，
所以 harness 按键的方式和人一模一样：

| 实验需要什么 | 怎么拿到 |
|---|---|
| 棋盘 | 页面自己持久化的 `gameState`，再和渲染出的方块交叉核对 |
| 分数 | `.score-container` 的文本（`+8` 那段动画 span 会被剥掉） |
| 游戏结束 | 可见的 `.game-message` 文本，加上模拟器自己判定的死局结论 |
| 新开一局 | 点 `.restart-button`；胜利后点 `.keep-playing-button` 继续 |
| 走一步 | `ArrowUp` / `ArrowRight` / `ArrowDown` / `ArrowLeft` |

读取时会等两份一致的快照，棋盘本身取自页面持久化的 `gameState`，取不到才退回渲染出的方块。
这个顺序很重要：游戏同步写入 `gameState`，而方块要晚一帧才画出来，
所以刚移动过的方块会有一帧还挂着旧的位置 class。如果把画出来的方块当主数据源，
在负载高到一帧超过读取间隔的机器上，偶尔会报出移动前的位置 —— 而分数已经更新了。
方块仍然留在流程里做交叉核对：一个合并后的格子有三个元素，`game_client` 在那里拒绝猜测；
两个数据源不一致时，会在这步记录 `dom_behind_model`。

差分测试已验证：三个带种子的对局中连续 135 步，每个观测到的棋盘都等于参考滑动结果
加上恰好一个新生成的 2 或 4，分数增量也精确吻合。

有两处 harness 侧的行为需要说明，因为它们从游戏本身看不出来。

**帧回退。** 游戏在 `requestAnimationFrame` 里构造它的 `GameManager`，也在里面渲染每一步，
所以一个 headed 窗口如果合成器停止绘制，游戏会彻底冻住 —— 连第一对方块都发不出来。
因此浏览器会话包了一层 `requestAnimationFrame`，带一个定时器回退，只在真实帧迟到超过
250 ms 时才触发。可见窗口的行为和以前完全一样；被遮挡的窗口会继续玩下去，而不是悄悄卡死。
这不改变任何游戏规则，也不改变任何随机抽取。

**重载时没有白闪。** Chromium 在文档还没有任何样式的那一刻会绘制自己的默认背景 —— 白色，
而每局都是一次全新导航。会话通过 CDP 把这个默认值设为游戏自己的 `#faf8ef`，
于是重载是看不见的，而不是一道白闪。这是纯外观、尽力而为的做法：
不支持该覆盖的浏览器就继续闪。

**不去截取别人正在看的窗口。** 对可见窗口调用 `page.screenshot()` 会迫使 surface 重新光栅化，
整个窗口都会闪；每步前后各来一次，让闪烁看起来像游戏的一部分，还每步多花约 100 ms。
演示入口在默认面板和复古模式下都明确关闭截图；`--shots` 只为面板模式开启镜像。
共享 runner 的其他调用者仍默认对隐藏窗口做镜像，可见窗口默认不截图。

**页面加载串行化。** 2048 页面由 `python3 -m http.server` 伺服，它说 HTTP/1.0：
每个文件一条连接，响应写完就关闭，listen backlog 只有 5。一个页面需要十几个文件，
所以多个浏览器同时加载会挤爆 backlog，页面到达时*缺少部分脚本* ——
`net::ERR_CONNECTION_RESET`、没有方块，也没有游戏自己的报错。因此页面加载在进程范围内
串行化，加载丢了资源的会被立刻发现并重新加载，而不是干等。做到这一点后，
八个并发会话开局零失败；不做的话，大约三分之一的并发对局会中止。

---

## 2. 唯一的变量

每个模式发送同一段 `instructions` 块和同样的四个候选标签。只有 `state` 和 `criteria`
不同。

```text
goal:  Avoid game over and reach the highest tile possible.
rules: 2048 rules: a move slides every tile toward that edge. Two tiles of equal value
       that collide merge into one tile of their sum, and the score increases by that sum.
       After a move that changes the board, one new tile of value 2 or 4 appears in an
       empty cell. The game is over when no direction changes the board.
```

四个方向永远都会给出，包括非法的。合法性是 harness 可能给、也可能不给的信息 ——
正因如此，invalid-move 率才是一个真实的测量值，而不是恒定的零。

### 模式 1 — `jev-board`

```text
Current 2048 board:

2 4 8 16
0 2 4 8
0 0 2 4
0 0 0 2

Choose one move:

UP
DOWN
LEFT
RIGHT

Goal:
Avoid game over and reach the highest tile possible.
```

### 模式 2 — `jev-state`

```text
Board:
2 4 8 16
0 2 4 8
0 0 2 4
0 0 0 2

Score: 4820
Max tile: 16
Empty cells: 6
Last move: DOWN
Recent moves:
DOWN, LEFT, DOWN, RIGHT, DOWN
Step: 183
Recent invalid moves: RIGHT x2
Repeated move pattern: no
```

### 模式 3 — `jev-history`

```text
Board:
2 4 8 16
0 2 4 8
0 0 2 4
0 0 0 2

Recent actions:
LEFT, RIGHT, LEFT, RIGHT, LEFT, RIGHT, DOWN, UP, DOWN, LEFT, DOWN, RIGHT, DOWN

Recent board states:
  1. hash=a1b2c3d4e5f6 score=4200 max=16 empty=7

Current board pattern seen before: 3 times
Recent action pattern: UP, DOWN, LEFT, DOWN, RIGHT, DOWN
Invalid RIGHT attempts recently: 2
```

history 模式只陈述事实，到此为止。它从不说遇到重复该怎么办。

### 模式 4 — `jev-features`

harness 对每个方向做一步前瞻模拟，并报告它产出的棋盘的测量值。只有一层：
没有两步前瞻，没有搜索，没有 rollout。

```text
DOWN:
  valid: true
  score_gain: 0
  merge_count: 0
  empty_cells_after: 6
  max_tile_after: 16
  max_tile_in_corner: true
  corner_preserved: true
  monotonicity: 1.0
  smoothness: -6.0
  changed_cells: 10
  mobility: 3
  board_entropy: 1.846
```

特征定义（全部确定性，全部作用在滑动后的棋盘上，新方块从不猜测）：

* `monotonicity` ∈ [0, 1] —— 对每一行和每一列，最好的单向连续段除以该线的总变化量。
  1.0 表示每条线都朝一个方向走。
* `smoothness` ≤ 0 —— 相邻非空方块之间 `|log2 差值|` 总和的负值。
* `mobility` —— 还有多少个方向能改变棋盘。
* `board_entropy` —— 方块数值分布的香农熵，单位 bit。
* `corner_preserved` / `max_tile_in_corner` —— 最大方块是否在角上。
  只有**唯一**的最大方块才算：开局棋盘上有好几个 2 和 4，随便挑一个叫「大方块」，
  等于凭空发明一种玩家还没开始的守角策略。
* `changed_cells` —— 与移动前棋盘不同的格子数。

### 模式 5 — `jev-state-history`

模式 2 的块后面接模式 3 的块，其他什么都不改。同样两个块，同样顺序，没有额外建议：

```text
Score: 4820
Max tile: 16
Empty cells: 6
Last move: DOWN
Recent moves:
DOWN, LEFT, DOWN, RIGHT, DOWN
Step: 183
Recent invalid moves: RIGHT x1
Repeated move pattern: no

Recent actions:
LEFT, RIGHT, LEFT, RIGHT, LEFT, RIGHT, DOWN

Recent board states:
  1. hash=a1b2c3d4e5f6 score=4200 max=16 empty=7

Current board pattern seen before: 3 times
Recent action pattern: RIGHT, LEFT, RIGHT, LEFT, RIGHT, DOWN
```

---

## 3. 基线

| 模式 | 规则 |
|---|---|
| `random` | 在合法方向上均匀随机，用自己的带种子生成器 |
| `greedy` | 取立刻的 `score_gain` 最大者；并列时选空格更多，再按固定顺序 |
| `heuristic` | 对向前一步的棋盘做手写评估后取 argmax |

heuristic 使用 nneonneo 公开的权重：空格（2.7）、单调性（1.0）、平滑度（0.1），
另外加了三项：`log2(最大方块)` 的角落奖励、移动后每个可用合并 0.6、每个合法方向 1.0。
这些权重没有在本 benchmark 上调过，而且对任何 jev 模式都不可见。

三个基线都只会选合法方向，所以它们的 invalid-move 率按构造就是零。

---

## 4. 谁决定什么

harness 可以读棋盘、保存历史、计算确定性统计、模拟一层、检测循环和失败、写日志、按方向键。

harness 不可以选择移动。没有任何代码路径会把一个 failure tag、一个启发式分数或一次循环检测
变成方向。tag 只是记录在赚到它的那一步旁边，别的什么都不做。当模型的回答无法通过校验时，
这局会带着原因记为 `aborted` —— 绝不会拿一个替代移动去补上。

---

## 5. 可复现性

`benchmark.py --seed 123` 和 `run.py --seed 123` 给出相同的生成序列。

游戏用 `Math.random` 生成方块，每个新方块抽两次（先抽数值，再抽格子）。
浏览器会话会注入一个 init script，把 `Math.random` 换成一个带种子的确定性流，
种子从页面自己的 query string 里读：

```js
const raw = new URLSearchParams(location.search).get("seed");
let state = (Number(raw) >>> 0) || 1;
Math.random = () => { /* mulberry32 */ };
```

每局都导航到 `index.html?seed=N`，同一个 init script 还会在 document start 时删掉页面保存
的对局，所以每次加载都从流的开头发出全新的一对方块。于是一整局就是
`(seed, action sequence)` 的函数。

已验证：同一个种子产出**逐字节相同的棋盘、动作和分数**：(a) 通过 CDP 连上的真实 Chrome
和全新的 headless Chromium，跑十步；(b) `--workers 1` 和 `--workers 5`，五整局逐步对比。

**限制，直说。** 抽取流是按位置走的，所以两个策略只有在生成的方块数相同时才对得上：

* 非法移动不生成任何方块，所以浪费步数的策略会逐渐和没有浪费的错位；
* 格子是按 `floor(r × available_cells)` 抽的，所以即使生成序号相同，
  只要两个棋盘的空格集合不同，选中的格子也可能不同。

因此同一个种子意味着「同样的随机流、同样的顺序」，而不是「每一步之后都是同样的棋盘」。
这是在不修改游戏自己生成代码的前提下能给出的最强保证，而本项目不做那种修改。
在同一个模式内，各局相互独立：第 `i` 局用 `seed + i`，`--workers N` 不改变任何结果。

---

## 6. 日志

每执行一步写一行 JSONL，边写边 flush。

```json
{
  "game_id": 12, "seed": 123, "step": 87, "mode": "jev-features",
  "board_before": [[2,4,8,16],[0,2,4,8],[0,0,2,4],[0,0,0,2]],
  "board_after":  [[0,0,0,16],[0,0,8,8],[0,4,4,4],[2,2,2,2]],
  "action": "down", "action_valid": true,
  "score_before": 1828, "score_after": 1836, "score_gain": 8, "score_gain_expected": 8,
  "max_tile": 256, "empty_cells": 5, "empty_cells_after": 6,
  "latency_ms": 43.0, "step_wall_ms": 78.2, "read_ms": 24.0,
  "recent_moves": ["down","left","down","right","down"],
  "board_hash": "0fcb3b167010", "state_hash": "9f2c1a77b3e5",
  "largest_corner": "tr", "largest_corner_after": null,
  "monotonicity": 0.61, "monotonicity_after": 0.88,
  "page_reacted": true,
  "decision_source": "jev-features",
  "jev_probabilities": {"up":0.08,"down":0.67,"left":0.19,"right":0.06},
  "jev_confidence": 0.41, "jev_attempts": 1, "jev_model": "jev-1.13.0",
  "jev_usage": {"input_tokens": 948, "output_tokens": 45},
  "prompt_preview": "...", "request_state": {"board": [[...]]},
  "features_after": {"up": {...}, "down": {...}, "left": {...}, "right": {...}},
  "failure_tags": []
}
```

`board_hash` 是精确局面；`state_hash` 是同一棋盘在八种旋转和镜像下规范化后的值，
所以即使方块挪了位置，「又是这个形状」也能被检测出来。`action_valid` 是模拟器的判定；
`page_reacted` 是页面实际做了什么。两者不一致时，这一步会被打上 `harness_desync` ——
那意味着 harness 对游戏的判断错了，而不是 jev 错了。

§9 里结果背后的三份日志以 gzip 提交，因为那张表和 §10 里的每个数字都是从它们推导出来的：

```bash
cd jev-lab
for f in logs/*.jsonl.gz; do gzip -dc "$f" | head -1 | python3 -m json.tool; done   # one step
gzip -dc logs/jev.jsonl.gz | wc -l                                                  # 11050 steps
```

---

## 7. 失败检测器

八项检查，全都可以只从 harness 一侧读出来。它们标记步骤，从不改变步骤。

| 标记 | 触发条件 |
|---|---|
| `alternating_loop` | 两个方向交替 6 步（`L R L R L R`、`U D U D U D`） |
| `repeated_state` | 同一形状（允许旋转和镜像）出现 3 次，窗口为 20 步 |
| `invalid_repetition` | 10 步内两次选了同一个非法方向 |
| `corner_break` | 最大方块离开了它守了 5 步的角 |
| `space_collapse` | 空格单调下降 6+（10 步内），最终剩 2 个或更少 |
| `greedy_trap` | 得分 32+，跨 8 步，同时单调性下降 0.15+ 或空格减少 4+ |
| `decision_stagnation` | 连续 4 次同一个方向，既没得分也没有合法效果 |
| `harness_desync` | 模拟器的合法性判定和页面的反应不一致 |

每个检测器都验证过：在手工构造的、正好是那种失败的模式上会触发，在干净的对局上保持沉默。

---

## 8. 运行它

```bash
cd jev-lab

# watch it play, forever (see §0)
python demo.py

# one game, visible browser, live panel
python run.py --mode jev-board
python run.py --mode jev-features --speed 1
python run.py --mode jev-history --cdp http://127.0.0.1:9222   # drive an existing Chrome
python run.py --mode jev-board --games 0                       # until stopped

# batch
python benchmark.py --mode random     --games 100 --headless
python benchmark.py --mode greedy     --games 100 --headless
python benchmark.py --mode heuristic  --games 100 --headless
python benchmark.py --mode jev-board    --games 100 --headless
python benchmark.py --mode jev-state    --games 100 --headless
python benchmark.py --mode jev-history  --games 100 --headless
python benchmark.py --mode jev-features --games 100 --headless

# all seven required modes in one pass, six games at a time
python benchmark.py --mode random,greedy,heuristic,jev-board,jev-state,jev-history,jev-features \
  --games 100 --seed 123 --headless --workers 6

# report from whatever summaries exist
python analysis/report.py
```

浏览器**默认是 headed**；`--headless` 只用于批量。`--seed` 固定生成流，`--games N`
设定批量大小，`--workers N` 并发跑对局（每局有自己的 tab 和自己的种子，
所以结果不依赖这个参数）。

`run.py` 还会在 `http://127.0.0.1:8799` 上启动 dashboard，并在你自己的浏览器里打开它。
面板显示实时棋盘、步数、分数、最大方块、空格数、延迟、模型对每个方向的概率、选中的移动、
最近的移动、失败检查项，以及在 feature 模式下四个方向的特征。
Start / Pause / Step / Reset / 速度 1x·5x·20x·Max 都在，用来单步观察一次决策。

如果模型的概率拿不到（所有基线都是），面板会直说，而不是画一根柱子。面板上没有任何东西是编的。

---

## 9. 结果

三次运行，同样的种子、同样的页面、同样的 rules 文本、同样的模型。每局都导航到
`index.html?seed=N`，生成流只是 `N` 的函数。

```bash
cd jev-lab

# baselines: uncapped, they finish on their own
python benchmark.py --mode random,greedy,heuristic --games 20 \
  --seed 123 --headless --workers 6 --max-steps 2000 --tag baseline

# the model: capped at 300 moves, because it does not reliably finish
python benchmark.py --mode jev-board,jev-state,jev-history,jev-features --games 12 \
  --seed 123 --headless --workers 4 --max-steps 300 --tag jev
python benchmark.py --mode jev-state-history --games 12 \
  --seed 123 --headless --workers 4 --max-steps 300 --tag jev-sh

python analysis/report.py results/baseline_summary.json results/jev_summary.json \
  results/jev-sh_summary.json
```

| Mode | Games | Scored | Abort% | Avg Score | Median | P90 | Max | Avg Steps | Max Tile | 256% | 512% | 1024% | 2048% | 4096% | Invalid% | Loop% | Repeat% | Corner% | Collapse% | Trap% | Stagnation% | Avg Lat ms | P50 ms | P95 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| random | 20 | 20 | 0.0 | 1010.0 | 922.0 | 1636.0 | 2160 | 112.5 | 100.8 | 5.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.00% | 0.49% | 0.00% | 0.40% | 0.36% | 3.78% | 0.00% | 0.0 | 0.0 | 0.0 |
| greedy | 20 | 20 | 0.0 | 2984.8 | 3040.0 | 4252.4 | 4584 | 260.5 | 211.2 | 65.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.00% | 2.55% | 0.00% | 1.55% | 0.02% | 0.96% | 0.00% | 0.0 | 0.0 | 0.0 |
| heuristic | 20 | 20 | 0.0 | 5814.2 | 5870.0 | 7748.0 | 12152 | 404.2 | 460.8 | 100.0 | 60.0 | 10.0 | 0.0 | 0.0 | 0.00% | 1.77% | 0.00% | 1.81% | 0.01% | 2.13% | 0.00% | 0.0 | 0.0 | 0.0 |
| jev-board | 12 | 12 | 0.0 | 22.7 | 18.0 | 49.6 | 72 | 300.0 | 6.7 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 97.25% | 0.00% | 96.28% | 0.00% | 0.00% | 0.00% | 96.25% | 432.8 | 337.4 | 902.2 |
| jev-state | 12 | 12 | 0.0 | 593.7 | 606.0 | 802.4 | 1004 | 86.6 | 64.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 7.03% | 0.96% | 2.12% | 0.29% | 0.58% | 4.72% | 0.10% | 519.3 | 392.4 | 1152.0 |
| jev-history | 12 | 12 | 0.0 | 462.3 | 458.0 | 685.6 | 1036 | 261.7 | 53.3 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 74.20% | 0.06% | 68.41% | 0.16% | 0.00% | 0.57% | 60.86% | 487.2 | 362.6 | 967.6 |
| jev-features | 12 | 12 | 0.0 | 3781.7 | 4282.0 | 4555.6 | 4564 | 272.6 | 373.3 | 91.7 | 50.0 | 0.0 | 0.0 | 0.0 | 0.00% | 0.86% | 0.00% | 2.57% | 0.03% | 1.86% | 0.00% | 425.5 | 354.4 | 779.0 |
| jev-state-history | 12 | 12 | 0.0 | 779.7 | 736.0 | 1182.8 | 1356 | 171.3 | 77.3 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 44.55% | 0.83% | 38.33% | 0.39% | 0.15% | 2.38% | 28.26% | 558.6 | 366.8 | 1216.1 |

读这张表：

* **Games / Scored / Abort%** —— harness 中止的对局（连接掉线、页面从未加载）是被截断的对局，
  不是结果，所以它被排除在分数、步数和方块统计之外，只在这里计数。两次运行都是
  **0% 中止**。
* **Avg Steps** 对每一行 jev 封顶 300，对基线封顶 2000。这个上限从未卡住任何一局基线
  （最长的一局是 719 步）；它卡住了 `jev-board` 的 12/12、`jev-features` 的 7/12、
  `jev-history` 的 9/12 和 `jev-state-history` 的 3/12。因此被封顶的 jev 分数是**下界**，
  而 `jev-board` 的 300 步在多数对局里只做出最大方块为 4 的棋盘。
* **Invalid%** 是被游戏忽略的移动占比，由模拟器测量，并用页面的反应确认。
  每个基线按构造都是 0%。
* **Loop% / Repeat% / Corner%** 是失败检测器的逐步触发率；见 §7。
* **Latency** 是模型调用耗时。基线没有模型调用，所以按定义延迟为 0。

## 10. 关于 Jev，我们学到了什么？

十二个问题，答案来自上面的表和逐步日志。

**1. 只给棋盘，jev 能走多远？**
哪儿也去不了。`jev-board` 平均 **22.7**，最大方块 **6.7** —— 它通常根本没合并过任何东西。
**97.2%** 的移动是非法的，单一方向的最长连续段平均是 **300 步里的 293.8 步**。
多数对局里它选一个方向就再也不换：`LEFT 76%, RIGHT 24%, UP 0%, DOWN 0%`。
它比 random 差 44 倍。

**2. 显式状态有帮助吗？**
帮助巨大。`jev-state` 得分 **593.7**，提升 26 倍，非法率从 97.2% 降到 **7.0%**。
但 593.7 仍然**低于 random 的 1010**。把分数、空间、上一步和浪费了多少次尝试告诉它，
只是把一个不会玩的 agent 变成一个玩得很差的 agent。

**3. 历史能打破循环吗？**
不能 —— 它制造循环。规格里的 history 模式 `jev-history` 比 `jev-state` *更差*
（462.3 对 593.7），非法移动 **74.2%**，重复状态步数 **68.4%**。
用来解耦的条件 `jev-state-history` 把模式 2 的计数器固定住、在上面叠加历史：
分数升到 **779.7**，但非法率从 **7.0% → 44.6%**，重复状态率从 **2.1% → 38.3%**，
单一方向最长连续段从 **3.7 → 20.2**。历史让 jev 更重复，而不是更不重复。
更高的分数来自对局撑得更久（86.6 → 171.3 步）—— 而它撑得久，部分*正是因为*非法移动冻住了
棋盘。每个合法移动的得分也没有改善 —— `jev-state` 7.37、`jev-state-history` 8.21、
`jev-history` 6.85 —— 见第 7 问。

**4. 一层确定性特征提取能买到多少？**
它是唯一一个改变了 agent 种类的干预。`jev-features` 得分 **3781.7**：
是模式 2 的 **6.4 倍**，模式 1 的 **167 倍**。非法率降到 **0.0%**，
**91.7%** 的对局摸到 256，**50.0%** 摸到 512 —— 而其他每个 jev 模式这两项都是 0% 和 0%。

**5. jev 比 random 好吗？**
只有 `jev-features`（3781.7 对 1010）。`jev-state`（593.7）、`jev-history`（462.3）和
`jev-state-history`（779.7）全都低于 random，`jev-board`（22.7）远低于它。
五个条件里有三个输给了在合法移动上抛硬币。

**6. jev 比 greedy 好吗？**
好，在特征辅助的条件下：**3781.7 对 2984.8**，91.7% 的对局摸到 256（对 65.0%），
50.0% 摸到 512（对 0%）。其他 jev 模式都远远比不上 greedy。

**7. jev 离传统 heuristic 有多远？**
`jev-features` 达到 heuristic 平均分的 **65%**（3781.7 对 5814.2），考虑到步数上限，
这还是下界。更有意思的数字是每个合法移动的效率：

| 策略 | 每次合法移动得分 | 每局合法移动数 |
|---|---|---|
| heuristic | 14.38 | 404 |
| **jev-features** | **13.87** | 272 (capped) |
| greedy | 11.46 | 260 |
| random | 8.97 | 112 |
| jev-state-history | 8.21 | 95 |
| jev-state | 7.37 | 80 |
| jev-history | 6.85 | 68 |
| jev-board | 2.75 | 8 |

按每步算，特征辅助模式已经和 heuristic 同级。它做不到的是活下去：
heuristic 一局走 404 步，其中 10% 摸到 1024，而 jev 各模式要么步数耗尽，要么棋盘耗尽。
**差距在规划深度，不在单步质量。**

**8. jev 最容易在哪里失败？**
两个地方，日志里都看得到。一是它必须自己推断合法性时 —— 只给棋盘 97.2% 非法，
给一个 history 块 74.2% 非法，把历史加到 state 上 44.6% 非法。二是当上下文是一长串过去的
动作时，它把这当成一个要继续下去的模式：stagnation 检测器在 `jev-board` 的步数上触发
96.3%，`jev-history` 60.9%，`jev-state-history` 28.3%，而 `jev-state` 和 `jev-features`
分别是 0.1% 和 0.0%。

**9. jev 能用历史跳出局部最优吗？**
在这个实验里不能。历史每多给一份，都伴随着*更长*的固着：单一方向最长连续段，
只有计数器时 3.7 步，计数器加历史 20.2，历史取代计数器 125.0，只给棋盘 293.8。

**10. jev 擅长同时权衡多个局部指标吗？**
部分擅长，而且这个设计无法完全分离两种效应。特征块是唯一打赢了基线的条件，
它每步的效率也追平 heuristic —— 所以是的，它能足够好地权衡单调性、平滑度、空间和合并数
来玩。但同一个块里还带着 `valid`，而一旦把合法性写明，非法率就是 0.0%。
3781.7 里有多少来自指标权衡、有多少只是「有人告诉我哪些移动合法」，在这里分不开。
一个后续实验：从块里去掉 `valid`、保留其余部分，就能定论。

**11. 哪些信息值得让 harness 去算？**
按实测价值排序：**一层模拟**（相对只给棋盘是 167 倍，也是唯一打赢基线的条件）；
**显式计数器**（相对只给棋盘 26 倍，而且几乎免费）；最后是**动作历史**，
在这个长度上它比什么都不给还糟。harness 能做的最便宜的有用之事，就是告诉 jev
哪些移动合法。

**12. 更多上下文在哪里不再能替代搜索？**
大致在 greedy 这条线上。一层确定性评估就足以把 jev 从「不会玩」带到「按每步算，
和一层分数贪心一样好」。但不足以摸到 1024：除了特征辅助的那个，每个 jev 模式都没能越过
最大方块 128，而特征辅助的那个一半对局摸到 512，一局都没到 1024。heuristic 在 1024+ 上的
优势来自多走了三倍步数，那是局面的性质，不是任何单步的性质 ——
这个实验里再多的单步上下文也没能把它补回来。

---

## 11. 目录结构

```text
.                          上游 2048 游戏（index.html、js/、style/、meta/）
├── start.py               自动搭建项目环境并启动可见演示
├── readme.md              本文件              readme-cn.md  中文版
├── README-2048.md         上游游戏自己的 readme
├── game-test/             实验复用的既有控制代码：
│                            game_client.py    黑盒页面客户端（DOM + localStorage）
│                            reference2048.py  独立规则引擎，用作模拟器
│                            run_tests.py      本仓库自己的差分测试套件
├── jev-test/jev_client.py 加载 jev 自己的 model.py 的加载器，以及 .env 读取器
└── jev-lab/               实验本体
    ├── game/              adapter（页面控制）· state（观测）· simulator（规则）
    ├── jev/               client（唯一的决策层）· prompts（每个模式一个构造器）
    ├── players/           random · greedy · heuristic · jev_board · jev_state · jev_history ·
    │                      jev_features · jev_state_history
    ├── analysis/          features · failure_detector · metrics · report
    ├── runner/            browser · game_server · game_loop · interactive · benchmark
    ├── ui/                dashboard（server + page）
    ├── logs/              逐步 JSONL（gitignored）   results/  汇总 JSON + CSV
    ├── demo.py            看它自己玩，一直玩下去
    ├── run.py             跑一次，可见浏览器
    └── benchmark.py       批量，多模式
```

## 12. 环境要求

以下列出 lab 的依赖；安装位置、凭据管理和高级参数见本节末尾。

* **`playwright`** 加 Chromium（`playwright install chromium`）—— 浏览器会话。游戏是通过
  真实浏览器驱动的，没有更轻的路子。
* **`httpx[http2]`** —— 决策层调用 jev 自己 `model.py` 里的 `model.post_json`，而它构造的是
  `httpx.Client(http2=True)`。普通 `httpx` 能走到第一步，然后因为缺 `h2` 包抛 ImportError；
  完全没有 httpx 则是同一行上的 `ModuleNotFoundError`。
* **Jev 客户端源码** —— [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)。
  启动器自动下载固定版本并设置 `JEV_REPO`。如果直接调用 lab，请自行把 `JEV_REPO` 指向已有
  客户端目录；lab 复用它的 `post_json` 和 `validate_choice`，而不是重写请求路径。
* **`TYPESAFE_API_KEY`** —— 按 §0 提供。三个基线不需要 Key 或 Jev 客户端，但仍需 Python、
  Playwright 和 Chromium，不是零依赖运行。
* **2048 页面**在 `http://127.0.0.1:8792`。`demo.py` 会替你启动；见 §0。

启动器已在 macOS 实测：创建全新项目虚拟环境、安装依赖、下载 Chromium 和固定版本
Jev 客户端，并用这套安装完成真实的可见 Jev 对局。同时验证了复用已有浏览器缓存、
隐藏输入 Key、经确认保存到仓库外（权限 0600），以及后续启动不再安装、下载或询问 Key。
每局限 8 步的短对局会自动开始下一局；Ctrl-C 正常退出并关闭自行启动的服务器。
也验证了缺少 Key 和无效 `JEV_REPO` 的报错。Windows/Linux 步骤尚未经过实际运行验证。

依赖复用单独验证过，因为早期版本会把 Chromium 装进项目内的目录，导致机器上已有的浏览器
被重复下载一份。在机器缓存已存在且未设置 `PLAYWRIGHT_BROWSERS_PATH` 的情况下，启动器现在
会报告已有的依赖和浏览器、不下载任何东西，并完成真实对局。安装分支则通过把 `HOME` 指向空目录
来触发，此时 Playwright 的默认缓存为空，下载和启动检查会真实执行。

界面切换已在 macOS 实测：默认模式在后台 Chromium 中执行真实 Jev 决策，新面板实时显示，
无截图，暂停和单步可用；`--retro` 打开可见原版窗口，不启动面板服务，也不会受旧面板的
暂停指令影响。两种模式均在 Ctrl-C 后以退出码 0 退出并关闭自行启动的服务器。
`game-test/test_demo_controls.py` 覆盖了旧暂停指令导致复古模式停住的回归问题。

人工接管也对着真实对局验证过：切到手动后模型冻结 6 秒、状态为 `waiting for you`；
随后三次分开的方向键（每次都在上一次走完之后）产生且只产生三步，
记录为 `decision_source: human`，没有重复；切回自动后模型恢复。
面板上直接按方向键走的是同一条路径，模式按钮和按键提示会跟随状态变化。

面板语言也验证过：用分别上报 `zh-CN`、`zh-TW`、`en-US`、`fr-FR` 的浏览器加载，
前两者显示中文，后两者显示英文；统计项、检查项名称、特征标签和状态都随之切换，
英文面板保持不变。

### 安装与配置细节

- 启动器把缺失的依赖装进项目内的 `.venv/`，只在 `.jev/` 下载固定版本的 Jev 客户端。
  Chromium 使用 Playwright 自己的缓存目录（macOS 为 `~/Library/Caches/ms-playwright`，
  Linux 为 `~/.cache/ms-playwright`，Windows 为 `%USERPROFILE%\AppData\Local\ms-playwright`），
  已经存在时直接复用，不会因为别的项目装过就重复下载。
  不需要本地模型权重；下载 ZIP 的用户也不需要 Git。
- 依赖按最低版本判断而不是精确版本：已满足要求的安装会被复用并打印出来，不会被替换。
- 只搭建环境、不开始游戏：`python3 start.py --setup-only`；Windows 使用 `py -3 start.py --setup-only`。
  此命令不询问 Key，也不调用模型 API。
- 不修改系统 Python，不全局安装 pip 包，不自动执行 `sudo`。Linux 缺系统库时会提示管理员安装命令。
- 下载需访问 PyPI、GitHub 和 Playwright 浏览器分发站点；Jev 决策需访问 `api.typesafe.ai`。
  本地环境检查不验证远端 Key 是否有效或额度是否充足。
- 保存 Key 前会询问。macOS/Linux 默认保存在 `~/.config/jev-2048/credentials.env`，
  可通过 `XDG_CONFIG_HOME` 指定配置目录；Windows 使用 `%LOCALAPPDATA%\jev-2048\credentials.env`。
  提示中会显示实际路径。macOS/Linux 权限仅限文件所有者，Windows 遵循用户目录的 ACL 权限。
  不要分享这个明文文件，删除它即可取消保存。
- 凭据优先级：环境变量 `TYPESAFE_API_KEY`、已保存的 Key、`$JEV_REPO/.env`。
  未保存时，下次需重新输入或通过环境变量提供。
- 设置 `JEV_REPO` 可复用自己的客户端目录，设置 `PLAYWRIGHT_BROWSERS_PATH` 可复用浏览器缓存。
  启动器不会修改指定的 Jev 目录。
- `--shots` 可为新面板开启截图镜像，默认关闭；复古模式不截图。
- 自行管理环境时，可在 `jev-lab/` 运行 `demo.py`，默认新面板，`--retro` 启动复古界面。
  本文其他章节的 `python` 命令假定已激活安装依赖的环境，并位于 `jev-lab/`。
  `demo.py` 自动管理自己启动的游戏服务器，`run.py` 和 `benchmark.py` 需要先启动服务器。
