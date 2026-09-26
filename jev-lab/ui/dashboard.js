/* jev-lab dashboard: poll the runner's state, render it, and post control levels.
 *
 * Every field is guarded. A key that is absent, null or the wrong type renders as "--"
 * (or an explicit note), never as 0 and never as an invented bar.
 */

"use strict";

const MISSING = "--";
const DIRECTIONS = ["up", "down", "left", "right"];
const ARROWS = { up: "↑", down: "↓", left: "←", right: "→" };
const SPEEDS = ["1", "5", "20", "max"];
const FEATURE_KEYS = ["valid", "empty", "merge", "corner", "mono", "smooth"];
// A human waiting on the keyboard gets a fast board. A model that answers in ~350 ms does
// not, so the idle rate stays cheap instead of polling flat out forever.
const POLL_IDLE_MS = 250;
const POLL_MANUAL_MS = 60;
const CONTROL_POLL_TICKS = 20; // refresh the control file every ~2s as well

/* -- language ---------------------------------------------------------------
 *
 * The panel is a local page, so it follows the browser's own language list, the way any other
 * page would. English is the fallback for a browser that asks for neither. Keys are flat;
 * `t()` takes required strings and `tOr()` takes vocabulary that comes from the runner, where
 * an unknown value (a new check, a new status) must show through unchanged rather than vanish.
 */
const STRINGS = {
  en: {
    title: "jev-lab dashboard",
    connLost: "connection lost",
    waitingRunner: "waiting for a runner",
    liveAlt: "screenshot of the live 2048 window",
    boardAria: "board",
    noBoard: "no board yet",
    cardDecision: "Jev Decision",
    cardMoves: "Recent Moves",
    cardFailures: "Failure Detection",
    cardFeatures: "Move Features",
    chosenLabel: "Chosen: ",
    noProbabilities: "this policy does not return probabilities",
    badProbabilities: "probabilities are not in the expected shape",
    noMoves: "no moves yet",
    noChecks: "no checks reported",
    tagsPrefix: "tags: ",
    mirrorOff: "live board below · screenshot mirror off",
    noShotYet: "no screenshot yet",
    shotUnavailable: "screenshot unavailable",
    shotPrefix: "live.jpg · ",
    yes: "Yes",
    no: "No",
    featureYes: "yes",
    featureNo: "no",
    "stat.mode": "Mode",
    "stat.step": "Step",
    "stat.score": "Score",
    "stat.max_tile": "Max Tile",
    "stat.empty_cells": "Empty Cells",
    "stat.latency_ms": "Latency",
    speedLabel: "speed",
    optMax: "Max",
    btnManual: "Play myself",
    btnAuto: "Jev plays",
    btnStart: "Start",
    btnPause: "Pause",
    btnStep: "Step",
    btnReset: "Reset",
    hint: "arrow keys or W A S D",
    controlSpeed: "speed ",
    controlPending: "pending ",
    controlYouPlay: "you play",
  },
  zh: {
    title: "jev-lab 控制面板",
    connLost: "连接已断开",
    waitingRunner: "等待 runner 启动",
    liveAlt: "实时 2048 窗口截图",
    boardAria: "棋盘",
    noBoard: "还没有棋盘",
    cardDecision: "Jev 决策",
    cardMoves: "最近走子",
    cardFailures: "失败检测",
    cardFeatures: "走子特征",
    chosenLabel: "选择：",
    noProbabilities: "该策略不返回概率",
    badProbabilities: "概率数据格式异常",
    noMoves: "还没有走子",
    noChecks: "暂无检测结果",
    tagsPrefix: "标签：",
    mirrorOff: "下方为实时棋盘 · 未开启截图镜像",
    noShotYet: "暂无截图",
    shotUnavailable: "截图不可用",
    shotPrefix: "实时截图 · ",
    yes: "是",
    no: "否",
    featureYes: "是",
    featureNo: "否",
    "stat.mode": "模式",
    "stat.step": "步数",
    "stat.score": "分数",
    "stat.max_tile": "最大方块",
    "stat.empty_cells": "空格",
    "stat.latency_ms": "延迟",
    speedLabel: "速度",
    optMax: "最快",
    btnManual: "我来玩",
    btnAuto: "Jev 来玩",
    btnStart: "开始",
    btnPause: "暂停",
    btnStep: "单步",
    btnReset: "重置",
    hint: "方向键或 W A S D",
    controlSpeed: "速度 ",
    controlPending: "待执行 ",
    controlYouPlay: "你来操作",
    "dir.up": "上",
    "dir.down": "下",
    "dir.left": "左",
    "dir.right": "右",
    "status.starting": "启动中",
    "status.deciding": "决策中",
    "status.moving": "走子中",
    "status.paused": "已暂停",
    "status.waiting for you": "等待你操作",
    "status.game_over": "游戏结束",
    "status.max_steps": "已达步数上限",
    "status.aborted": "已中止",
    "status.unknown": "未知",
    "check.Loop": "循环",
    "check.Repeated State": "重复局面",
    "check.Invalid Repeat": "无效重复",
    "check.Corner Break": "最大块离角",
    "check.Space Collapse": "空间崩塌",
    "check.Greedy Trap": "贪心陷阱",
    "check.Stagnation": "停滞",
    "check.Harness Desync": "状态失步",
    "feature.valid": "合法",
    "feature.empty": "空格",
    "feature.merge": "合并",
    "feature.corner": "在角",
    "feature.mono": "单调",
    "feature.smooth": "平滑",
    "cmd.run": "运行",
    "cmd.pause": "暂停",
    "cmd.reset": "重置",
  },
};

const LANGUAGE = (() => {
  const wanted = (navigator.languages && navigator.languages.length)
    ? navigator.languages : [navigator.language];
  for (const tag of wanted) {
    const base = String(tag || "").toLowerCase().split("-")[0];
    if (STRINGS[base]) return base;
  }
  return "en";
})();
const T = STRINGS[LANGUAGE];
// Number and clock formatting follow the chosen language rather than a browser tag that may be
// one we cannot serve.
const LOCALE = LANGUAGE === "zh" ? "zh-CN" : "en-US";

function t(key) {
  const value = T[key];
  return typeof value === "string" ? value : STRINGS.en[key];
}

function tOr(key, fallback) {
  const value = T[key];
  return typeof value === "string" ? value : fallback;
}

function speedLabel(speed) {
  if (speed === "max") return t("optMax");
  return speed ? speed + "x" : MISSING;
}

function applyStatic() {
  document.documentElement.lang = LANGUAGE === "zh" ? "zh-Hans" : "en";
  document.title = t("title");
  for (const node of document.querySelectorAll("[data-i18n]")) {
    node.textContent = t(node.dataset.i18n);
  }
  for (const node of document.querySelectorAll("[data-i18n-alt]")) {
    node.alt = t(node.dataset.i18nAlt);
  }
  for (const node of document.querySelectorAll("[data-i18n-aria]")) {
    node.setAttribute("aria-label", t(node.dataset.i18nAria));
  }
}

const dom = {
  banner: document.getElementById("banner"),
  statusChip: document.getElementById("status-chip"),
  connNote: document.getElementById("conn-note"),
  board: document.getElementById("board"),
  live: document.getElementById("live"),
  liveNote: document.getElementById("live-note"),
  stats: document.getElementById("stats"),
  decision: document.getElementById("decision"),
  moves: document.getElementById("moves"),
  failures: document.getElementById("failures"),
  featuresCard: document.getElementById("features-card"),
  features: document.getElementById("features"),
  controlStatus: document.getElementById("control-status"),
  speed: document.getElementById("speed"),
  btnManual: document.getElementById("btn-manual"),
  btnAuto: document.getElementById("btn-auto"),
  humanHint: document.getElementById("human-hint"),
};

// A human plays with the same four directions the policies choose from.
const KEY_DIRECTIONS = {
  ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
  w: "up", s: "down", a: "left", d: "right",
};

const STAT_KEYS = ["mode", "step", "score", "max_tile", "empty_cells", "latency_ms"];

// Cached DOM so a 4Hz poll updates text instead of rebuilding the panel.
let statCells = null;
let boardCells = null;
let decisionShell = null;
let probRows = null;
let failureSignature = null;
let featureSignature = null;
let lastImageToken = null;
let pendingImageToken = null;
let pollTick = 0;
let polling = false;
let pollDelay = POLL_IDLE_MS;

/* -- small helpers ---------------------------------------------------------- */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function isObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asInteger(value) {
  const number = asNumber(value);
  return number === null ? null : Math.trunc(number);
}

function asString(value) {
  return typeof value === "string" && value.length ? value : null;
}

function fixed(value, digits, suffix) {
  const number = asNumber(value);
  return number === null ? MISSING : number.toFixed(digits) + (suffix || "");
}

function grouped(value) {
  const number = asInteger(value);
  return number === null ? MISSING : number.toLocaleString(LOCALE);
}

function put(node, text, missing) {
  node.textContent = text;
  node.classList.toggle("missing", Boolean(missing));
}

function directionLabel(direction) {
  const name = tOr("dir." + direction, direction);
  return name + (ARROWS[direction] ? " " + ARROWS[direction] : "");
}

/* -- board ------------------------------------------------------------------ */

function buildBoard() {
  dom.board.replaceChildren();
  boardCells = [];
  for (let index = 0; index < 16; index += 1) {
    const cell = el("div", "cell");
    boardCells.push(cell);
    dom.board.appendChild(cell);
  }
}

function renderBoard(board) {
  if (!Array.isArray(board)) {
    boardCells = null;
    dom.board.replaceChildren(el("div", "board-missing", t("noBoard")));
    return;
  }
  if (!boardCells) buildBoard();
  for (let row = 0; row < 4; row += 1) {
    const line = Array.isArray(board[row]) ? board[row] : [];
    for (let col = 0; col < 4; col += 1) {
      const cell = boardCells[row * 4 + col];
      const value = asInteger(line[col]);
      if (value === null) {
        cell.className = "cell";
        cell.textContent = MISSING;
      } else if (value === 0) {
        cell.className = "cell empty";
        cell.textContent = "";
      } else {
        cell.className = value >= 4096 ? "cell big" : "cell t" + value;
        cell.textContent = String(value);
      }
    }
  }
}

/* -- stats ------------------------------------------------------------------ */

function statValue(key, state) {
  switch (key) {
    case "mode": {
      const mode = asString(state.mode);
      return [mode || MISSING, !mode];
    }
    case "step":
      return [grouped(state.step), asInteger(state.step) === null];
    case "score":
      return [grouped(state.score), asInteger(state.score) === null];
    case "max_tile":
      return [grouped(state.max_tile), asInteger(state.max_tile) === null];
    case "empty_cells":
      return [grouped(state.empty_cells), asInteger(state.empty_cells) === null];
    case "latency_ms":
      return [fixed(state.latency_ms, 1, " ms"), asNumber(state.latency_ms) === null];
    default:
      return [MISSING, true];
  }
}

function buildStats() {
  dom.stats.replaceChildren();
  statCells = {};
  for (const key of STAT_KEYS) {
    const cell = el("div", "stat");
    cell.appendChild(el("div", "label", t("stat." + key)));
    const value = el("div", "value");
    cell.appendChild(value);
    statCells[key] = value;
    dom.stats.appendChild(cell);
  }
}

function renderStats(state) {
  if (!statCells) buildStats();
  for (const key of STAT_KEYS) {
    const [text, missing] = statValue(key, state);
    put(statCells[key], text, missing);
  }
}

/* -- jev decision ----------------------------------------------------------- */

function ensureDecisionShell() {
  if (decisionShell) return;
  const rows = el("div", "rows");
  dom.decision.replaceChildren(rows);
  const chosen = document.getElementById("chosen");
  chosen.replaceChildren(t("chosenLabel"), el("b", null, MISSING));
  decisionShell = { chosen: chosen.lastChild, rows };
  probRows = null;
}

function buildProbRows() {
  decisionShell.rows.replaceChildren();
  probRows = {};
  for (const direction of DIRECTIONS) {
    const row = el("div", "prob-row");
    const label = el("div", "dir", directionLabel(direction));
    const bar = el("div", "bar");
    const fill = el("span");
    bar.appendChild(fill);
    const number = el("div", "num");
    row.append(label, bar, number);
    probRows[direction] = { row, label, bar, fill, number };
    decisionShell.rows.appendChild(row);
  }
}

function renderDecision(state) {
  ensureDecisionShell();
  const chosen = asString(state.chosen);
  decisionShell.chosen.textContent = chosen ? directionLabel(chosen) : MISSING;

  const probabilities = state.probabilities;
  if (probabilities === null || probabilities === undefined) {
    probRows = null;
    decisionShell.rows.replaceChildren(
      el("div", "missing-note", t("noProbabilities")));
    return;
  }
  if (!isObject(probabilities)) {
    probRows = null;
    decisionShell.rows.replaceChildren(
      el("div", "missing-note", t("badProbabilities")));
    return;
  }
  if (!probRows) buildProbRows();
  for (const direction of DIRECTIONS) {
    const refs = probRows[direction];
    const value = asNumber(probabilities[direction]);
    const missing = value === null;
    refs.fill.style.width = (missing ? 0 : Math.max(0, Math.min(1, value)) * 100).toFixed(1) + "%";
    refs.bar.classList.toggle("chosen", direction === chosen);
    refs.label.classList.toggle("chosen", direction === chosen);
    put(refs.number, missing ? MISSING : value.toFixed(2), missing);
  }
}

/* -- recent moves ----------------------------------------------------------- */

function renderMoves(state) {
  const moves = Array.isArray(state.recent_moves) ? state.recent_moves : null;
  dom.moves.replaceChildren();
  if (!moves || moves.length === 0) {
    dom.moves.appendChild(el("div", "missing-note", t("noMoves")));
    return;
  }
  const names = moves.map((move) => (typeof move === "string" ? move : String(move)));
  dom.moves.appendChild(el("div", "arrows", names.map((name) => ARROWS[name] || "?").join(" ")));
  dom.moves.appendChild(el("div", "raw-names", names.join("  ")));
}

/* -- failure detection ------------------------------------------------------ */

function renderFailures(state) {
  const checks = isObject(state.checks) ? state.checks : null;
  const names = checks ? Object.keys(checks) : [];
  const signature = names.join("|");
  if (signature !== failureSignature) {
    failureSignature = signature;
    dom.failures.replaceChildren();
    if (names.length === 0) {
      dom.failures.appendChild(el("div", "missing-note", t("noChecks")));
    } else {
      for (const name of names) {
        const row = el("div", "check-row");
        row.dataset.check = name;
        row.appendChild(el("div", "name", tOr("check." + name, name)));
        row.appendChild(el("div", "flag", MISSING));
        dom.failures.appendChild(row);
      }
    }
  }
  for (const row of dom.failures.querySelectorAll(".check-row")) {
    const value = checks[row.dataset.check];
    const flag = row.querySelector(".flag");
    if (typeof value !== "boolean") {
      flag.textContent = MISSING;
      flag.className = "flag";
      row.classList.remove("flagged");
      continue;
    }
    flag.textContent = value ? t("yes") : t("no");
    flag.className = "flag " + (value ? "yes" : "no");
    row.classList.toggle("flagged", value);
  }
  const tags = Array.isArray(state.failure_tags) ? state.failure_tags : [];
  const existing = dom.failures.querySelector(".tags");
  if (tags.length === 0) {
    if (existing) existing.remove();
  } else if (existing) {
    existing.textContent = t("tagsPrefix") + tags.join(", ");
  } else {
    dom.failures.appendChild(el("div", "tags", t("tagsPrefix") + tags.join(", ")));
  }
}

/* -- features --------------------------------------------------------------- */

function featureCell(key, block) {
  // The second element is the CSS tone, kept separate from the text so a translated "yes"
  // still colours the cell.
  switch (key) {
    case "valid":
      return typeof block.valid === "boolean"
        ? [block.valid ? t("featureYes") : t("featureNo"), block.valid ? "yes" : "no"]
        : [MISSING, ""];
    case "empty":
      return [grouped(block.empty_cells_after), ""];
    case "merge":
      return [grouped(block.merge_count), ""];
    case "corner":
      return typeof block.max_tile_in_corner === "boolean"
        ? [block.max_tile_in_corner ? t("featureYes") : t("featureNo"),
           block.max_tile_in_corner ? "yes" : "no"]
        : [MISSING, ""];
    case "mono":
      return [fixed(block.monotonicity, 2), ""];
    case "smooth":
      return [fixed(block.smoothness, 2), ""];
    default:
      return [MISSING, ""];
  }
}

function renderFeatures(state) {
  const features = isObject(state.features) ? state.features : null;
  const present = features
    ? DIRECTIONS.filter((direction) => isObject(features[direction])
      && Object.keys(features[direction]).length > 0)
    : [];
  dom.featuresCard.hidden = present.length === 0;
  if (present.length === 0) {
    featureSignature = null;
    dom.features.replaceChildren();
    return;
  }
  const signature = present.join("|");
  if (signature !== featureSignature) {
    featureSignature = signature;
    dom.features.replaceChildren();
    const grid = el("div", "feature-grid");
    for (const direction of present) {
      const block = el("div", "feature");
      block.dataset.direction = direction;
      block.appendChild(el("h3", null, directionLabel(direction)));
      for (const key of FEATURE_KEYS) {
        const row = el("div", "kv");
        row.dataset.key = key;
        row.appendChild(el("span", "k", tOr("feature." + key, key)));
        row.appendChild(el("span", "v", MISSING));
        block.appendChild(row);
      }
      grid.appendChild(block);
    }
    dom.features.appendChild(grid);
  }
  for (const block of dom.features.querySelectorAll(".feature")) {
    const source = features[block.dataset.direction];
    for (const row of block.querySelectorAll(".kv")) {
      const key = row.dataset.key;
      const [text, tone] = featureCell(key, source);
      const node = row.querySelector(".v");
      node.textContent = text;
      node.className = "v" + (tone ? " " + tone : "");
    }
  }
}

/* -- header, screenshot, controls ------------------------------------------- */

function renderHeader(state, available) {
  const status = asString(state.status);
  dom.statusChip.textContent = status ? tOr("status." + status, status) : MISSING;
  // The attribute stays the runner's own word: the stylesheet keys off it.
  dom.statusChip.dataset.status = status || "unknown";

  if (!available) {
    const error = asString(state.error);
    dom.banner.textContent = error || t("waitingRunner");
    dom.banner.className = "banner";
    dom.banner.hidden = false;
    return;
  }
  const message = asString(state.message);
  dom.banner.textContent = message || "";
  dom.banner.className = "banner info";
  dom.banner.hidden = !message;
}

function renderScreenshot(state, available) {
  // The default dashboard draws the board from game state, without screenshot requests.
  if (available && state.shots === false) {
    lastImageToken = null;
    pendingImageToken = null;
    dom.live.hidden = true;
    dom.liveNote.textContent = t("mirrorOff");
    return;
  }
  const token = available ? String(state.updated_at ?? state.step ?? "state") : null;
  if (token === null) {
    lastImageToken = null;
    pendingImageToken = null;
    dom.live.hidden = true;
    dom.liveNote.textContent = t("noShotYet");
    return;
  }
  if (token === lastImageToken || token === pendingImageToken) return;

  // Decode the new frame off-screen and only then hand it to the visible <img>. Assigning
  // `src` directly blanks the pane for as long as the fetch and decode take, and at several
  // refreshes a second that blank reads as a flicker.
  const url = "/live.jpg?t=" + encodeURIComponent(token);
  const loader = new Image();
  pendingImageToken = token;
  loader.onload = () => {
    if (pendingImageToken === token) pendingImageToken = null;
    if (lastImageToken === token) return;   // a newer frame already won the race
    lastImageToken = token;
    dom.live.src = loader.src;
    dom.live.hidden = false;
    dom.liveNote.textContent =
      t("shotPrefix") + new Date().toLocaleTimeString(LOCALE, { hour12: false });
  };
  loader.onerror = () => {
    if (pendingImageToken === token) pendingImageToken = null;
  };
  loader.src = url;
}

dom.live.addEventListener("error", () => {
  dom.liveNote.textContent = t("shotUnavailable");
});

function applyManual(manual) {
  // Only a real boolean moves the panel: a missing key must not claim a mode.
  if (typeof manual !== "boolean") return;
  dom.btnManual.classList.toggle("btn-active", manual);
  dom.btnAuto.classList.toggle("btn-active", !manual);
  dom.humanHint.hidden = !manual;
  pollDelay = manual ? POLL_MANUAL_MS : POLL_IDLE_MS;
}

function renderControl(control) {
  if (!isObject(control) || control.available === false) {
    dom.controlStatus.textContent = MISSING;
    return;
  }
  const command = asString(control.command) || MISSING;
  const speed = asString(control.speed);
  const pending = asInteger(control.pending_steps);
  const parts = [tOr("cmd." + command, command), t("controlSpeed") + speedLabel(speed)];
  if (pending !== null && pending > 0) parts.push(t("controlPending") + pending);
  if (control.manual === true) parts.push(t("controlYouPlay"));
  dom.controlStatus.textContent = parts.join(" · ");
  if (speed && SPEEDS.indexOf(speed) >= 0) dom.speed.value = speed;
  // The command level is written immediately, so the panel answers a click at once; the
  // state poll then confirms what the runner actually did.
  applyManual(control.manual);
}

async function postControl(payload) {
  try {
    const response = await fetch("/api/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      dom.controlStatus.textContent = "rejected: " + (await response.text()).trim();
      return;
    }
    renderControl(await response.json());
  } catch (error) {
    dom.controlStatus.textContent = "control failed";
  }
}

async function fetchControl() {
  try {
    const response = await fetch("/api/control", { cache: "no-store" });
    renderControl(await response.json());
  } catch (error) {
    /* the state poll already reports a lost connection */
  }
}

/* -- polling ---------------------------------------------------------------- */

function renderState(state, available) {
  const source = available ? state : {};
  renderHeader(isObject(state) ? state : {}, available);
  renderStats(source);
  renderBoard(available ? source.board : null);
  renderDecision(source);
  renderMoves(source);
  renderFailures(source);
  renderFeatures(source);
  renderScreenshot(source, available);
  applyManual(available ? source.manual : undefined);
}

async function poll() {
  if (polling) return;
  polling = true;
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    const state = await response.json();
    const available = response.ok && isObject(state) && state.available !== false;
    renderState(state, available);
    dom.connNote.hidden = true;
    pollTick += 1;
    if (pollTick % CONTROL_POLL_TICKS === 0) fetchControl();
  } catch (error) {
    dom.connNote.hidden = false; // never blank the page on a failed poll
  } finally {
    polling = false;
  }
}

document.getElementById("btn-start").addEventListener("click", () => postControl({ command: "start" }));
document.getElementById("btn-pause").addEventListener("click", () => postControl({ command: "pause" }));
document.getElementById("btn-step").addEventListener("click", () => postControl({ command: "step" }));
document.getElementById("btn-reset").addEventListener("click", () => postControl({ command: "reset" }));
document.getElementById("btn-manual").addEventListener("click", () => postControl({ command: "manual" }));
document.getElementById("btn-auto").addEventListener("click", () => postControl({ command: "auto" }));
dom.speed.addEventListener("change", () => postControl({ speed: dom.speed.value }));

document.addEventListener("keydown", (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  const tag = event.target && event.target.tagName;
  if (tag === "SELECT" || tag === "INPUT" || tag === "TEXTAREA") return;
  const direction = KEY_DIRECTIONS[event.key];
  if (!direction) return;
  event.preventDefault(); // an arrow key would otherwise scroll the panel
  // The first keypress also switches the panel to manual, so a move is never swallowed
  // because the policy happened to still be driving.
  postControl({ direction });
});

applyStatic();
fetchControl();
(function schedule() {
  setTimeout(async () => {
    await poll();
    schedule();
  }, pollDelay);
})();
