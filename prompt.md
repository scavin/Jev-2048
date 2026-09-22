请基于现有已经可以被程序成功控制的 2048 项目，以及 `browser-use/jev-ultrafast`，实现一个用于验证 Jev 能力边界的完整实验项目。

项目核心不是“做一个最强的 2048 AI”，而是验证一个问题：

同一个 Jev，当 Harness 暴露给它的状态不同，决策表现会发生什么变化？哪些问题 Jev 单步决策可以处理，哪些问题开始需要更强的规划、搜索或 System-2？

请直接开始实现，不要只输出方案。

项目必须满足以下目标。

第一，复用现有 2048。

现有 2048 已经可以被成功控制，不要重新实现完整游戏。

先阅读现有代码，确认：

- 如何获取 4×4 棋盘状态
- 如何读取当前 score
- 如何判断 Game Over
- 如何执行 UP / DOWN / LEFT / RIGHT
- 如何重新开始一局
- 当前是通过 DOM、键盘事件、按钮还是其他方式控制

优先使用现有控制方式。

第二，使用 Jev 做唯一 AI 决策层。

2048 每一步只允许 Jev 在以下四个动作中选择：

- UP
- DOWN
- LEFT
- RIGHT

不要使用 GPT、Claude、Gemini 或其他通用大模型 API 辅助判断。

`jev-ultrafast` 或现有浏览器控制代码负责：

- 获取页面状态
- 执行动作
- 等待页面更新

Jev 只负责：

“在当前 Harness 提供的状态下，下一步应该选择哪个方向？”

不要让 Jev 直接执行任意代码、生成 JavaScript、生成 selector 或操作系统命令。

第三，浏览器默认必须可见。

单局运行和演示模式必须默认使用 headed / visible browser。

启动项目后，人类应该可以直接看到：

- 2048 浏览器窗口
- 每一步实际操作
- 棋盘变化
- 分数变化
- Jev 的当前选择

批量 benchmark 可以通过参数切换为 headless。

例如：

```bash
python run.py --mode jev-board
python benchmark.py --mode jev-board --games 100 --headless
```

第四，整个项目围绕 Harness 状态设计做实验。

必须实现以下 Jev 模式。

模式 1：Jev Board Only

Harness 只提供当前棋盘，以及最基本目标。

示例：

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

不要提供：

- 历史动作
- 启发式评分
- 空格数
- merge 数
- corner bonus
- monotonicity
- 下一步模拟结果

这个模式用于测：

“Jev 只看到当前棋盘时，能做到什么程度？”

模式 2：Jev + Explicit State

在原始棋盘基础上，增加 Harness 中明确维护的当前状态。

至少包括：

- score
- max_tile
- empty_cells
- last_move
- 最近若干步动作
- 当前 step
- 最近是否出现无效动作
- 最近是否出现重复动作模式

例如：

```text
Board:
...

Score: 4820
Max tile: 256
Empty cells: 5
Last move: DOWN
Recent moves:
DOWN, LEFT, DOWN, RIGHT, DOWN

Choose:
UP
DOWN
LEFT
RIGHT
```

不要提前模拟四个方向的结果。

这个模式用于验证：

“仅仅增加显式状态和有限历史，是否能改善 Jev 的表现？”

模式 3：Jev + History

这个模式重点测试历史信息是否能帮助 Jev 避免局部循环。

除了当前棋盘外，提供：

- 最近 8～16 步动作
- 最近若干棋盘状态摘要
- 某个局面最近出现次数
- 最近动作模式
- 最近无效动作次数

例如：

```text
Recent actions:
LEFT, RIGHT, LEFT, RIGHT, LEFT, RIGHT

Repeated board pattern detected: 3 times
Invalid RIGHT attempts recently: 2
```

但不要告诉 Jev应该怎么处理。

让 Jev自己根据这些状态进行 Choice。

这个模式主要验证：

“Jev 能否真正利用历史，而不是反复做同一个局部判断？”

模式 4：Jev + One-Step Features

这个模式最符合 Harness + Jev 的设计理念。

由确定性程序先模拟四个方向执行一步后的结果，但只允许看一步未来。

对每个方向计算：

- valid
- score_gain
- merge_count
- empty_cells_after
- max_tile_after
- max_tile_in_corner
- corner_preserved
- monotonicity
- smoothness
- changed_cells
- mobility
- board_entropy 或类似可选指标

例如：

```text
UP:
valid: true
score_gain: 8
merge_count: 1
empty_cells_after: 4
max_tile_after: 256
max_tile_in_corner: false
corner_preserved: false
monotonicity: 0.61
smoothness: -18

DOWN:
valid: true
score_gain: 0
merge_count: 0
empty_cells_after: 6
max_tile_after: 256
max_tile_in_corner: true
corner_preserved: true
monotonicity: 0.88
smoothness: -9
```

然后让 Jev 在四个候选动作中做 Choice。

禁止：

- 两步以上 lookahead
- BFS
- DFS
- A*
- Expectimax
- Monte Carlo Tree Search
- rollout
- 外部规划器

这个模式用于验证：

“当 Harness 把确定性计算做完后，Jev 是否适合做高频多指标权衡？”

第五，加入传统对照组。

至少实现：

1. Random

从合法动作中随机选择。

2. Greedy

选择当前 score_gain 最大的动作。

3. Heuristic

使用传统确定性 2048 启发式评分。

建议综合：

- empty cells
- monotonicity
- smoothness
- corner bonus
- merge potential
- mobility

Heuristic 不使用 Jev。

这些基线用于回答：

- Jev 是否优于随机
- Jev 是否优于简单 greedy
- Jev 是否能接近传统 heuristic

第六，统一随机性。

2048 新数字出现的位置和数值会影响实验。

为了公平比较，必须实现可复现的 random seed。

尽量做到：

同一个 seed 下，不同策略面对相同的随机数字序列。

如果由于不同动作导致空格位置不同，不能做到完全相同，请在 README 中说明具体实现方式和限制。

benchmark 必须支持：

```bash
--seed 123
--games 100
```

第七，详细记录每一步。

每一步至少保存：

- game_id
- seed
- step
- mode
- board_before
- action
- action_valid
- Jev probabilities / scores，如果 API 能返回
- board_after
- score_before
- score_gain
- score_after
- max_tile
- empty_cells
- latency_ms
- recent_moves
- board_hash
- failure_tags

保存为 JSONL。

示例：

```json
{
  "game_id": 12,
  "seed": 123,
  "step": 87,
  "mode": "jev-features",
  "board_before": [
    [2,4,8,16],
    [0,2,4,8],
    [0,0,2,4],
    [0,0,0,2]
  ],
  "action": "DOWN",
  "action_valid": true,
  "score_gain": 8,
  "score_after": 1836,
  "max_tile": 256,
  "empty_cells": 5,
  "latency_ms": 43,
  "failure_tags": []
}
```

第八，自动检测 Jev 的失败模式。

实现 failure detector。

至少检测以下情况。

1. Alternating Move Loop

例如：

LEFT → RIGHT → LEFT → RIGHT

或者：

UP → DOWN → UP → DOWN

连续重复超过阈值。

2. Repeated State

最近 N 步出现相同或等价 board hash。

3. Invalid Move Repetition

同一个无效方向被重复选择。

4. Corner Break

最大 tile 长时间在角落后，被某一步主动移出角落。

5. Space Collapse

短时间内 empty_cells 明显连续下降并最终 Game Over。

6. Greedy Trap

短时间连续获得 score_gain，但棋盘结构明显恶化。

7. Decision Stagnation

Jev 在近似相同状态下持续选择相同动作，即使已经多次失败。

这些 detector 只负责记录和标记。

不要自动修正 Jev 的选择。

第九，增加可视化实验面板。

需要提供一个适合录屏的可视化页面。

左侧：

真实 2048 游戏。

右侧显示：

```text
Mode:
Jev Board Only

Step:
183

Score:
7280

Max Tile:
512

Empty Cells:
4

Latency:
32 ms
```

再显示：

```text
Jev Decision

UP      0.08
DOWN    0.67
LEFT    0.19
RIGHT   0.06

Chosen:
DOWN
```

如果 API 只返回部分概率信息，则显示实际可获得的数据，不要伪造。

还要显示：

```text
Recent Moves:
↓ ↓ ← ↓ → ↓

Failure Detection:
Loop: No
Corner Break: No
Repeated State: Yes
```

如果当前模式是 Feature Assisted，还显示四个方向的特征。

例如：

```text
DOWN
empty: 6
merge: 2
corner: yes
mono: 0.88
```

第十，支持实时控制。

UI 至少提供：

- Start
- Pause
- Step
- Reset
- Speed

Speed 可以支持：

- 1x
- 5x
- 20x
- Max

Step 模式下：

每次点击只允许 Jev 完成一次决策和一次实际移动。

这样可以逐步观察 Jev 为什么做出这个 Choice。

第十一，提供 benchmark runner。

支持：

```bash
python benchmark.py --mode random --games 100
python benchmark.py --mode greedy --games 100
python benchmark.py --mode heuristic --games 100
python benchmark.py --mode jev-board --games 100
python benchmark.py --mode jev-state --games 100
python benchmark.py --mode jev-history --games 100
python benchmark.py --mode jev-features --games 100
```

输出至少包括：

- games
- average score
- median score
- P90 score
- max score
- average steps
- median steps
- average max tile
- reached 256 %
- reached 512 %
- reached 1024 %
- reached 2048 %
- reached 4096 %
- invalid move rate
- repeated-state rate
- loop rate
- corner-break rate
- average latency
- P50 latency
- P95 latency

同时导出：

- JSON
- CSV

第十二，最终生成对比报告。

生成一张类似这样的结果表：

```text
Mode               Avg Score   1024%   2048%   Loop%   Avg Latency

Random
Greedy
Heuristic
Jev Board
Jev + State
Jev + History
Jev + Features
```

不要在代码中预设谁应该赢。

让数据自己得出结果。

第十三，README 中明确说明实验问题。

项目 README 重点回答以下问题：

1. 只给 Jev 当前棋盘，它能玩到什么程度？
2. 增加显式状态后，是否明显改善？
3. 增加历史后，是否减少循环和重复错误？
4. 提供一步确定性特征后，表现提升多少？
5. Jev 是否优于 Random？
6. Jev 是否优于 Greedy？
7. Jev 和传统 Heuristic 差距多大？
8. Jev 在哪些状态下最容易失败？
9. Jev 是否能利用“历史状态”打破局部最优？
10. Jev 是否擅长权衡多个局部指标？
11. 哪类信息最值得由 Harness 提前计算？
12. 哪些问题开始明显需要搜索或 System-2？

README 中加入：

`What did we learn about Jev?`

但在实验实际完成前，不要预写结论。

第十四，严格区分 Harness 和 Jev 的职责。

Harness 可以：

- 读取棋盘
- 维护历史
- 计算确定性统计
- 模拟一步后的状态
- 检测 loop
- 记录日志
- 执行浏览器动作

Jev 负责：

- 在 Harness 暴露给它的候选动作和状态中做 Choice

禁止 Harness 偷偷替 Jev 做最终决策。

例如不要：

```python
if loop_detected:
    force_move = LEFT
```

可以把：

```text
loop_detected = true
```

提供给 Jev。

最终方向仍然必须由 Jev 选择。

第十五，代码结构。

尽量拆成：

```text
game/
  adapter
  state
  simulator

jev/
  client
  prompts
  schemas

players/
  random
  greedy
  heuristic
  jev_board
  jev_state
  jev_history
  jev_features

analysis/
  features
  failure_detector
  metrics

runner/
  interactive
  benchmark

ui/
  dashboard

logs/
results/
```

不要把所有逻辑塞进一个文件。

第十六，实施顺序。

请按以下顺序实际开发。

1. 阅读现有 2048 项目
2. 确认现有控制已经可靠工作
3. 接入 Jev，先完成 `Jev Board Only`
4. 在 visible browser 中实际跑完一局
5. 加入完整日志
6. 加入 `Jev + Explicit State`
7. 加入 `Jev + History`
8. 加入 `Jev + One-Step Features`
9. 加入 Random / Greedy / Heuristic
10. 加入 failure detector
11. 加入 benchmark
12. 加入可视化 dashboard
13. 跑一组小规模真实 benchmark
14. 检查数据是否正确
15. 完善 README

每完成一阶段都实际运行测试。

不要在没有运行验证的情况下假设功能正常。

第十七，最终项目定位。

最终成品应该可以被概括为：

“一个用 2048 实测 Jev 的 Harness 实验场。”

核心实验变量不是换模型。

模型始终是同一个 Jev。

我们只改变：

Harness 到底给 Jev 看什么。

最终目标是用实际数据回答：

“Jev 作为高速 System-1 单步决策器，当状态设计越来越完善时，能力可以被推到哪里；又从哪里开始，继续增加上下文已经无法替代真正的规划和搜索。”
