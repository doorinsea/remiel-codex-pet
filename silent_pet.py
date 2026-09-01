# -*- coding: utf-8 -*-
"""
蕾米埃尔 Codex 桌宠（独立版，2026-08-08）

基于“桌宠公开版”全模型改造：
  - think：Codex 开始一轮任务（思考中）→ 播放 think 循环
  - happy：Codex 本轮完成 → 播放 happy 循环，并在宠物上方弹出
          微信风格白色气泡“爱思考先生/小姐，你的任务已经完成了~”（粉色不透明）
  - approval：Codex 征求权限（升级命令）→ 弹出粉色不透明审批窗口，
          显示命令与原因，可直接点“允许 / 总是允许 / 拒绝”，
          通过 UI 自动化把决定点回 Codex 应用的审批卡片
  - 单击（happy/气泡期间）：只收回气泡回到 silent，不打开任何窗口
  - 其余交互保留原模型：拖拽、左键双击收起、右键菜单、右键双击退出、
    键盘 2 秒内连击 8 次唤醒 work 状态

Codex 状态检测：轮询 ~/.codex/sessions 下最新的会话 JSONL，
  - task_started / user_message          → 思考中（think）
  - agent_message(phase=final_answer) / task_complete → 完成（happy + 气泡）
  - 只跟踪真实用户任务，忽略 Codex 内部自动审批评估线程（guardian）
  - 升级命令先观察 3 秒：approve for me 自动批准的不会弹审批窗

铁律（与公开版一致，改代码前必读）：
  1. 动画主循环 _animate 永远自我续动（root.after 调度自己），
     绝不依赖一次性定时器，否则中途点击会永久卡死。
  2. 后台线程绝不碰 Tk，一律 root.after(0, ...) 回主线程再更新界面。
  3. Tk 颜色只用十六进制字符串（如 "#FF99CC"），RGB 元组会抛 TclError。
  4. 打包必须用 Windows Python（WSL 里的 PyInstaller 只能出 Linux ELF）。
"""

import os
import sys
import json
import io
import time
import glob
import re
import threading
import subprocess
import ctypes
import importlib.util
import tkinter as tk
from tkinter import font as tkfont
from collections import deque
from datetime import datetime

from PIL import Image, ImageDraw, ImageTk
from pynput import keyboard


# ─────────────────────────── 路径与配置 ───────────────────────────

def _program_dir():
    """打包 exe 时返回 exe 所在目录；源码运行时返回脚本目录"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


PROGRAM_DIR = _program_dir()
ASSETS_DIR = os.path.join(PROGRAM_DIR, "素材")
MENU_ICON_DIR = os.path.join(ASSETS_DIR, "菜单图标")
LOG_FILE = os.path.join(PROGRAM_DIR, "_pet.log")
MUTEX_NAME = "CodexPet_Singleton_Mutex_V1"

PET_SIZE = 200          # 桌宠窗口边长（初始值，可缩放）
MIN_PET_SIZE = 120      # 缩放下限
MAX_PET_SIZE = 400      # 缩放上限

GIF_FILES = {
    "silent":     os.path.join(ASSETS_DIR, "silent.gif"),
    "afterclick": os.path.join(ASSETS_DIR, "afterclick.gif"),
    "work":       os.path.join(ASSETS_DIR, "work.gif"),
    "think":      os.path.join(ASSETS_DIR, "think.gif"),
    "happy":      os.path.join(ASSETS_DIR, "happy.gif"),
}

# 键盘连击唤醒（work 状态）
WORK_TRIGGER_COUNT = 8          # 2 秒内连击次数阈值
WORK_TRIGGER_WINDOW = 2.0       # 时间窗口（秒）
WORK_IDLE_TIMEOUT = 1.0         # 无敲击多久退出 work（秒）
WORK_IDLE_POLL_MS = 100         # idle 检测间隔（毫秒）

# Codex 会话监听
CODEX_HOME = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
CODEX_SESSIONS_DIR = os.environ.get("CODEX_PET_SESSIONS") or os.path.join(CODEX_HOME, "sessions")
CODEX_POLL_MS = 1000            # 轮询间隔（毫秒）
STALE_BUSY_SECONDS = 300        # “思考中”文件 5 分钟无新写入则视为陈旧，不计入 busy
APPROVAL_OBSERVE_SECONDS = 3.0  # 升级命令出现后的观察窗：3 秒内被自动批准则不弹审批窗
APPROVAL_DETECT_RETRIES = 5     # 探测不到审批卡片的次数上限；仍无卡片视为已自动批准，不再打扰

# 微信风格气泡
BUBBLE_TEXT = "爱思考先生/小姐，你的任务已经完成了~"
BUBBLE_BG = "#FFF4F9"           # 近白带粉，微信气泡底色
BUBBLE_BORDER = "#FFB6D1"       # 粉色描边
BUBBLE_TEXT_FG = "#8A3B5E"      # 深粉文字
BUBBLE_ALPHA = 1.0              # 不透明（可调 0.0~1.0）
BUBBLE_BODY_W = 230             # 气泡主体宽
BUBBLE_BODY_H = 54              # 气泡主体高
BUBBLE_TAIL_H = 12              # 朝下尾巴高
BUBBLE_TAIL_W = 18              # 朝下尾巴宽
BUBBLE_RADIUS = 14              # 圆角半径

# Codex 审批窗口（与气泡同风格：粉色不透明）
APPROVAL_ALPHA = 1.0            # 不透明（可调 0.0~1.0）
APPROVAL_BG = "#FFF4F9"         # 近白带粉，微信气泡底色
APPROVAL_BORDER = "#FFB6D1"     # 粉色描边
APPROVAL_TITLE_FG = "#8A3B5E"   # 标题深粉
APPROVAL_TEXT_FG = "#5A3A45"    # 正文深棕
APPROVAL_CMD_FG = "#7A4A5A"     # 命令文字色
APPROVAL_W = 400                # 窗口宽
APPROVAL_BODY_MAX_W = 356       # 正文最大宽度
APPROVAL_TAIL_H = 12            # 朝下尾巴高
APPROVAL_TAIL_W = 18            # 朝下尾巴宽
APPROVAL_BTN_ALLOW = "允许"
APPROVAL_BTN_ALWAYS = "总是允许"
APPROVAL_BTN_DENY = "拒绝"

HAPPY_HOLD_MS = 5000            # happy 完成后自动保持 5 秒，再决定回 think / silent

# 插件系统：plugins/ 目录下每个子文件夹 = 一个插件（manifest.json + 入口）
PLUGINS_DIR = os.path.join(PROGRAM_DIR, "plugins")
BALANCE_REFRESH_MS = 60000      # 余额徽章刷新间隔
FLASH_STEPS = ["#FFFFFF", "#FFF3F8", "#FFE0ED", "#FFD0E2"]  # 阶段转换白光渐变

CONFIG_FILE = os.environ.get("CODEX_PET_CONFIG") or os.path.join(PROGRAM_DIR, "config.json")


def load_config():
    """读取 config.json（本机配置），失败返回 {}"""
    cfg = {}
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                cfg = json.load(fh) or {}
    except Exception as e:
        log_msg(f"config.json 读取失败: {e}")
    return cfg


def save_config(updates):
    """合并写入 config.json（保留已有字段，如 api key / 档位阈值）"""
    cfg = load_config()
    cfg.update(updates)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        log_msg(f"config.json 写入失败: {e}")


def load_plugins():
    """扫描 plugins/ 目录并导入插件模块，返回 [{manifest, module, dir}]"""
    out = []
    try:
        if not os.path.isdir(PLUGINS_DIR):
            return out
        for name in sorted(os.listdir(PLUGINS_DIR)):
            pdir = os.path.join(PLUGINS_DIR, name)
            mfile = os.path.join(pdir, "manifest.json")
            if not os.path.isfile(mfile):
                continue
            try:
                with open(mfile, "r", encoding="utf-8") as fh:
                    manifest = json.load(fh)
                entry = manifest.get("entry", "main.py")
                spec = importlib.util.spec_from_file_location(
                    f"pet_plugin_{name}", os.path.join(pdir, entry))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                out.append({"manifest": manifest, "module": mod, "dir": pdir})
                log_msg(f"插件已加载: {manifest.get('name', name)}")
            except Exception as e:
                log_msg(f"插件加载失败 [{name}]: {e}")
    except Exception as e:
        log_msg(f"plugins 目录读取失败: {e}")
    return out


def _detect_codex_app_id():
    """自动探测 Codex 桌面应用的 AppID；找不到返回已知别名"""
    known = "OpenAI.Codex_2p2nqsd0c76g0!App"
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-StartApps | Where-Object { $_.Name -like '*Codex*' } "
             "| Sort-Object @{Expression={$_.Name -eq 'Codex'}} -Descending "
             "| Select-Object -First 1 -ExpandProperty AppID"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        line = (r.stdout or "").strip()
        if line:
            return line
    except Exception:
        pass
    return known


# ─────────────────────────── 工具函数 ───────────────────────────

def log_msg(msg):
    """写日志（桌宠无控制台，用文件定位问题）"""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def launch_app(path):
    """用系统关联方式启动程序，原生支持中文/特殊路径"""
    try:
        if not os.path.exists(path):
            log_msg(f"启动失败: 路径不存在 {path}")
            return False
        os.startfile(path)
        log_msg(f"已启动 {path}")
        return True
    except Exception as e:
        log_msg(f"启动异常 [{path}]: {e}")
        return False
# ─────────────────── Codex 会话监听（后台线程） ───────────────────

class CodexWatcher(threading.Thread):
    """增量跟踪 ~/.codex/sessions 下所有会话文件（支持多线并行）。

    行为：
      - 任意会话开始思考（task_started / user_message）→ on_busy
      - 任意会话完成一轮（final_answer / task_complete）→ on_done
      - 任意会话出现升级命令 → on_approval；出现结果 → on_approval_resolved

    只跟踪真实用户任务；Codex 内部自动审批评估线程（guardian，thread_source=
    subagent）不参与状态。升级命令出现后先观察 APPROVAL_OBSERVE_SECONDS 秒，
    期间若已自动批准（approve for me）则不弹审批窗；启动时历史未决审批不重放。

    回调在“后台线程”里触发，调用方必须用 root.after(0, ...) 转回主线程。
    """

    def __init__(self, sessions_dir, on_busy, on_done,
                 on_approval=None, on_approval_resolved=None,
                 poll_ms=CODEX_POLL_MS):
        super().__init__(daemon=True)
        self._sessions_dir = sessions_dir
        self._on_busy = on_busy
        self._on_done = on_done
        self._on_approval = on_approval
        self._on_approval_resolved = on_approval_resolved
        self._poll_ms = poll_ms
        self._states = {}          # path -> 会话状态
        self._internal_cache = {}  # path -> 是否内部评估线程（guardian）
        self._any_busy = False     # 是否任意会话正在思考
        self._first_scan_done = False  # 首轮扫描后是否已上报过初始 busy
        self._stop = False

    def stop(self):
        self._stop = True

    def is_any_busy(self):
        """主线程读取：当前是否还有会话在思考（决定 happy 5 秒后回 think 还是 silent）"""
        return self._any_busy

    def _all_files(self):
        try:
            pattern = os.path.join(self._sessions_dir, "**", "rollout-*.jsonl")
            return [p for p in glob.glob(pattern, recursive=True)
                    if os.path.isfile(p) and not self._is_internal(p)]
        except Exception:
            return []

    def _is_internal(self, path):
        """是否为 Codex 内部线程（自动审批评估 guardian），不参与桌宠状态"""
        if path in self._internal_cache:
            return self._internal_cache[path]
        internal = False
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                first = fh.readline()
            ev = json.loads(first)
            p = ev.get("payload") or {}
            if p.get("thread_source") == "subagent":
                internal = True
            src = p.get("source") or {}
            if (src.get("subagent") or {}).get("other") == "guardian":
                internal = True
            base = p.get("base_instructions") or {}
            if "You are judging one planned coding-agent action" in (base.get("text") or ""):
                internal = True
        except Exception:
            pass
        self._internal_cache[path] = internal
        return internal

    def _busy_fresh(self, path, st, now):
        """会话是否仍算“思考中”：busy=True 且文件 5 分钟内有新写入"""
        if st["busy"] is not True:
            return False
        try:
            return (now - os.path.getmtime(path)) < STALE_BUSY_SECONDS
        except Exception:
            return False

    def _approval_card_present(self):
        """探测 Codex 应用当前是否有真实审批卡片（approve/deny 按钮）。

        approve for me 模式下，已自动批准的命令不会出现卡片，探测不到就不弹
        桌宠审批窗，避免误弹。
        """
        script = os.path.join(PROGRAM_DIR, "uia_approval.ps1")
        try:
            r = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", script, "-Action", "detect"],
                capture_output=True, text=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            out = (r.stdout or "").strip()
            if out.startswith("FOUND:"):
                return True
            return False
        except Exception:
            return False

    def _event_state(self, ev):
        """单条事件 → True(思考中) / False(完成) / None(无关)"""
        try:
            t = ev.get("type")
            p = ev.get("payload") or {}
            pt = p.get("type")
            if t == "event_msg":
                if pt in ("task_started", "user_message"):
                    return True
                if pt in ("task_complete", "turn_aborted"):
                    return False
                if pt == "agent_message" and p.get("phase") == "final_answer":
                    return False
        except Exception:
            pass
        return None

    @staticmethod
    def _ts(ev):
        t = ev.get("timestamp") or ""
        try:
            return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    def _apply(self, st, lines):
        """把一批完整行并入某个会话的状态（不直接触发回调）"""
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            t = ev.get("type")
            p = ev.get("payload") or {}
            pt = p.get("type")
            s = self._event_state(ev)
            if s is not None:
                st["busy"] = s
            if t == "event_msg" and pt == "user_message":
                st["last_start_ts"] = max(st["last_start_ts"], self._ts(ev))
                st["graceful_done"] = False
            elif t == "event_msg" and pt == "task_started":
                st["last_start_ts"] = max(st["last_start_ts"], self._ts(ev))
                st["graceful_done"] = False
            elif t == "event_msg" and pt == "task_complete":
                st["graceful_done"] = True
            elif t == "event_msg" and pt == "turn_aborted":
                st["graceful_done"] = False
            elif t == "event_msg" and pt == "agent_message" and p.get("phase") == "final_answer":
                st["graceful_done"] = True
            if t == "response_item" and pt == "function_call":
                # 升级命令 = 需要用户审批
                try:
                    args = json.loads(p.get("arguments") or "")
                except Exception:
                    args = None
                if isinstance(args, dict) and args.get("sandbox_permissions") == "require_escalated":
                    call_id = p.get("call_id") or p.get("id")
                    if call_id:
                        st["pending"][call_id] = {
                            "args": args, "seen_ts": time.time(), "checks": 0,
                        }
            elif t == "response_item" and pt == "function_call_output":
                call_id = p.get("call_id")
                if call_id:
                    st["pending"].pop(call_id, None)

    def _scan(self, path):
        """新文件全量扫描：只建状态，不触发历史事件"""
        st = {"offset": 0, "busy": None, "prev_busy": None,
              "last_start_ts": 0.0, "graceful_done": False,
              "pending": {}, "notified": set()}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except Exception:
            return st
        self._apply(st, lines)
        st["offset"] = len(lines)
        st["prev_busy"] = st["busy"]
        return st

    def _read_new(self, path, st):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except Exception:
            return []
        total = len(lines)
        if total < st["offset"]:      # 文件被截断/轮转
            st["offset"] = 0
        new_lines = lines[st["offset"]:]
        st["offset"] = total
        return new_lines

    def _poll(self):
        files = self._all_files()
        # 移除已不存在的会话
        for p in list(self._states):
            if p not in files:
                del self._states[p]
        # 新增会话：全量扫描
        for p in files:
            if p not in self._states:
                self._states[p] = self._scan(p)

        started = False
        completed = False
        for p in files:
            st = self._states[p]
            self._apply(st, self._read_new(p, st))
            # 思考结束：本文件 busy True -> False
            if st["prev_busy"] is True and st["busy"] is False and st.get("graceful_done"):
                completed = True
            # 思考开始：busy False/None -> True
            if st["prev_busy"] is not True and st["busy"] is True:
                started = True
            st["prev_busy"] = st["busy"]

        # 只有“文件 5 分钟内有新写入”的思考才算 busy，陈旧会话（如中断/漏了完成标记）不算
        now = time.time()
        self._any_busy = any(
            self._busy_fresh(p, st, now)
            for p, st in self._states.items()
        )

        is_first_scan = not self._first_scan_done
        if is_first_scan:
            # 首轮扫描：若已有会话在思考，直接进入 think
            if self._any_busy and self._on_busy is not None:
                self._on_busy()
            self._first_scan_done = True
        else:
            if started and self._on_busy is not None:
                self._on_busy()
            if completed and self._on_done is not None:
                self._on_done()

        # 审批：仅增量弹窗。新升级命令先观察 APPROVAL_OBSERVE_SECONDS 秒，
        # 期间若自动批准（function_call_output 出现）则不打扰；观察窗过后再
        # 用 UIA 探测 Codex 应用里是否真有审批卡片，有才弹窗；
        # 首轮扫描的历史未决审批只标记、不重放弹窗。
        for p in files:
            st = self._states[p]
            for call_id, info in list(st["pending"].items()):
                if call_id not in st["notified"]:
                    if is_first_scan:
                        st["notified"].add(call_id)
                    elif now - info.get("seen_ts", 0.0) >= APPROVAL_OBSERVE_SECONDS:
                        if self._approval_card_present():
                            st["notified"].add(call_id)
                            if self._on_approval is not None:
                                self._on_approval(call_id, info.get("args", {}))
                        else:
                            info["checks"] = info.get("checks", 0) + 1
                            if info["checks"] >= APPROVAL_DETECT_RETRIES:
                                # 多次探测无卡片 → approve for me 已自动批准，不再打扰
                                st["notified"].add(call_id)
            for call_id in list(st["notified"]):
                if call_id not in st["pending"]:
                    st["notified"].discard(call_id)
                    if self._on_approval_resolved is not None:
                        self._on_approval_resolved(call_id)

    def run(self):
        while not self._stop:
            try:
                self._poll()
            except Exception:
                pass
            time.sleep(self._poll_ms / 1000.0)


# ─────────────────────────── 主程序 ───────────────────────────

class DesktopPet:
    def __init__(self):
        self._check_singleton()

        self.root = tk.Tk()
        self.root.title("蕾米埃尔 Codex 桌宠")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        # 透明键用黑色（与公开版一致，本机实测可靠）
        self.root.config(bg="black")
        self.root.attributes("-transparentcolor", "black")
        self._pet_size = PET_SIZE
        x0, y0 = self._initial_pos()
        self.root.geometry(f"{self._pet_size}x{self._pet_size}+{x0}+{y0}")

        self.canvas = tk.Canvas(self.root, width=self._pet_size, height=self._pet_size,
                                bg="black", highlightthickness=0)
        self.canvas.pack()

        # ── 动画数据 ──
        self._frames = {}
        self._delays = {}
        self._orig_frames = {}   # 原始 PIL 帧，缩放时重新渲染
        self._tk_refs = {}
        self._load_animations()
        first = (self._frames.get("silent") or self._frames.get("think")
                 or self._make_placeholder())[0]
        self._cur_photo = first
        self._img_id = self.canvas.create_image(self._pet_size // 2, self._pet_size // 2, image=first)
        self._draw_resize_handle()

        self._state = "silent"
        self._frame_idx = 0
        self._alive = True
        self._last_frame_time = time.time()   # 看门狗：最后一帧时间
        self._max_frame_gap = 5.0             # 超过 5 秒无帧更新则自动重启
        self._key_timestamps = deque()
        self._last_key_time = 0.0

        # ── 交互状态 ──
        self._press_pos = None
        self._press_time = 0.0
        self._dragging = False
        self._click_timer = None
        self._suppress_single = 0.0
        self._rb_timer = None
        self._codex_app_id = None    # 双击打开 Codex 用的 AppID（首次使用时探测）

        # ── 微信风格气泡 ──
        self._bubble_win = None
        self._bubble_cv = None

        # ── Codex 审批窗口 ──
        self._approval_win = None
        self._approval_cv = None
        self._approval_call_id = None
        self._happy_timer = None
        self._resizing = False      # 正在拖动右下角缩放把手
        self._render_pending = False
        self._render_after_id = None

        # ── 事件绑定 ──
        self.canvas.bind("<Button-1>", self._on_lb_press)
        self.canvas.bind("<B1-Motion>", self._on_lb_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_lb_release)
        self.canvas.bind("<Double-Button-1>", self._on_lb_double)
        self.canvas.bind("<Button-3>", self._on_rb_press)
        self.canvas.bind("<Double-Button-3>", self._on_rb_double)

        # ── 键盘全局监听：2 秒内连击 8 次 → work 状态 ──
        self._key_listener = keyboard.Listener(on_press=self._on_key)
        self._key_listener.daemon = True
        self._key_listener.start()

        # ── Codex 会话监听 ──
        self._watcher = CodexWatcher(
            CODEX_SESSIONS_DIR,
            on_busy=self._on_codex_busy_thread,
            on_done=self._on_codex_done_thread,
            on_approval=self._on_approval_thread,
            on_approval_resolved=self._on_approval_resolved_thread,
        )
        self._watcher.start()

        # ── 插件系统：加载 plugins/ 并启动余额类插件 ──
        self._plugins = load_plugins()
        self._balance_plugins = [p for p in self._plugins
                                 if p["manifest"].get("plugin_type") == "balance"]
        self._balance_api_key = ""
        self._balance_win = None
        self._balance_cv = None
        self._balance_photos = []
        self._balance_displayed = ""
        self._balance_last_ok = True
        self._balance_tiers = [20, 50, 80]
        self._balance_win_w = 220
        self._balance_win_h = 60
        self._balance_tier_key = None
        self._balance_refresh_id = None
        self._balance_drag_off = (0, 0)
        # ── 插件启停状态 + 本地控制台 ──
        self._enabled_plugins = self._load_enabled_plugins()
        self._console_port = 0
        self._pet_preview_cache = None
        self._plugin_preview_cache = {}
        self._plugin_offsets = {}   # 缩放过程中的插件偏移（pid -> (x, y)），松手后写回 config
        self._start_console_server()
        self._start_balance_plugins()

        log_msg(f"蕾米埃尔 Codex 桌宠启动 | 会话目录={CODEX_SESSIONS_DIR}")
        self._animate()
        self._check_work_idle()
        self.root.mainloop()

    # ───────────────────────── 基础 ─────────────────────────

    def _check_singleton(self):
        try:
            kernel32 = ctypes.windll.kernel32
            self._mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
            if kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
                log_msg("已有 Codex 桌宠实例在运行，本实例退出")
                sys.exit(0)
        except Exception:
            pass

    def _initial_pos(self):
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        except Exception:
            sw, sh = 1920, 1080
        return max(0, sw - self._pet_size - 80), max(0, sh - self._pet_size - 120)

    def _quit(self):
        self._alive = False
        try:
            self._watcher.stop()
        except Exception:
            pass
        self._cancel_happy_timer()
        self._approval_hide()
        self._close_balance()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _auto_restart(self):
        """检测到卡顿时自动重启自身"""
        try:
            self._alive = False
            if getattr(sys, 'frozen', False):
                cmd = [sys.executable]
            else:
                cmd = [sys.executable, os.path.abspath(__file__)]
            subprocess.Popen(cmd,
                             shell=False, cwd=os.path.dirname(os.path.abspath(__file__)))
        except Exception as e:
            log_msg(f"自动重启失败: {e}")
        try:
            self.root.destroy()
        except Exception:
            pass

    # ─────────────────── 键盘连击唤醒（work 状态） ───────────────────

    def _on_key(self, key):
        """pynput 后台线程回调：记录按键时间，2 秒内连击 8 次切 work"""
        now = time.time()
        self._last_key_time = now
        self._key_timestamps.append(now)
        cutoff = now - WORK_TRIGGER_WINDOW
        while self._key_timestamps and self._key_timestamps[0] < cutoff:
            self._key_timestamps.popleft()
        if len(self._key_timestamps) >= WORK_TRIGGER_COUNT:
            self._set_state("work")

    def _check_work_idle(self):
        """work 中 1 秒无敲击 → 回 silent（只操作普通属性 + after 调度）"""
        if not self._alive:
            return
        if self._state == "work":
            if time.time() - self._last_key_time >= WORK_IDLE_TIMEOUT:
                self._set_state("silent")
                self._key_timestamps.clear()
        try:
            self.root.after(WORK_IDLE_POLL_MS, self._check_work_idle)
        except Exception:
            pass

    # ───────────────────────── 动画 ─────────────────────────

    def _load_gif(self, path):
        """读取 GIF 全部帧（保留原始 PIL 帧），返回 (pil_frames, delays)"""
        frames, delays = [], []
        try:
            im = Image.open(path)
            while True:
                try:
                    frame = im.convert("RGBA")
                except Exception:
                    frame = im.convert("RGB")
                frames.append(frame.copy())
                delays.append(max(20, int(im.info.get("duration", 80) or 80)))
                im.seek(im.tell() + 1)
        except EOFError:
            pass
        except Exception as e:
            log_msg(f"GIF 读取异常 {path}: {e}")
        return frames, delays

    def _render_frame(self, im):
        """按当前桌宠尺寸渲染一帧 PhotoImage"""
        return ImageTk.PhotoImage(
            im.resize((self._pet_size, self._pet_size), Image.BILINEAR))

    def _make_placeholder(self):
        """GIF 全部缺失时的兜底：粉色圆球"""
        s = self._pet_size
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([int(s * 0.15), int(s * 0.15), int(s * 0.85), int(s * 0.85)],
                  fill=(255, 182, 212, 255))
        return [ImageTk.PhotoImage(img)]

    def _load_animations(self):
        for st, path in GIF_FILES.items():
            pil_frames, delays = self._load_gif(path)
            self._orig_frames[st] = pil_frames
            self._frames[st] = [self._render_frame(im) for im in pil_frames]
            self._delays[st] = delays
        # 兜底：缺失状态用 silent，silent 都没有则用占位图
        for st in GIF_FILES:
            if not self._frames.get(st):
                if self._frames.get("silent"):
                    self._frames[st] = self._frames["silent"]
                    self._delays[st] = self._delays["silent"]
                    self._orig_frames[st] = self._orig_frames.get("silent", [])
                else:
                    self._frames[st] = self._make_placeholder()
                    self._delays[st] = [100]
                    self._orig_frames[st] = []
        self._tk_refs = {st: fs for st, fs in self._frames.items()}
        log_msg("动画帧加载完成: " + ", ".join(f"{k}={len(v)}帧" for k, v in self._frames.items()))

    # ─────────────── 右下角缩放把手 ───────────────

    def _draw_resize_handle(self):
        """在桌宠右下角绘制常驻缩放把手（粉底圆角 + 斜线抓握图标）"""
        s = self._pet_size
        x0, y0 = s - 27, s - 27
        self._rounded_rect(self.canvas, x0, y0, x0 + 25, y0 + 25, 8,
                           fill="#FFB6D1", outline="#FFFFFF", width=1, tags="handle")
        for k in range(3):
            x1 = x0 + 5 + k * 4
            y1 = y0 + 22
            x2 = x0 + 20
            y2 = y0 + 5 + k * 4
            self.canvas.create_line(x1, y1, x2, y2, fill="#8A3B5E", width=1, tags="handle")

    def _redraw_resize_handle(self):
        try:
            self.canvas.delete("handle")
        except Exception:
            pass
        self._draw_resize_handle()

    def _resize_window_only(self, center=None):
        """拖动时先只改窗口大小，动画帧稍后异步重渲染，保证流畅。
        center 为缩放锚点（桌宠中心，屏幕坐标）；缺省时取当前窗口中心。"""
        try:
            if center is None:
                cx = self.root.winfo_x() + self.root.winfo_width() / 2.0
                cy = self.root.winfo_y() + self.root.winfo_height() / 2.0
            else:
                cx, cy = center
            new_x = int(cx - self._pet_size / 2.0)
            new_y = int(cy - self._pet_size / 2.0)
            self.canvas.config(width=self._pet_size, height=self._pet_size)
            self.root.geometry(f"{self._pet_size}x{self._pet_size}+{new_x}+{new_y}")
            self.canvas.coords(self._img_id, self._pet_size // 2, self._pet_size // 2)
            self._redraw_resize_handle()
            self._place_bubble()
            self._place_approval()
            self._place_balance()
        except Exception as e:
            log_msg(f"缩放窗口失败: {e}")

    def _schedule_render(self):
        if self._render_pending:
            return
        self._render_pending = True
        try:
            self._render_after_id = self.root.after(120, self._do_render_frames)
        except Exception:
            self._render_pending = False

    def _do_render_frames(self):
        self._render_pending = False
        self._render_after_id = None
        try:
            for st, imgs in self._orig_frames.items():
                self._frames[st] = [self._render_frame(im) for im in imgs]
            self._tk_refs = {st: fs for st, fs in self._frames.items()}
            frames = self._frames.get(self._state) or self._frames.get("silent") or []
            if frames:
                idx = self._frame_idx % len(frames)
                self._cur_photo = frames[idx]
                self.canvas.itemconfig(self._img_id, image=frames[idx])
        except Exception as e:
            log_msg(f"缩放重渲染失败: {e}")

    def _handle_resize_motion(self, e):
        try:
            rel_x = e.x_root - self.root.winfo_rootx()
            rel_y = e.y_root - self.root.winfo_rooty()
            new_size = max(MIN_PET_SIZE, min(MAX_PET_SIZE, int(max(rel_x, rel_y))))
            if new_size != self._pet_size:
                old_size = self._pet_size
                cx = self.root.winfo_x() + old_size / 2.0
                cy = self.root.winfo_y() + old_size / 2.0
                self._scale_plugin_offsets(new_size / float(old_size))
                self._pet_size = new_size
                self._resize_window_only(center=(cx, cy))
                self._schedule_render()
        except Exception:
            pass

    def _finish_resize(self):
        self._resizing = False
        self._suppress_single = time.time()
        if self._balance_win is not None and self._balance_displayed:
            try:
                self._render_balance(self._balance_displayed, self._balance_last_ok)
            except Exception:
                pass
        if self._render_after_id is not None:
            try:
                self.root.after_cancel(self._render_after_id)
            except Exception:
                pass
            self._render_after_id = None
        self._render_pending = False
        self._do_render_frames()
        if self._plugin_offsets:
            try:
                cfg = load_config()
                pos_map = dict(cfg.get("plugin_positions") or {})
                for pid, off in self._plugin_offsets.items():
                    pos_map[pid] = {"x": off[0], "y": off[1]}
                save_config({"plugin_positions": pos_map})
            except Exception as e:
                log_msg(f"缩放后保存插件偏移失败: {e}")
            self._plugin_offsets = {}
        log_msg(f"缩放完成: {self._pet_size}px")

    def _set_state(self, st, force=False):
        if st == self._state:
            return
        if st not in self._frames:
            return
        # happy 保持期（5 秒）：除用户主动操作（force）外不切换其它状态
        if self._state == "happy" and st != "happy" and not force:
            return
        # think 是“思考锁定”状态：只允许 watcher 在完成时切到 happy，
        # 其余状态（work/afterclick/silent 等）一律不允许打断思考
        if self._state == "think" and st != "happy":
            return
        # work 优先：work 状态下不接受切到 afterclick（键盘唤醒动画不被中断）
        if self._state == "work" and st == "afterclick":
            return
        self._state = st
        self._frame_idx = 0
        # 每次状态变化后主动复检一次 Codex 环境
        try:
            self.root.after(80, self._reconcile_state)
        except Exception:
            pass

    def _animate(self):
        """动画主循环：永远自我续动"""
        # 看门狗：超过 5 秒没有帧更新则判定卡顿，自动重启
        try:
            gap = time.time() - self._last_frame_time
            if gap > self._max_frame_gap and self._frame_idx > 1:
                log_msg(f"看门狗触发: {gap:.1f}s 无帧更新，自动重启")
                self._auto_restart()
                return
        except Exception:
            pass
        self._last_frame_time = time.time()
        try:
            st = self._state
            frames = self._frames.get(st) or self._frames.get("silent")
            if frames:
                idx = self._frame_idx % len(frames)
                self._cur_photo = frames[idx]
                self.canvas.itemconfig(self._img_id, image=frames[idx])
                delays = self._delays.get(st) or []
                d = delays[idx % len(delays)] if delays else 80
                if st == "afterclick":
                    # 一次性状态：播完自动回 silent
                    self._frame_idx += 1
                    if self._frame_idx >= len(frames):
                        self._state = "silent"
                        self._frame_idx = 0
                else:
                    # think / happy / silent / work 都是循环，happy 循环到用户单击为止
                    self._frame_idx = (self._frame_idx + 1) % len(frames)
            else:
                d = 100
        except Exception as e:
            log_msg(f"动画异常: {e}")
            d = 200
        self.root.after(max(30, d), self._animate)

    # ─────────── Codex 状态回调（线程 → 主线程） ───────────

    def _on_codex_busy_thread(self):
        try:
            self.root.after(0, self._codex_busy)
        except Exception:
            pass

    def _on_codex_done_thread(self):
        try:
            self.root.after(0, self._codex_done)
        except Exception:
            pass

    def _codex_busy(self):
        if not self._alive:
            return
        if self._state == "happy":
            return                       # happy 保持期不被思考打断
        self._cancel_happy_timer()
        self._hide_bubble()
        self._approval_hide()
        self._set_state("think")
        log_msg("Codex 开始思考 → think")

    def _cancel_happy_timer(self):
        if self._happy_timer is not None:
            try:
                self.root.after_cancel(self._happy_timer)
            except Exception:
                pass
            self._happy_timer = None

    def _codex_done(self):
        if not self._alive:
            return
        self._cancel_happy_timer()
        self._approval_hide()
        self._set_state("happy")
        self._show_bubble()
        self._happy_timer = self.root.after(HAPPY_HOLD_MS, self._happy_timeout)
        log_msg(f"Codex 完成 → happy + 气泡（{HAPPY_HOLD_MS // 1000} 秒后自动处理）")

    def _happy_timeout(self):
        self._happy_timer = None
        self._hide_bubble()
        if self._watcher.is_any_busy():
            self._set_state("think")
            log_msg("happy 5 秒结束 → 仍有会话思考中，回到 think")
        else:
            self._set_state("silent")
            log_msg("happy 5 秒结束 → 无任务，回到 silent")

    def _reconcile_state(self):
        """状态变化后的环境复检：若 Codex 仍在思考，则回到 think 状态"""
        if not self._alive:
            return
        try:
            # happy 展示期间不打断（让 5 秒完整播完），由 _happy_timeout 决定去向
            if self._state == "happy":
                return
            if self._watcher.is_any_busy() and self._state != "think":
                self._cancel_happy_timer()
                self._hide_bubble()
                # 注意：不动审批窗口，审批可能仍处于等待状态
                self._set_state("think")
                log_msg("状态复检：Codex 仍在思考 → 回到 think")
        except Exception:
            pass

    # ─────────────── 插件：余额徽章（喧响值风格） ───────────────

    def _load_enabled_plugins(self):
        """读取 config.json 的 enabled_plugins；未配置时默认全部启用"""
        cfg = load_config()
        ids = cfg.get("enabled_plugins")
        if ids is None:
            return set(p["manifest"].get("id", os.path.basename(p["dir"]))
                       for p in self._plugins)
        return set(ids)

    def _start_console_server(self):
        """启动本地插件控制台（127.0.0.1 + 随机端口）"""
        try:
            import console_server
            self._console_port = console_server.start_console_server(self)
            log_msg(f"本地控制台已启动: http://127.0.0.1:{self._console_port}/")
        except Exception as e:
            log_msg(f"本地控制台启动失败: {e}")

    def _open_console(self):
        """用默认浏览器打开本地控制台"""
        try:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{self._console_port}/")
            log_msg(f"已打开本地控制台 :{self._console_port}")
        except Exception as e:
            log_msg(f"打开控制台失败: {e}")

    def list_plugins(self):
        """返回插件列表（含启停状态），供控制台页面展示"""
        out = []
        for p in self._plugins:
            m = p["manifest"]
            pid = m.get("id", os.path.basename(p["dir"]))
            out.append({
                "id": pid,
                "name": m.get("name", pid),
                "version": m.get("version", ""),
                "description": m.get("description", ""),
                "enabled": pid in self._enabled_plugins,
            })
        return out

    def set_enabled(self, pid, enabled):
        """控制台切换插件启停；写配置并即时生效"""
        try:
            if enabled:
                self._enabled_plugins.add(pid)
            else:
                self._enabled_plugins.discard(pid)
            save_config({"enabled_plugins": sorted(self._enabled_plugins)})
            if pid == "deepseek-balance":
                if enabled:
                    self.root.after(0, self._balance_enable)
                else:
                    self.root.after(0, self._close_balance)
            log_msg(f"插件 {pid} -> {'启用' if enabled else '停用'}")
            return True
        except Exception as e:
            log_msg(f"切换插件状态失败 [{pid}]: {e}")
            return False

    def _balance_enable(self):
        """重新启用余额插件（徽章 + 定时刷新）"""
        try:
            if self._balance_refresh_id is None:
                self._refresh_balance()
            log_msg("余额插件已重新启用")
        except Exception as e:
            log_msg(f"余额插件启用失败: {e}")

    def _start_balance_plugins(self):
        cfg = load_config()
        self._balance_api_key = (cfg.get("deepseek_api_key") or "").strip()
        tiers = cfg.get("deepseek_balance_tiers") or [20, 50, 80]
        try:
            self._balance_tiers = [float(x) for x in tiers][:3] or [20, 50, 80]
        except Exception:
            self._balance_tiers = [20, 50, 80]
        self._load_balance_assets()
        enabled = "deepseek-balance" in self._enabled_plugins
        if self._balance_plugins and self._balance_api_key and enabled:
            self.root.after(500, self._refresh_balance)
            log_msg("DeepSeek 余额插件已启动（每 60 秒刷新，喧响值风格）")
        elif self._balance_plugins and not enabled:
            log_msg("DeepSeek 余额插件当前为停用状态")
        elif self._balance_plugins:
            log_msg("DeepSeek 余额插件待命：请在 config.json 填写 deepseek_api_key")

    def _load_balance_assets(self):
        """加载整卡渲染器（自包含 compose_badge.py，素材由其内部加载）"""
        self._badge_render = None
        try:
            rpath = os.path.join(PLUGINS_DIR, "deepseek-balance", "compose_badge.py")
            spec = importlib.util.spec_from_file_location("deepseek_balance_render", rpath)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self._badge_render = mod
            log_msg("余额徽章渲染器已加载")
        except Exception as e:
            log_msg(f"徽章渲染器加载失败: {e}")

    def _refresh_balance(self):
        if not self._alive:
            return

        def worker():
            try:
                for p in self._balance_plugins:
                    fn = getattr(p["module"], "fetch_balance", None)
                    if not fn:
                        continue
                    res = fn(self._balance_api_key)
                    self.root.after(0, lambda r=res: self._show_balance(r))
                    break
            except Exception as e:
                self.root.after(0, lambda: log_msg(f"余额刷新异常: {e}"))

        threading.Thread(target=worker, daemon=True).start()
        try:
            self._balance_refresh_id = self.root.after(
                BALANCE_REFRESH_MS, self._refresh_balance)
        except Exception:
            pass

    def _show_balance(self, res):
        text = res.get("text", "?")
        ok = bool(res.get("ok"))
        if not ok:
            text = f"余额 {text}"
        if self._balance_win is None:
            self._create_balance_win()
        self._render_balance(text, ok)

    def _balance_tier(self, amount):
        """反向映射：余额越少等级越高（极→特→喧→无，嘲讽充值）"""
        t = self._balance_tiers or [10, 50, 100]
        if amount < t[0]:
            return "maximum"     # 极
        if amount < t[1]:
            return "blasting"    # 特
        if amount < t[2]:
            return "uproar"      # 喧
        return "base"            # 余额充足 → 无等级

    def _render_balance(self, text, ok):
        m = re.search(r"([\d.]+)", text)
        amount = None
        tier = "base"
        if m:
            try:
                amount = float(m.group(1))
                tier = self._balance_tier(amount)
            except Exception:
                amount = None
        log_msg(f"余额徽章渲染: amount={amount} tier={tier}")
        if self._balance_win is None or self._balance_cv is None:
            return
        if self._balance_tier_key is not None and tier != self._balance_tier_key:
            self._balance_flash()          # 阶段转换：周边闪一次白光
        self._balance_tier_key = tier
        self._balance_displayed = text
        self._balance_last_ok = ok
        try:
            self._draw_balance_content(text, ok, tier, amount)
        except Exception as e:
            log_msg(f"余额徽章渲染失败: {e}")

    def _draw_balance_content(self, text, ok, tier, amount):
        cv = self._balance_cv
        cv.delete("all")
        self._balance_photos = []
        scale = max(0.5, self._pet_size / 200.0)
        pad_x = 12
        pad_y = 10
        x = pad_x
        if self._badge_render is not None and amount is not None:
            try:
                char_h = int(220 * 3 / 16 * 1.5 * 2 / 3 * max(0.5, self._pet_size / 200.0))   # 缩到 2/3
                img = self._badge_render.compose(tier, f"{amount:.2f}", char_h=char_h)
                photo = ImageTk.PhotoImage(img)
                self._balance_photos.append(photo)
                w, h = img.size
                cv.config(width=w, height=h)
                cv.create_image(0, 0, image=photo, anchor="nw")
                f_close = tkfont.Font(family="Microsoft YaHei UI", size=11)
                cv.create_text(w - 12, 10, text="✕", font=f_close, fill="#FFD9E6",
                               tags=("close",))
                self._balance_win_w = w
                self._balance_win_h = h
                self._balance_win.geometry(f"{w}x{h}")
                self._place_balance()
                return
            except Exception as e:
                log_msg(f"整卡徽章渲染失败: {e}")
        # 素材缺失兜底：普通文字
        f_num = tkfont.Font(family="Consolas", size=20, weight="bold")
        cv.create_text(pad_x, pad_y, text=text, anchor="nw",
                       font=f_num, fill="#FF6B6B")
        x = pad_x + f_num.measure(text) + 20
        w = max(x + 22, pad_x * 2 + 20)
        h = max(pad_y + 56 + pad_y, 46)
        cv.config(width=w, height=h)
        f_close = tkfont.Font(family="Microsoft YaHei UI", size=11)
        cv.create_text(w - 12, 10, text="✕", font=f_close, fill="#FFD9E6",
                       tags=("close",))
        self._balance_win_w = w
        self._balance_win_h = h
        self._balance_win.geometry(f"{w}x{h}")
        self._place_balance()

    def _balance_flash(self):
        """阶段转换时，徽章周边闪一次白光"""
        cv = self._balance_cv
        if cv is None:
            return
        try:
            w = self._balance_win_w or cv.winfo_width()
            h = self._balance_win_h or cv.winfo_height()
            r1 = self._rounded_rect(cv, 2, 2, w - 3, h - 3, 10,
                                    fill="", outline="#FFFFFF", width=4, tags="flash")
            r2 = self._rounded_rect(cv, 6, 6, w - 7, h - 7, 8,
                                    fill="", outline="#FFFFFF", width=2, tags="flash")

            def fade(i):
                if not self._alive:
                    return
                try:
                    if cv.winfo_exists() == 0:
                        return
                except Exception:
                    return
                if i >= len(FLASH_STEPS):
                    try:
                        cv.delete("flash")
                    except Exception:
                        pass
                    return
                cv.itemconfig(r1, outline=FLASH_STEPS[i])
                cv.itemconfig(r2, outline=FLASH_STEPS[i])
                try:
                    cv.after(55, lambda: fade(i + 1))
                except Exception:
                    pass

            fade(0)
        except Exception as e:
            log_msg(f"余额闪光失败: {e}")

    def _create_balance_win(self):
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.config(bg="#010203")   # 近黑透明键（纯黑留给徽章黑色粗边框）
        try:
            win.attributes("-transparentcolor", "#010203")
        except Exception:
            pass
        cv = tk.Canvas(win, bg="#010203", highlightthickness=0, bd=0)
        cv.pack()
        win.update_idletasks()
        self._balance_win = win
        self._balance_cv = cv
        self._balance_photos = []
        self._balance_win_w = 220
        self._balance_win_h = 60
        self._balance_tier_key = None
        cv.bind("<Button-1>", lambda e: self._balance_canvas_press(e))
        cv.bind("<B1-Motion>", lambda e: self._balance_drag_move(e))
        cv.tag_bind("close", "<Button-1>", lambda e: self._close_balance())
        self._place_balance()
        log_msg("DeepSeek 余额徽章已显示（喧响值风格）")

    def _balance_canvas_press(self, e):
        try:
            cur = self._balance_cv.find_withtag("current")
            if cur and "close" in self._balance_cv.gettags(cur[0]):
                return
            self._balance_drag_start(e)
        except Exception:
            pass

    def _balance_drag_start(self, e):
        try:
            self._balance_drag_off = (e.x_root - self._balance_win.winfo_x(),
                                      e.y_root - self._balance_win.winfo_y())
        except Exception:
            pass

    def _balance_drag_move(self, e):
        try:
            ox, oy = self._balance_drag_off
            self._balance_win.geometry(f"+{int(e.x_root - ox)}+{int(e.y_root - oy)}")
        except Exception:
            pass

    def _place_balance(self):
        if self._balance_win is None:
            return
        try:
            px = self.root.winfo_rootx()
            py = self.root.winfo_rooty()
            sw = self._balance_win.winfo_screenwidth()
            sh = self._balance_win.winfo_screenheight()
            w = self._balance_win_w or self._balance_win.winfo_width() or 220
            h = self._balance_win_h or self._balance_win.winfo_height() or 60
            gap = 6
            off = self._plugin_offset("deepseek-balance")
            if off is not None:
                # 控制台自定义位置：插件中心相对桌宠中心的偏移
                ox, oy = off
                x = px + self._pet_size / 2.0 + ox - w / 2.0
                y = py + self._pet_size / 2.0 + oy - h / 2.0
            else:
                x = px + (self._pet_size - w) // 2   # 默认：桌宠正下方居中
                y = py + self._pet_size + gap
                if y + h > sh - 4:                   # 底部放不下 → 放到桌宠上方
                    y = max(2, py - h - gap)
            # 屏幕边缘兜底
            if x < 2:
                x = 2
            if x + w > sw - 4:
                x = max(2, sw - w - 4)
            if y < 2:
                y = 2
            if y + h > sh - 4:
                y = max(2, sh - h - 4)
            self._balance_win.geometry(f"+{int(x)}+{int(y)}")
        except Exception:
            pass

    def _plugin_offset(self, pid):
        """读取插件中心偏移；缩放过程中优先用内存里的缩放后偏移，否则读 config"""
        if pid in self._plugin_offsets:
            return self._plugin_offsets[pid]
        try:
            cfg = load_config()
            pos = (cfg.get("plugin_positions") or {}).get(pid)
            if isinstance(pos, dict) and "x" in pos and "y" in pos:
                return float(pos["x"]), float(pos["y"])
        except Exception:
            pass
        return None

    def _scale_plugin_offsets(self, ratio):
        """桌宠缩放时，把所有插件相对桌宠中心的偏移按同一比例缩放（整体缩放）"""
        if ratio <= 0:
            return
        try:
            cfg = load_config()
            pos_map = cfg.get("plugin_positions") or {}
            for pid, pos in pos_map.items():
                if isinstance(pos, dict) and "x" in pos and "y" in pos:
                    try:
                        self._plugin_offsets[pid] = (float(pos["x"]) * ratio,
                                                     float(pos["y"]) * ratio)
                    except Exception:
                        pass
        except Exception as e:
            log_msg(f"插件偏移整体缩放失败: {e}")

    def get_plugin_positions(self):
        """返回桌宠尺寸 + 所有已启用插件的相对位置（中心偏移）"""
        out = {}
        for p in self._plugins:
            pid = p["manifest"].get("id", os.path.basename(p["dir"]))
            if pid not in self._enabled_plugins:
                continue
            off = self._plugin_offset(pid)
            if off is not None:
                out[pid] = {"x": off[0], "y": off[1]}
                continue
            if pid == "deepseek-balance":
                w = self._balance_win_w or 220
                h = self._balance_win_h or 60
                out[pid] = {"x": 0.0,
                            "y": float(self._pet_size / 2.0 + 6 + h / 2.0)}
        return {"pet_size": self._pet_size, "plugins": out}

    def apply_plugin_position(self, pid, x, y):
        """保存插件相对桌宠的位置（中心偏移）并即时应用"""
        try:
            x = float(x)
            y = float(y)
            self._plugin_offsets.pop(pid, None)
            cfg = load_config()
            pos_map = dict(cfg.get("plugin_positions") or {})
            pos_map[pid] = {"x": x, "y": y}
            save_config({"plugin_positions": pos_map})
            if pid == "deepseek-balance":
                self.root.after(0, self._place_balance)
            log_msg(f"插件位置已更新 {pid}: ({x:.0f}, {y:.0f})")
            return True
        except Exception as e:
            log_msg(f"保存插件位置失败 [{pid}]: {e}")
            return False

    def reset_plugin_position(self, pid):
        """删除自定义位置，恢复插件默认位置"""
        try:
            self._plugin_offsets.pop(pid, None)
            cfg = load_config()
            pos_map = dict(cfg.get("plugin_positions") or {})
            if pid in pos_map:
                del pos_map[pid]
                save_config({"plugin_positions": pos_map})
            if pid == "deepseek-balance":
                self.root.after(0, self._place_balance)
            log_msg(f"插件位置已重置 {pid}")
            return True
        except Exception as e:
            log_msg(f"重置插件位置失败 [{pid}]: {e}")
            return False

    def get_balance_tiers(self):
        """返回当前余额档位阈值（极/特/喧 的三个界限）"""
        return {"tiers": [float(x) for x in (self._balance_tiers or [20, 50, 80])]}

    def set_balance_tiers(self, tiers):
        """设置余额档位阈值并实时生效：低于第一个数为极，低于第二个为特，低于第三个为喧"""
        try:
            vals = [float(x) for x in (tiers or [])]
            if len(vals) != 3 or not (vals[0] < vals[1] < vals[2]):
                return False
            self._balance_tiers = vals
            save_config({"deepseek_balance_tiers": vals})
            if self._balance_displayed:
                self.root.after(0, lambda: self._render_balance(
                    self._balance_displayed, self._balance_last_ok))
            log_msg(f"档位阈值已更新: {vals}")
            return True
        except Exception as e:
            log_msg(f"档位设置失败: {e}")
            return False

    def pet_preview_png(self):
        """桌宠 silent 首帧缩略 PNG（预览区中心图标），缓存"""
        if self._pet_preview_cache is None:
            try:
                im = Image.open(GIF_FILES.get("silent"))
                im.seek(0)
                frame = im.convert("RGBA").copy()
                frame.thumbnail((260, 260), Image.LANCZOS)
                buf = io.BytesIO()
                frame.save(buf, "PNG")
                self._pet_preview_cache = buf.getvalue()
            except Exception as e:
                log_msg(f"桌宠预览图生成失败: {e}")
                return None
        return self._pet_preview_cache

    def plugin_preview_png(self, pid, tier=None):
        """插件示例缩略 PNG（预览区 + 卡片示例图 + 档位示例），缓存。
        tier 指定档位（maximum/blasting/uproar/base）时渲染对应样例。"""
        key = f"preview:{pid}" if not tier else f"preview:{pid}:{tier}"
        if key in self._plugin_preview_cache:
            return self._plugin_preview_cache[key]
        data = None
        if pid == "deepseek-balance" and self._badge_render is not None:
            try:
                char_h = int(220 * 3 / 16 * 1.5 * 2 / 3)   # 与运行时比例一致
                if tier:
                    sample_num = {"maximum": "5.00", "blasting": "25.00",
                                  "uproar": "75.00", "base": "120.00"}.get(tier, "12.34")
                    img = self._badge_render.compose(tier, sample_num, char_h=char_h)
                else:
                    img = self._badge_render.compose("blasting", "12.34", char_h=char_h)
                img.thumbnail((230, 130), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, "PNG")
                data = buf.getvalue()
            except Exception as e:
                log_msg(f"插件示例图生成失败 [{pid}]: {e}")
        if data:
            self._plugin_preview_cache[key] = data
        return data

    def _close_balance(self):
        if self._balance_refresh_id is not None:
            try:
                self.root.after_cancel(self._balance_refresh_id)
            except Exception:
                pass
            self._balance_refresh_id = None
        if self._balance_win is not None:
            try:
                self._balance_win.destroy()
            except Exception:
                pass
        self._balance_win = None
        self._balance_cv = None
        self._balance_photos = []
        self._balance_tier_key = None
        log_msg("DeepSeek 余额徽章已关闭")

    # ─────────────── 微信风格气泡（白色 + 粉色不透明） ───────────────

    def _rounded_rect(self, cv, x0, y0, x1, y1, r, **kw):
        """用平滑多边形画圆角矩形"""
        pts = [
            x0 + r, y0,
            x1 - r, y0,
            x1, y0,
            x1, y0 + r,
            x1, y1 - r,
            x1, y1,
            x1 - r, y1,
            x0 + r, y1,
            x0, y1,
            x0, y1 - r,
            x0, y0 + r,
            x0, y0,
        ]
        return cv.create_polygon(pts, smooth=True, **kw)

    def _show_bubble(self):
        if self._bubble_win is not None and self._bubble_win.winfo_exists():
            self._place_bubble()
            self._bubble_win.lift()
            return

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.config(bg="black")
        try:
            win.attributes("-transparentcolor", "black")
            win.attributes("-alpha", BUBBLE_ALPHA)   # 不透明
        except Exception as e:
            log_msg(f"气泡透明属性设置失败: {e}")

        # 按文案实际宽度自适应气泡尺寸，避免文字被窗口裁掉
        f_bubble = tkfont.Font(family="Microsoft YaHei UI", size=12)
        text_w = f_bubble.measure(BUBBLE_TEXT)
        max_single = 520
        body_w = min(max(BUBBLE_BODY_W, text_w + 36), max_single)
        lines = 1
        if text_w + 36 > max_single:
            lines = 2
            body_w = max_single - 40
        body_h = BUBBLE_BODY_H + (lines - 1) * 22
        w = body_w + 2
        h = body_h + BUBBLE_TAIL_H + 2
        cv = tk.Canvas(win, width=w, height=h, bg="black", highlightthickness=0)
        cv.pack()

        # 微信风格：白色圆角主体 + 粉色描边
        self._rounded_rect(
            cv, 1, 1, body_w + 1, body_h + 1,
            BUBBLE_RADIUS, fill=BUBBLE_BG, outline=BUBBLE_BORDER, width=1,
        )
        # 朝下的小尾巴（指向宠物）
        cx = w // 2
        tail_top = body_h + 1
        cv.create_polygon(
            cx - BUBBLE_TAIL_W // 2, tail_top,
            cx + BUBBLE_TAIL_W // 2, tail_top,
            cx, tail_top + BUBBLE_TAIL_H,
            fill=BUBBLE_BG, outline=BUBBLE_BG,
        )
        if lines == 1:
            cv.create_text(
                w // 2, (body_h + 2) // 2,
                text=BUBBLE_TEXT, font=("Microsoft YaHei UI", 12),
                fill=BUBBLE_TEXT_FG,
            )
        else:
            mid = len(BUBBLE_TEXT) // 2
            cv.create_text(
                w // 2, (body_h + 2) // 2 - 11,
                text=BUBBLE_TEXT[:mid], font=("Microsoft YaHei UI", 12),
                fill=BUBBLE_TEXT_FG,
            )
            cv.create_text(
                w // 2, (body_h + 2) // 2 + 11,
                text=BUBBLE_TEXT[mid:], font=("Microsoft YaHei UI", 12),
                fill=BUBBLE_TEXT_FG,
            )

        # 单击气泡任意处 = 收回
        cv.bind("<Button-1>", lambda e: self._dismiss_bubble())
        win.bind("<Button-1>", lambda e: self._dismiss_bubble())

        self._bubble_win = win
        self._bubble_cv = cv
        win.update_idletasks()
        self._place_bubble()
        log_msg("气泡已弹出")

    def _place_above_pet(self, win, cv):
        """把气泡/审批窗口放在宠物上方居中，无空间则放下方，跟随宠物"""
        if win is None:
            return
        try:
            px = self.root.winfo_rootx()
            py = self.root.winfo_rooty()
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            w = win.winfo_width() or cv.winfo_reqwidth()
            h = win.winfo_height() or cv.winfo_reqheight()
            x = px + (self._pet_size - w) // 2
            y = py - h + 4            # 底部（含尾巴）压住宠物顶部 4px
            if y < 0:
                # 顶部没空间时放到宠物下方
                y = py + self._pet_size + 4
            if x < 0:
                x = 0
            if x + w > sw:
                x = max(0, sw - w)
            if y + h > sh:
                y = max(0, sh - h)
            win.geometry(f"+{int(x)}+{int(y)}")
        except Exception:
            pass

    def _place_bubble(self):
        """气泡跟随宠物（上方居中，无空间则下方）"""
        self._place_above_pet(self._bubble_win, self._bubble_cv)

    def _hide_bubble(self):
        if self._bubble_win is not None:
            try:
                self._bubble_win.destroy()
            except Exception:
                pass
        self._bubble_win = None
        self._bubble_cv = None

    def _dismiss_bubble(self):
        """单击收回：气泡消失，happy 结束（不打开任何窗口）"""
        self._cancel_happy_timer()
        self._hide_bubble()
        self._set_state("afterclick", force=True)
        log_msg("单击收回气泡 → afterclick → silent")

    # ─────────────── Codex 审批窗口（粉色不透明） ───────────────

    def _on_approval_thread(self, call_id, args):
        try:
            self.root.after(0, lambda: self._approval_show(call_id, args))
        except Exception:
            pass

    def _on_approval_resolved_thread(self, call_id):
        try:
            self.root.after(0, lambda: self._approval_resolved(call_id))
        except Exception:
            pass

    def _approval_hide(self):
        if self._approval_win is not None:
            try:
                self._approval_win.destroy()
            except Exception:
                pass
        self._approval_win = None
        self._approval_cv = None

    def _approval_show(self, call_id, args):
        if not self._alive:
            return
        self._approval_call_id = call_id
        self._approval_hide()

        if isinstance(args, dict):
            command = str(args.get("cmd") or args.get("command", ""))
            justification = str(args.get("justification", ""))
        else:
            command = str(args)
            justification = ""

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.config(bg="black")
        try:
            win.attributes("-transparentcolor", "black")
            win.attributes("-alpha", APPROVAL_ALPHA)   # 不透明
        except Exception as e:
            log_msg(f"审批窗口透明属性设置失败: {e}")

        f_title = tkfont.Font(family="Microsoft YaHei UI", size=12, weight="bold")
        f_text = tkfont.Font(family="Microsoft YaHei UI", size=10)
        f_btn = tkfont.Font(family="Microsoft YaHei UI", size=10, weight="bold")

        def wrap(font, text, max_w, max_lines):
            out = []
            for raw in text.splitlines() or [""]:
                cur = ""
                for ch in raw:
                    if font.measure(cur + ch) > max_w:
                        out.append(cur)
                        cur = ch
                    else:
                        cur += ch
                out.append(cur)
            if len(out) > max_lines:
                out = out[:max_lines]
                out[-1] = out[-1].rstrip("…") + "…"
            return out

        reason_lines = wrap(f_text, justification, APPROVAL_BODY_MAX_W, 2) if justification else []

        pad = 16
        line_h_reason = 20
        body_h = (len(reason_lines) * line_h_reason + 6) if reason_lines else 26
        btn_h = 40
        tail_h = APPROVAL_TAIL_H
        w = APPROVAL_W
        h = pad + 30 + 8 + body_h + 8 + btn_h + 10 + tail_h

        cv = tk.Canvas(win, width=w, height=h, bg="black", highlightthickness=0)
        cv.pack()

        # 微信风格圆角卡片 + 粉色描边
        self._rounded_rect(cv, 1, 1, w - 1, h - tail_h - 1, 16,
                           fill=APPROVAL_BG, outline=APPROVAL_BORDER, width=1)
        cx = w // 2
        tail_top = h - tail_h - 1
        cv.create_polygon(
            cx - APPROVAL_TAIL_W // 2, tail_top,
            cx + APPROVAL_TAIL_W // 2, tail_top,
            cx, tail_top + APPROVAL_TAIL_H,
            fill=APPROVAL_BG, outline=APPROVAL_BG,
        )

        y = pad
        cv.create_text(pad + 4, y, text="Codex 请求权限", font=f_title,
                       fill=APPROVAL_TITLE_FG, anchor="nw")
        y += 30 + 4
        if reason_lines:
            for ln in reason_lines:
                cv.create_text(pad + 4, y, text=ln, font=f_text,
                               fill=APPROVAL_TEXT_FG, anchor="nw")
                y += line_h_reason
        else:
            cv.create_text(pad + 4, y, text="Codex 请求执行命令权限", font=f_text,
                           fill=APPROVAL_TEXT_FG, anchor="nw")
            y += line_h_reason
        y += 8

        # 三个按钮：允许 / 总是允许 / 拒绝
        buttons = [
            (APPROVAL_BTN_ALLOW,  "#FF7FA3", "white",   "approve"),
            (APPROVAL_BTN_ALWAYS, "#FFD3E0", "#8A3B5E", "always"),
            (APPROVAL_BTN_DENY,   "#E5E5E5", "#5A3A45", "deny"),
        ]
        bw = 100
        bgap = 12
        total = len(buttons) * bw + (len(buttons) - 1) * bgap
        bx = (w - total) // 2
        by = h - tail_h - 10 - btn_h
        for i, (label, fill, fg, action) in enumerate(buttons):
            x0 = bx + i * (bw + bgap)
            x1 = x0 + bw
            tag = f"abtn_{action}"
            self._rounded_rect(cv, x0, by, x1, by + btn_h, 12,
                               fill=fill, outline="", tags=tag)
            cv.create_text((x0 + x1) // 2, by + btn_h // 2, text=label,
                           font=f_btn, fill=fg, tags=tag)
            cv.tag_bind(tag, "<Button-1>", lambda e, a=action: self._approval_action(a))

        # 右键临时关掉审批窗（不点任何决定）
        cv.bind("<Button-3>", lambda e: self._approval_hide())

        self._approval_win = win
        self._approval_cv = cv
        win.update_idletasks()
        self._place_approval()
        log_msg(f"审批请求已弹出: call={call_id} cmd={command[:60]!r}")

    def _place_approval(self):
        """审批窗口跟随宠物（上方居中，无空间则下方）"""
        self._place_above_pet(self._approval_win, self._approval_cv)

    def _approval_action(self, action):
        """用户点了允许/总是允许/拒绝：关窗，后台去点 Codex 应用里的按钮"""
        call_id = self._approval_call_id
        self._approval_hide()
        log_msg(f"审批决定: {action} (call={call_id})")
        threading.Thread(target=self._uia_click, args=(action,), daemon=True).start()

    def _uia_click(self, action):
        """后台线程：调 PowerShell UI 自动化，点 Codex 应用审批卡片上的按钮"""
        script = os.path.join(PROGRAM_DIR, "uia_approval.ps1")
        # 应用卡片可能还没渲染出来，重试几次
        for attempt in range(1, 6):
            try:
                r = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-File", script, "-Action", action],
                    capture_output=True, text=True, timeout=25,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                out = (r.stdout or "").strip()
                file_res = ""
                try:
                    with open(os.path.join(PROGRAM_DIR, "uia_result.txt"), "r", encoding="utf-8") as fh:
                        file_res = fh.read().strip()
                except Exception:
                    pass
                log_msg(f"UIA 点击[{action}] 第{attempt}次: rc={r.returncode} out={out!r} file={file_res!r} err={(r.stderr or '').strip()!r}")
                if file_res:
                    out = file_res
                if r.returncode == 0:
                    return
                if out == "NOT_FOUND" and attempt < 5:
                    time.sleep(1.0)
                    continue
                return
            except Exception as e:
                log_msg(f"UIA 点击异常[{action}] 第{attempt}次: {e}")
                return

    def _approval_resolved(self, call_id):
        if not self._alive:
            return
        if self._approval_call_id == call_id:
            self._approval_hide()
            self._approval_call_id = None
            log_msg(f"审批已处理: call={call_id}")

    # ─────────────── 左键：单击反馈 / 双击收起 / 拖拽 ───────────────

    def _on_lb_press(self, e):
        # 按在右下角缩放把手上 → 进入缩放模式
        try:
            cur = self.canvas.find_withtag("current")
            if cur and "handle" in self.canvas.gettags(cur[0]):
                self._resizing = True
                self._press_pos = None
                return
        except Exception:
            pass
        self._resizing = False
        self._press_pos = (e.x_root, e.y_root)
        self._press_time = time.time()
        self._dragging = False

    def _on_lb_motion(self, e):
        if self._resizing:
            self._handle_resize_motion(e)
            return
        if self._press_pos is None:
            return
        dx = e.x_root - self._press_pos[0]
        dy = e.y_root - self._press_pos[1]
        if abs(dx) > 6 or abs(dy) > 6:
            self._dragging = True
            try:
                self.root.geometry(f"+{int(self.root.winfo_x() + dx)}+{int(self.root.winfo_y() + dy)}")
            except Exception:
                pass
            self._press_pos = (e.x_root, e.y_root)
            self._place_bubble()   # 气泡跟着宠物走
            self._place_balance()  # 余额徽章跟着宠物走

    def _on_lb_release(self, e):
        if self._resizing:
            self._finish_resize()
            return
        if time.time() - self._suppress_single < 0.5:
            self._suppress_single = 0.0
            return
        if self._dragging:
            self._dragging = False
            self._press_pos = None
            return
        if self._click_timer is None:
            self._click_timer = self.root.after(320, self._do_single_click)

    def _find_codex_window(self):
        """枚举顶层可见窗口，找 Codex/ChatGPT 窗口（排除本宠物自身）"""
        try:
            user32 = ctypes.windll.user32
            found = []
            ProcType = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

            def cb(hwnd, lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length == 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == os.getpid():
                    return True
                if title and ("ChatGPT" in title or "Codex" in title):
                    if not any(k in title for k in ("桌宠", "宠物", "桌乐")):
                        found.append(hwnd)
                        return False
                return True

            proc = ProcType(cb)
            user32.EnumWindows(proc, 0)
            return found[0] if found else None
        except Exception:
            return None

    def _open_codex(self):
        """双击打开 Codex：已有窗口则置前，未运行则启动应用"""
        try:
            hwnd = self._find_codex_window()
            if hwnd:
                user32 = ctypes.windll.user32
                user32.ShowWindow(hwnd, 9)      # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
                log_msg("双击：Codex 窗口已置前")
                return
            if self._codex_app_id is None:
                self._codex_app_id = _detect_codex_app_id()
            os.startfile(f"shell:AppsFolder\\{self._codex_app_id}")
            log_msg(f"双击：正在启动 Codex 应用（AppID={self._codex_app_id}）")
        except Exception as e:
            log_msg(f"双击打开 Codex 失败: {e}")

    def _on_lb_double(self, e):
        if self._click_timer is not None:
            try:
                self.root.after_cancel(self._click_timer)
            except Exception:
                pass
            self._click_timer = None
        self._suppress_single = time.time()
        self._hide_bubble()
        self._approval_hide()
        self._open_codex()

    def _do_single_click(self):
        self._click_timer = None
        log_msg(f"单击处理: state={self._state}")
        if time.time() - self._suppress_single < 0.5:
            return
        if self._state == "think":
            return                       # 思考中不响应单击
        if self._state == "happy":
            self._dismiss_bubble()       # happy：单击收回，不打开窗口
            return
        self._set_state("afterclick")    # silent/work：仅播放单击动画，不打开任何窗口

    # ─────────────── 右键：单击打开本地控制台 / 双击退出 ───────────────

    def _on_rb_press(self, e):
        if self._rb_timer is not None:
            return   # 双击第二击，交给 Double-Button-3
        self._rb_timer = self.root.after(320, self._rb_single)

    def _rb_single(self):
        self._rb_timer = None
        self._open_console()

    def _on_rb_double(self, e):
        if self._rb_timer is not None:
            try:
                self.root.after_cancel(self._rb_timer)
            except Exception:
                pass
            self._rb_timer = None
        self._quit()


if __name__ == "__main__":
    DesktopPet()
