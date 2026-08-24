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
import time
import glob
import threading
import subprocess
import ctypes
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

HAPPY_HOLD_MS = 3000            # happy 完成后自动保持 3 秒，再决定回 think / silent

# ── 应用菜单：运行时自动探测安装位置（不再写死个人路径）──
# 每项支持字段：
#   name   菜单显示名
#   match  注册表卸载项 DisplayName 的匹配关键字（可多个）
#   exe    可执行文件名（用于拼接 InstallLocation）
#   paths  常见安装路径（支持 * 通配符）
#   path   显式路径（存在则优先使用）
#   icon   菜单图标 PNG 文件名（可省略，省略时用首字兜底图标）
# 探测不到的项自动隐藏。可在 config.json（同目录，或用环境变量
# CODEX_PET_CONFIG 指定位置）里用 launch_apps 覆盖默认列表。
CONFIG_FILE = os.environ.get("CODEX_PET_CONFIG") or os.path.join(PROGRAM_DIR, "config.json")

DEFAULT_LAUNCH_APPS = [
    {
        "name": "微信",
        "icon": "wechat.png",
        "match": ["Weixin", "WeChat"],
        "exe": ["Weixin.exe", "WeChat.exe"],
        "paths": [
            r"C:\Program Files\Tencent\Weixin\Weixin.exe",
            r"C:\Program Files (x86)\Tencent\Weixin\Weixin.exe",
            r"C:\Program Files\Tencent\WeChat\WeChat.exe",
        ],
    },
    {
        "name": "Steam",
        "icon": "steam.png",
        "match": ["Steam"],
        "exe": ["steam.exe"],
        "paths": [
            r"C:\Program Files (x86)\Steam\steam.exe",
            r"C:\Program Files\Steam\steam.exe",
            r"C:\Program Files (x86)\steam+\steam.exe",
        ],
    },
    {
        "name": "WPS",
        "icon": "wps.png",
        "match": ["WPS Office"],
        "exe": ["wps.exe"],
        "paths": [
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "Kingsoft", "WPS Office", "*", "office6", "wps.exe"),
        ],
    },
]


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


def _reg_uninstall_entries():
    """遍历注册表卸载项，产出 {DisplayName, DisplayIcon, InstallLocation}"""
    import winreg
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for root, path in roots:
        try:
            key = winreg.OpenKey(root, path)
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                    i += 1
                except OSError:
                    break
                try:
                    sk = winreg.OpenKey(key, sub)
                except OSError:
                    continue
                d = {}
                for val in ("DisplayName", "DisplayIcon", "InstallLocation"):
                    try:
                        d[val], _ = winreg.QueryValueEx(sk, val)
                    except OSError:
                        pass
                try:
                    winreg.CloseKey(sk)
                except OSError:
                    pass
                yield d
        finally:
            try:
                winreg.CloseKey(key)
            except OSError:
                pass


def _exe_candidates(d, exes):
    """由注册表条目推导候选 exe 路径"""
    out = []
    icon = (d.get("DisplayIcon") or "").strip()
    icon_path = icon.split(",")[0].strip().strip('"') if icon else ""
    if icon_path:
        if icon_path.lower().endswith(".exe"):
            if exes and os.path.basename(icon_path).lower() in [e.lower() for e in exes]:
                out.append(icon_path)
            # DisplayIcon 常指向 uninstall.exe：去同目录找目标 exe
            if exes:
                dname = os.path.dirname(icon_path)
                for exe in exes:
                    out.append(os.path.join(dname, exe))
    loc = (d.get("InstallLocation") or "").strip()
    if loc and exes:
        for exe in exes:
            out.append(os.path.join(loc, exe))
    return out


def _detect_app(item):
    """自动探测某个应用的可执行路径；找不到返回 None"""
    p = (item.get("path") or "").strip()
    if p and os.path.isfile(p):
        return p
    names = [n.lower() for n in (item.get("match") or [])]
    exes = item.get("exe") or []
    for d in _reg_uninstall_entries():
        disp = (d.get("DisplayName") or "")
        if names and not any(m in disp.lower() for m in names):
            continue
        for cand in _exe_candidates(d, exes):
            if cand and os.path.isfile(cand):
                return cand
    for pat in item.get("paths") or []:
        for cand in glob.glob(pat):
            if os.path.isfile(cand):
                return cand
        if os.path.isfile(pat):
            return pat
    return None


def build_launch_apps():
    """组装右键菜单应用列表：(显示名, 可执行路径, 图标文件名)"""
    cfg = load_config()
    spec = cfg.get("launch_apps")
    if not isinstance(spec, list) or not spec:
        spec = DEFAULT_LAUNCH_APPS
    apps = []
    for item in spec:
        if isinstance(item, str):      # 兼容：配置里直接写路径
            item = {"name": os.path.splitext(os.path.basename(item))[0], "path": item}
        if not isinstance(item, dict):
            continue
        exe = _detect_app(item)
        if exe:
            apps.append((item.get("name") or os.path.splitext(os.path.basename(exe))[0],
                         exe, item.get("icon") or ""))
    return apps


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


# 右键菜单应用列表：启动时自动探测安装位置（配置方式见 config.example.json）
LAUNCH_APPS = build_launch_apps()


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
        """主线程读取：当前是否还有会话在思考（决定 happy 3 秒后回 think 还是 silent）"""
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
        self._menu_win = None
        self._menu_close_after = None
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
        try:
            self.root.destroy()
        except Exception:
            pass

    def _auto_restart(self):
        """检测到卡顿时自动重启自身"""
        try:
            self._alive = False
            if getattr(sys, 'frozen', False):
                exe_path = sys.executable
            else:
                exe_path = os.path.abspath(__file__)
            subprocess.Popen([exe_path], shell=False, cwd=os.path.dirname(exe_path))
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

    def _resize_pet(self, new_size):
        """把桌宠缩放到指定边长（像素），动画/窗口/气泡/审批窗一起跟随"""
        new_size = max(MIN_PET_SIZE, min(MAX_PET_SIZE, int(new_size)))
        if new_size == self._pet_size:
            return
        self._pet_size = new_size
        self._resize_window_only()
        self._do_render_frames()
        log_msg(f"缩放为 {self._pet_size}px")

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

    def _resize_window_only(self):
        """拖动时先只改窗口大小，动画帧稍后异步重渲染，保证流畅"""
        try:
            self.canvas.config(width=self._pet_size, height=self._pet_size)
            self.root.geometry(
                f"{self._pet_size}x{self._pet_size}+{self.root.winfo_x()}+{self.root.winfo_y()}")
            self.canvas.coords(self._img_id, self._pet_size // 2, self._pet_size // 2)
            self._redraw_resize_handle()
            self._place_bubble()
            self._place_approval()
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
                self._pet_size = new_size
                self._resize_window_only()
                self._schedule_render()
        except Exception:
            pass

    def _finish_resize(self):
        self._resizing = False
        self._suppress_single = time.time()
        if self._render_after_id is not None:
            try:
                self.root.after_cancel(self._render_after_id)
            except Exception:
                pass
            self._render_after_id = None
        self._render_pending = False
        self._do_render_frames()
        log_msg(f"缩放完成: {self._pet_size}px")

    def _set_state(self, st):
        if st == self._state:
            return
        if st not in self._frames:
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
            log_msg("happy 3 秒结束 → 仍有会话思考中，回到 think")
        else:
            self._set_state("silent")
            log_msg("happy 3 秒结束 → 无任务，回到 silent")

    def _reconcile_state(self):
        """状态变化后的环境复检：若 Codex 仍在思考，则回到 think 状态"""
        if not self._alive:
            return
        try:
            # happy 展示期间不打断（让 3 秒完整播完），由 _happy_timeout 决定去向
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

    def _place_bubble(self):
        """把气泡放在宠物正上方，尾巴压住宠物顶部；拖拽时跟随"""
        if self._bubble_win is None:
            return
        try:
            px = self.root.winfo_rootx()
            py = self.root.winfo_rooty()
            sw = self._bubble_win.winfo_screenwidth()
            sh = self._bubble_win.winfo_screenheight()
            w = self._bubble_win.winfo_width() or self._bubble_cv.winfo_reqwidth()
            h = self._bubble_win.winfo_height() or self._bubble_cv.winfo_reqheight()
            x = px + (self._pet_size - w) // 2
            y = py - h + 4            # 气泡底部（含尾巴）压住宠物顶部 4px
            if y < 0:
                # 顶部没空间时放到宠物下方
                y = py + self._pet_size + 4
            if x < 0:
                x = 0
            if x + w > sw:
                x = max(0, sw - w)
            if y + h > sh:
                y = max(0, sh - h)
            self._bubble_win.geometry(f"+{int(x)}+{int(y)}")
        except Exception:
            pass

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
        self._set_state("afterclick")
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
        """把审批窗口放在宠物上方，跟随宠物"""
        if self._approval_win is None:
            return
        try:
            px = self.root.winfo_rootx()
            py = self.root.winfo_rooty()
            sw = self._approval_win.winfo_screenwidth()
            sh = self._approval_win.winfo_screenheight()
            w = self._approval_win.winfo_width() or self._approval_cv.winfo_reqwidth()
            h = self._approval_win.winfo_height() or self._approval_cv.winfo_reqheight()
            x = px + (self._pet_size - w) // 2
            y = py - h + 4
            if y < 0:
                y = py + self._pet_size + 4
            if x < 0:
                x = 0
            if x + w > sw:
                x = max(0, sw - w)
            if y + h > sh:
                y = max(0, sh - h)
            self._approval_win.geometry(f"+{int(x)}+{int(y)}")
        except Exception:
            pass

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
        if self._menu_win is not None:   # 菜单开着时，先关菜单
            self._close_menu()
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
        self._close_menu()
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

    # ─────────────── 右键：单击菜单 / 双击退出 ───────────────

    def _on_rb_press(self, e):
        if self._menu_win is not None:
            self._close_menu()
            if self._rb_timer is not None:
                try:
                    self.root.after_cancel(self._rb_timer)
                except Exception:
                    pass
                self._rb_timer = None
            return
        if self._rb_timer is not None:
            return   # 双击第二击，交给 Double-Button-3
        self._rb_timer = self.root.after(320, self._rb_single)

    def _rb_single(self):
        self._rb_timer = None
        self._show_menu()

    def _on_rb_double(self, e):
        if self._rb_timer is not None:
            try:
                self.root.after_cancel(self._rb_timer)
            except Exception:
                pass
            self._rb_timer = None
        self._close_menu()
        self._quit()

    # ─────────────── 右键菜单（真实图标，点击即图片） ───────────────

    def _show_menu(self):
        if not LAUNCH_APPS:
            log_msg("未探测到可启动的应用，右键菜单为空")
            return
        if self._menu_win is not None and self._menu_win.winfo_exists():
            return
        items = [(n, ic, 1.0) for (n, _p, ic) in LAUNCH_APPS]
        n = len(items)
        icon_sz = 56
        gap = 12
        pad = 12
        w = icon_sz + pad * 2
        h = n * icon_sz + (n - 1) * gap + pad * 2

        menu = tk.Toplevel(self.root)
        menu.overrideredirect(True)
        menu.attributes("-topmost", True)
        menu.config(bg="#FFF3F6")            # 实底，不透明：点击 100% 可靠
        self._menu_win = menu

        cv = tk.Canvas(menu, width=w, height=h, bg="#FFF3F6", highlightthickness=0)
        cv.pack()

        self._menu_tk_refs = []
        for i, (name, icon_file, scale) in enumerate(items):
            x = w // 2
            y = pad + icon_sz // 2 + i * (icon_sz + gap)
            sz_i = max(16, int(icon_sz * scale))
            img = self._load_icon(icon_file, sz_i)
            if img is None:
                img = self._fallback_icon(name, sz_i)
            self._menu_tk_refs.append(img)
            tag = f"mi_{i}"
            cv.create_image(x, y, image=img, tags=tag)
            # 点击图片本身 → 启动（按下即触发，最直接可靠）
            cv.tag_bind(tag, "<Button-1>", lambda e, idx=i: self._menu_click(idx))

        # 点击面板空白/右键 → 关闭菜单
        cv.bind("<Button-1>", lambda e: self._close_menu())
        cv.bind("<Button-3>", lambda e: self._close_menu())

        # 定位到桌宠右侧
        try:
            px = self.root.winfo_rootx()
            py = self.root.winfo_rooty()
            sw = menu.winfo_screenwidth()
            sh = menu.winfo_screenheight()
        except Exception:
            px = py = 0
            sw, sh = 1920, 1080
        x = px + self._pet_size + 10
        y = py + (self._pet_size - h) // 2
        if y + h > sh - 8:
            y = sh - h - 8
        if y < 0:
            y = 0
        if x + w > sw - 8:
            x = max(0, px - w - 10)
        menu.geometry(f"+{int(x)}+{int(y)}")
        self._menu_close_after = self.root.after(8000, self._close_menu)
        log_msg(f"菜单已打开: {len(items)} 个按钮 @ ({int(x)},{int(y)})")

    def _menu_click(self, idx):
        if 0 <= idx < len(LAUNCH_APPS):
            name, path, _icon = LAUNCH_APPS[idx]
            log_msg(f"点击菜单 '{name}'")
            ok = launch_app(path)
            log_msg(f"启动结果: {'OK' if ok else 'FAIL'}")
        self._close_menu()

    def _close_menu(self):
        if self._menu_close_after is not None:
            try:
                self.root.after_cancel(self._menu_close_after)
            except Exception:
                pass
            self._menu_close_after = None
        if self._menu_win is not None:
            try:
                self._menu_win.destroy()
            except Exception:
                pass
        self._menu_win = None

    def _load_icon(self, icon_file, sz):
        """加载 素材/菜单图标/<file>，等比缩放居中"""
        try:
            path = os.path.join(MENU_ICON_DIR, icon_file)
            if not os.path.exists(path):
                log_msg(f"图标缺失: {path}")
                return None
            im = Image.open(path).convert("RGBA")
            im.thumbnail((sz, sz), Image.LANCZOS)
            bg = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
            bg.paste(im, ((sz - im.width) // 2, (sz - im.height) // 2), im)
            return ImageTk.PhotoImage(bg)
        except Exception as e:
            log_msg(f"图标加载失败 {icon_file}: {e}")
            return None

    def _fallback_icon(self, name, sz):
        """图标缺失时的兜底：白底圆 + 名字首字"""
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([2, 2, sz - 3, sz - 3], fill=(255, 255, 255, 255),
                  outline=(255, 120, 160, 255), width=2)
        try:
            from PIL import ImageFont
            font = ImageFont.truetype("msyh.ttc", int(sz * 0.32))
            d.text((sz // 2, sz // 2), name[:1], font=font,
                   fill=(80, 40, 60, 255), anchor="mm")
        except Exception:
            pass
        return ImageTk.PhotoImage(img)


if __name__ == "__main__":
    DesktopPet()
