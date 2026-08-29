# -*- coding: utf-8 -*-
"""蕾米埃尔 Codex 桌宠 · 本地插件控制台。

极简 HTTP 服务：仅监听 127.0.0.1 + 随机端口，提供：
  GET  /                          控制台页面（含桌面预览区）
  GET  /api/plugins               插件列表 JSON
  GET  /api/positions             各插件相对桌宠的位置（中心偏移）
  GET  /api/pet                   桌宠缩略 PNG
  GET  /api/preview/<id>          插件示例缩略 PNG（?tier= 指定档位示例）
  GET  /api/tiers                 余额档位阈值
  POST /api/plugins/<id>/enable|disable   启用/停用插件
  POST /api/positions/<id>        保存并应用插件位置 {"x": .., "y": ..}
  POST /api/positions/<id>/reset  恢复插件默认位置
  POST /api/tiers                 设置余额档位阈值 {"tiers": [a, b, c]}
"""

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _esc(s):
    """HTML 转义"""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def build_page(plugins):
    """服务端渲染插件卡片 + 客户端 JS 刷新状态与预览区"""
    cards = ""
    for p in plugins:
        enabled = p.get("enabled")
        badge = ('<span class="badge on">已打开</span>' if enabled
                 else '<span class="badge off">已关闭</span>')
        btn = ('<button class="btn off" data-id="%s" data-on="0">关闭</button>'
               if enabled else
               '<button class="btn on" data-id="%s" data-on="1">打开</button>') % _esc(p["id"])
        tier_box = ""
        if p["id"] == "deepseek-balance":
            tier_box = (
                '<div class="tier-box">'
                '<div class="tier-row">'
                '<span>极 &lt;</span><input id="tier1" class="tier-in" type="number" step="any">'
                '<span>特 &lt;</span><input id="tier2" class="tier-in" type="number" step="any">'
                '<span>喧 &lt;</span><input id="tier3" class="tier-in" type="number" step="any">'
                '<button id="apply-tiers" class="btn ghost">应用档位</button>'
                '<span id="tier-msg"></span>'
                '</div>'
                '<div class="tier-hint">三个数字为档位界限（默认 20 / 50 / 80）：余额低于第一个数为「极」，低于第二个数为「特」，低于第三个数为「喧」，其余为基础。保存后实时生效。</div>'
                '<div class="samples">'
                '<div class="sample"><img src="/api/preview/deepseek-balance?tier=maximum" alt="极"><span>极 · 5.00</span></div>'
                '<div class="sample"><img src="/api/preview/deepseek-balance?tier=blasting" alt="特"><span>特 · 25.00</span></div>'
                '<div class="sample"><img src="/api/preview/deepseek-balance?tier=uproar" alt="喧"><span>喧 · 75.00</span></div>'
                '<div class="sample"><img src="/api/preview/deepseek-balance?tier=base" alt="基础"><span>基础 · 120.00</span></div>'
                '</div>'
                '</div>'
            )
        cards += (
            '<div class="card" data-id="' + _esc(p["id"]) + '">'
            '<div class="info">'
            '<div class="name">' + _esc(p.get("name", p["id"])) + badge + '</div>'
            '<div class="desc">' + _esc(p.get("description") or "") + '</div>'
            '<div class="ver">v' + _esc(p.get("version") or "0.0.0") + ' · ' + _esc(p["id"]) + '</div>'
            '<div class="pview"><img src="/api/preview/' + urllib.parse.quote(p["id"]) + '" alt="插件示例"></div>'
            '</div>' + tier_box + btn +
            '</div>'
        )
    return """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>蕾米埃尔 · 插件控制台</title>
<style>
  :root { --pink:#FFB6D1; --deep:#8A3B5E; --bg:#1B1220; --card:#2A1B2E; --text:#F4E6EE; --muted:#B99CAE; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--text); font-family:"Microsoft YaHei UI", sans-serif; padding:28px; }
  h1 { font-size:22px; margin-bottom:6px; }
  .sub { color:var(--muted); font-size:13px; margin-bottom:20px; }
  .sec { font-size:15px; font-weight:bold; color:var(--pink); margin:22px 0 10px; }
  .preview { position:relative; width:400px; height:400px; background:#221527;
             border:2px dashed #4A2C50; border-radius:12px; overflow:hidden; touch-action:none; }
  .preview .pet { position:absolute; left:50%; top:50%; transform:translate(-50%,-50%);
                  width:150px; height:150px; pointer-events:none; opacity:.95; }
  .preview .plg { position:absolute; cursor:grab; background:rgba(255,182,209,.06);
                  border:1px dashed rgba(255,182,209,.55); border-radius:8px; padding:2px; }
  .preview .plg:hover { border-color:var(--pink); }
  .preview .plg:active { cursor:grabbing; }
  .preview .plg img { display:block; }
  .preview .hint { position:absolute; left:12px; bottom:10px; font-size:12px; color:#7E637F; pointer-events:none; }
  .reset-row { margin:10px 0 4px; display:flex; gap:12px; align-items:center; }
  .tier-row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:6px; }
  .tier-in { width:84px; padding:8px 10px; border-radius:8px; border:1px solid #3D263F;
             background:#221527; color:var(--text); font-size:14px; text-align:center; }
  .tier-hint { font-size:12px; color:#7E637F; margin-top:4px; }
  #tier-msg { font-size:13px; color:#7FE0A0; }
  .tier-box { margin-top:14px; padding-top:12px; border-top:1px dashed #3D263F; }
  .samples { display:flex; gap:18px; flex-wrap:wrap; margin-bottom:8px; }
  .sample { text-align:center; }
  .sample img { display:block; background:#221527; border:1px dashed #3D263F;
                border-radius:8px; padding:6px; max-height:150px; }
  .sample span { display:block; font-size:12px; color:var(--muted); margin-top:6px; }
  .card { background:var(--card); border:1px solid #3D263F; border-radius:12px;
          padding:18px 20px; margin-bottom:16px; display:flex; align-items:center; gap:16px; }
  .card .info { flex:1; }
  .card .name { font-size:17px; font-weight:bold; color:var(--pink); }
  .card .desc { font-size:13px; color:var(--muted); margin-top:4px; }
  .card .ver { font-size:12px; color:#7E637F; margin-top:3px; }
  .card .pview { margin-top:12px; }
  .card .pview img { display:block; max-height:130px; border-radius:6px; }
  .btn { border:none; border-radius:8px; padding:9px 20px; font-size:14px; cursor:pointer; font-weight:bold; }
  .btn.on { background:var(--pink); color:#4A1530; }
  .btn.off { background:#3A233E; color:var(--muted); }
  .btn.on:hover { background:#FFC4DA; }
  .btn.off:hover { background:#4A2C50; }
  .btn.ghost { background:#3A233E; color:var(--muted); }
  .btn.ghost:hover { background:#4A2C50; color:var(--text); }
  .badge { font-size:12px; padding:3px 10px; border-radius:20px; margin-left:8px; }
  .badge.on { background:#2E4A32; color:#7FE0A0; }
  .badge.off { background:#4A2C33; color:#E08A8A; }
  .foot { margin-top:22px; color:var(--muted); font-size:13px; }
  .foot a { color:var(--pink); text-decoration:none; }
  #err { display:none; color:#E08A8A; margin-bottom:14px; }
</style>
</head>
<body>
  <h1>💗 蕾米埃尔 Codex 桌宠 · 插件控制台</h1>
  <div class="sub">本地管理已安装插件：拖动上方预览区里的插件示例，可调整它在桌面上的相对位置，松手生效。</div>
  <div id="err">页面刷新失败，请确认桌宠仍在运行。</div>
  <div class="sec">桌面预览</div>
  <div id="preview" class="preview">
    <img class="pet" src="/api/pet" alt="桌宠">
    <div class="hint">拖动插件示例调整位置，松手后应用到桌面</div>
  </div>
  <div class="reset-row">
    <button id="reset" class="btn ghost">重置位置</button>
  </div>
  <div class="sec">插件列表</div>
  <div id="list">__CARDS__</div>
  <div class="foot">更多插件将发布在 <a href="#" onclick="alert('公开插件市场即将上线');return false;">公开插件市场</a>（敬请期待）</div>
  <script>
    var PREVIEW = document.getElementById('preview');
    var PREV = 400, SCALE = 1.0;
    function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
    function esc(s) { return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
    function tierHtmlFor(id) {
      if (id !== 'deepseek-balance') return '';
      return (
        '<div class="tier-box">' +
        '<div class="tier-row">' +
        '<span>极 &lt;</span><input id="tier1" class="tier-in" type="number" step="any">' +
        '<span>特 &lt;</span><input id="tier2" class="tier-in" type="number" step="any">' +
        '<span>喧 &lt;</span><input id="tier3" class="tier-in" type="number" step="any">' +
        '<button id="apply-tiers" class="btn ghost">应用档位</button>' +
        '<span id="tier-msg"></span>' +
        '</div>' +
        '<div class="tier-hint">三个数字为档位界限（默认 20 / 50 / 80）：余额低于第一个数为「极」，低于第二个数为「特」，低于第三个数为「喧」，其余为基础。保存后实时生效。</div>' +
        '<div class="samples">' +
        '<div class="sample"><img src="/api/preview/deepseek-balance?tier=maximum" alt="极"><span>极 · 5.00</span></div>' +
        '<div class="sample"><img src="/api/preview/deepseek-balance?tier=blasting" alt="特"><span>特 · 25.00</span></div>' +
        '<div class="sample"><img src="/api/preview/deepseek-balance?tier=uproar" alt="喧"><span>喧 · 75.00</span></div>' +
        '<div class="sample"><img src="/api/preview/deepseek-balance?tier=base" alt="基础"><span>基础 · 120.00</span></div>' +
        '</div>' +
        '</div>'
      );
    }
    function createCard(p) {
      var card = document.createElement('div');
      card.className = 'card';
      card.dataset.id = p.id;
      var status = p.enabled
        ? '<span class="badge on">已打开</span>'
        : '<span class="badge off">已关闭</span>';
      var btn = p.enabled
        ? '<button class="btn off" data-id="' + esc(p.id) + '" data-on="0">关闭</button>'
        : '<button class="btn on" data-id="' + esc(p.id) + '" data-on="1">打开</button>';
      card.innerHTML =
        '<div class="info">' +
        '<div class="name">' + esc(p.name) + status + '</div>' +
        '<div class="desc">' + esc(p.description || '') + '</div>' +
        '<div class="ver">v' + esc(p.version || '0.0.0') + ' · ' + esc(p.id) + '</div>' +
        '<div class="pview"><img src="/api/preview/' + encodeURIComponent(p.id) + '" alt="插件示例"></div>' +
        '</div>' + tierHtmlFor(p.id) + btn;
      return card;
    }
    function updateCardStatus(card, p) {
      var name = card.querySelector('.name');
      if (name) {
        name.innerHTML = esc(p.name) +
          (p.enabled
            ? '<span class="badge on">已打开</span>'
            : '<span class="badge off">已关闭</span>');
      }
      var btn = card.querySelector('button[data-id]');
      if (btn) {
        btn.outerHTML = p.enabled
          ? '<button class="btn off" data-id="' + esc(p.id) + '" data-on="0">关闭</button>'
          : '<button class="btn on" data-id="' + esc(p.id) + '" data-on="1">打开</button>';
      }
    }
    async function load() {
      try {
        var r = await fetch('/api/plugins');
        var plugins = await r.json();
        var box = document.getElementById('list');
        for (var i = 0; i < plugins.length; i++) {
          var p = plugins[i];
          var card = box.querySelector('.card[data-id="' + esc(p.id) + '"]');
          if (!card) {
            card = createCard(p);
            box.appendChild(card);
          }
          updateCardStatus(card, p);
        }
        document.getElementById('err').style.display = 'none';
        loadPositions();
      } catch (e) {
        document.getElementById('err').style.display = 'block';
      }
    }
    async function loadPositions() {
      var pos;
      try {
        var r = await fetch('/api/positions');
        pos = await r.json();
      } catch (e) { return; }
      var petSize = pos.pet_size || 200;
      var petScale = petSize / 200;
      var petImg = document.querySelector('#preview .pet');
      var ps = Math.min(Math.max(petSize, 60), 240);
      petImg.style.width = ps + 'px';
      petImg.style.height = ps + 'px';
      var plugins = pos.plugins || {};
      document.querySelectorAll('#preview .plg').forEach(function (el) { el.remove(); });
      Object.keys(plugins).forEach(function (id) {
        var item = plugins[id];
        var div = document.createElement('div');
        div.className = 'plg';
        div.dataset.id = id;
        var img = document.createElement('img');
        img.src = '/api/preview/' + encodeURIComponent(id);
        img.alt = id;
        div.appendChild(img);
        img.onload = function () {
          var pw = Math.max(8, Math.round(img.naturalWidth * petScale));
          var ph = Math.max(8, Math.round(img.naturalHeight * petScale));
          img.style.width = pw + 'px';
          img.style.height = ph + 'px';
          div.style.left = clamp(PREV / 2 + item.x * SCALE - pw / 2, 0, PREV - pw) + 'px';
          div.style.top  = clamp(PREV / 2 + item.y * SCALE - ph / 2, 0, PREV - ph) + 'px';
          div.dataset.w = pw;
          div.dataset.h = ph;
        };
        img.onerror = function () { div.remove(); };
        PREVIEW.appendChild(div);
      });
    }
    var drag = null;
    PREVIEW.addEventListener('mousedown', function (ev) {
      var el = ev.target && ev.target.closest ? ev.target.closest('.plg') : null;
      if (!el) return;
      ev.preventDefault();
      var im = el.querySelector('img');
      var pw = im ? im.width : 0, ph = im ? im.height : 0;
      drag = { el: el, sx: ev.clientX, sy: ev.clientY,
               left: parseFloat(el.style.left) || 0, top: parseFloat(el.style.top) || 0,
               w: pw || parseInt(el.dataset.w || 0, 10),
               h: ph || parseInt(el.dataset.h || 0, 10) };
    });
    document.addEventListener('mousemove', function (ev) {
      if (!drag) return;
      var nl = clamp(drag.left + ev.clientX - drag.sx, 0, PREV - drag.w);
      var nt = clamp(drag.top + ev.clientY - drag.sy, 0, PREV - drag.h);
      drag.el.style.left = nl + 'px';
      drag.el.style.top = nt + 'px';
    });
    document.addEventListener('mouseup', async function () {
      if (!drag) return;
      var el = drag.el, id = el.dataset.id;
      var left = parseFloat(el.style.left) || 0, top = parseFloat(el.style.top) || 0;
      var x = Math.round((left + drag.w / 2 - PREV / 2) / SCALE);
      var y = Math.round((top + drag.h / 2 - PREV / 2) / SCALE);
      drag = null;
      try {
        await fetch('/api/positions/' + encodeURIComponent(id), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ x: x, y: y })
        });
      } catch (e) {}
      loadPositions();
    });
    document.addEventListener('click', async function (ev) {
      var apply = ev.target && ev.target.closest ? ev.target.closest('#apply-tiers') : null;
      if (apply) {
        var t = [parseFloat(document.getElementById('tier1').value),
                 parseFloat(document.getElementById('tier2').value),
                 parseFloat(document.getElementById('tier3').value)];
        var msg = document.getElementById('tier-msg');
        try {
          var r = await fetch('/api/tiers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tiers: t })
          });
          var d = await r.json();
          msg.textContent = d.ok ? '✓ 已更新' : '设置失败：请填写递增的三个数字';
          msg.style.color = d.ok ? '#7FE0A0' : '#E08A8A';
        } catch (e) {
          msg.textContent = '连接失败';
          msg.style.color = '#E08A8A';
        }
        return;
      }
      var btn = ev.target && ev.target.closest ? ev.target.closest('button[data-id]') : null;
      if (!btn) return;
      var id = btn.getAttribute('data-id');
      var on = btn.getAttribute('data-on') === '1';
      try {
        await fetch('/api/plugins/' + encodeURIComponent(id) + '/' + (on ? 'enable' : 'disable'), {
          method: 'POST'
        });
      } catch (e) {}
      load();
    });
    document.getElementById('reset').addEventListener('click', async function () {
      try {
        var r = await fetch('/api/positions');
        var pos = await r.json();
        for (var id in (pos.plugins || {})) {
          await fetch('/api/positions/' + encodeURIComponent(id) + '/reset', { method: 'POST' });
        }
      } catch (e) {}
      loadPositions();
    });
    async function loadTiers() {
      var t1 = document.getElementById('tier1');
      if (!t1) return;
      if (document.activeElement === t1 ||
          document.activeElement === document.getElementById('tier2') ||
          document.activeElement === document.getElementById('tier3')) {
        return;   // 正在编辑时不覆盖输入
      }
      try {
        var r = await fetch('/api/tiers');
        var d = await r.json();
        var t = d.tiers || [20, 50, 80];
        document.getElementById('tier1').value = t[0];
        document.getElementById('tier2').value = t[1];
        document.getElementById('tier3').value = t[2];
      } catch (e) {}
    }
    load();
    loadTiers();
    setInterval(function () {
      if (document.visibilityState === 'visible') load();
    }, 3000);
  </script>
</body>
</html>
""".replace("__CARDS__", cards)


class ConsoleHandler(BaseHTTPRequestHandler):
    manager = None

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, build_page(self.manager.list_plugins()), "text/html; charset=utf-8")
        elif path == "/api/plugins":
            data = json.dumps(self.manager.list_plugins(), ensure_ascii=False)
            self._send(200, data, "application/json; charset=utf-8")
        elif path == "/api/positions":
            data = json.dumps(self.manager.get_plugin_positions(), ensure_ascii=False)
            self._send(200, data, "application/json; charset=utf-8")
        elif path == "/api/pet":
            data = self.manager.pet_preview_png()
            if data:
                self._send(200, data, "image/png")
            else:
                self._send(404, "no preview")
        elif path == "/api/tiers":
            data = json.dumps(self.manager.get_balance_tiers(), ensure_ascii=False)
            self._send(200, data, "application/json; charset=utf-8")
        elif path.startswith("/api/preview/"):
            pid = urllib.parse.unquote(path[len("/api/preview/"):])
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            tier = (qs.get("tier") or [None])[0]
            data = self.manager.plugin_preview_png(pid, tier)
            if data:
                self._send(200, data, "image/png")
            else:
                self._send(404, "no preview")
        else:
            self._send(404, "not found")

    def do_POST(self):
        parts = [urllib.parse.unquote(x) for x in self.path.strip("/").split("/")]
        if (len(parts) == 4 and parts[0] == "api" and parts[1] == "plugins"
                and parts[3] in ("enable", "disable")):
            ok = self.manager.set_enabled(parts[2], parts[3] == "enable")
            self._send(200, json.dumps({"ok": ok}), "application/json; charset=utf-8")
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "positions":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
                ok = self.manager.apply_plugin_position(
                    parts[2], float(body.get("x", 0)), float(body.get("y", 0)))
                self._send(200, json.dumps({"ok": ok}), "application/json; charset=utf-8")
            except Exception as exc:
                self._send(200, json.dumps({"ok": False, "error": str(exc)}),
                           "application/json; charset=utf-8")
        elif (len(parts) == 4 and parts[0] == "api" and parts[1] == "positions"
                and parts[3] == "reset"):
            ok = self.manager.reset_plugin_position(parts[2])
            self._send(200, json.dumps({"ok": ok}), "application/json; charset=utf-8")
        elif parts == ["api", "tiers"]:
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
                ok = self.manager.set_balance_tiers(body.get("tiers"))
                self._send(200, json.dumps({"ok": ok}), "application/json; charset=utf-8")
            except Exception as exc:
                self._send(200, json.dumps({"ok": False, "error": str(exc)}),
                           "application/json; charset=utf-8")
        else:
            self._send(404, "not found")


def start_console_server(manager):
    """在 127.0.0.1 随机端口启动控制台服务，返回端口号"""
    ConsoleHandler.manager = manager
    server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
    port = server.server_address[1]
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return port
