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
        pname = _esc(p.get("name", p["id"]))
        btn = ('<button type="button" class="btn off" data-id="%s" data-on="0" aria-label="关闭 %s">关闭</button>'
               if enabled else
               '<button type="button" class="btn on" data-id="%s" data-on="1" aria-label="打开 %s">打开</button>') % (_esc(p["id"]), pname)
        tier_box = ""
        if p["id"] == "deepseek-balance":
            tier_box = (
                '<div class="tier-box">'
                '<div class="tier-row">'
                '<span>极 &lt;</span><input id="tier1" class="tier-in" type="number" step="any" inputmode="decimal" aria-label="极档余额上限">'
                '<span>特 &lt;</span><input id="tier2" class="tier-in" type="number" step="any" inputmode="decimal" aria-label="特档余额上限">'
                '<span>喧 &lt;</span><input id="tier3" class="tier-in" type="number" step="any" inputmode="decimal" aria-label="喧档余额上限">'
                '<button id="apply-tiers" type="button" class="btn ghost">应用档位</button>'
                '<span id="tier-msg" role="status" aria-live="polite"></span>'
                '</div>'
                '<div class="tier-hint">三个数字为档位界限（默认 20 / 50 / 80）：余额低于第一个数为「极」，低于第二个数为「特」，低于第三个数为「喧」，其余为基础。保存后实时生效。</div>'
                '<div class="samples">'
                '<div class="sample"><img src="/api/preview/deepseek-balance?tier=maximum" alt="极档示例" draggable="false"><span>极 · 5.00</span></div>'
                '<div class="sample"><img src="/api/preview/deepseek-balance?tier=blasting" alt="特档示例" draggable="false"><span>特 · 25.00</span></div>'
                '<div class="sample"><img src="/api/preview/deepseek-balance?tier=uproar" alt="喧档示例" draggable="false"><span>喧 · 75.00</span></div>'
                '<div class="sample"><img src="/api/preview/deepseek-balance?tier=base" alt="基础档示例" draggable="false"><span>基础 · 120.00</span></div>'
                '</div>'
                '</div>'
            )
        cards += (
            '<article class="card" data-id="' + _esc(p["id"]) + '">'
            '<div class="head-row">'
            '<div class="info">'
            '<div class="name">' + pname + badge + '</div>'
            '<div class="desc">' + _esc(p.get("description") or "") + '</div>'
            '<div class="ver">v' + _esc(p.get("version") or "0.0.0") + ' · ' + _esc(p["id"]) + '</div>'
            '<div class="pview"><img src="/api/preview/' + urllib.parse.quote(p["id"]) + '" alt="插件示例" draggable="false"></div>'
            '</div>'
            '<div class="side">' + btn + '</div>'
            '</div>'
            + tier_box +
            '</article>'
        )
    return """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>蕾米埃尔 · 插件控制台</title>
<style>
  :root {
    --pink:#FFB6D1; --pink-strong:#FF8FBF; --rose:#E76FA3; --deep:#8A3B5E;
    --surface:rgba(44,26,50,.66); --surface-solid:#2A1B2E;
    --border:rgba(255,182,209,.16); --border-strong:rgba(255,182,209,.40);
    --text:#F7E8F0; --muted:#C4A5B8; --faint:#8F6E86;
    --success:#7FE0A0; --danger:#F08A9A;
    --shadow:0 14px 36px rgba(0,0,0,.34);
    --radius:16px;
    --font:"Microsoft YaHei UI","PingFang SC","Segoe UI",system-ui,sans-serif;
  }
  * { box-sizing:border-box; margin:0; padding:0; }
  html { min-height:100%; }
  body {
    min-height:100vh;
    color:var(--text);
    font-family:var(--font);
    background:
      radial-gradient(880px 520px at 12% -6%, rgba(255,143,191,.15), transparent 60%),
      radial-gradient(760px 460px at 98% 10%, rgba(138,59,94,.24), transparent 62%),
      linear-gradient(180deg,#1A0F22 0%,#130A19 55%,#0D0711 100%);
  }
  /* 细网格 + 顶部光晕，仿 HDD 背景的层次但换成蕾米埃尔配色 */
  body::before {
    content:""; position:fixed; inset:0; pointer-events:none; z-index:0;
    background-image:
      linear-gradient(rgba(255,182,209,.03) 1px,transparent 1px),
      linear-gradient(90deg,rgba(255,182,209,.03) 1px,transparent 1px);
    background-size:44px 44px;
    -webkit-mask-image:radial-gradient(980px 600px at 50% 0%,#000 32%,transparent 80%);
    mask-image:radial-gradient(980px 600px at 50% 0%,#000 32%,transparent 80%);
  }
  .wrap { position:relative; z-index:1; max-width:1020px; margin:0 auto; padding:34px 26px 44px; }
  .topbar { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; flex-wrap:wrap; margin-bottom:26px; }
  .brand { min-width:0; }
  h1 { font-size:23px; line-height:1.35; font-weight:800; letter-spacing:.02em;
       background:linear-gradient(92deg,#FFD9E7 6%,#FF8FBF 55%,#E76FA3 96%);
       -webkit-background-clip:text; background-clip:text; color:transparent; }
  .sub { color:var(--faint); font-size:13px; line-height:1.7; margin-top:5px; max-width:640px; }
  .conn { display:inline-flex; align-items:center; gap:8px; padding:7px 14px; border-radius:999px;
          font-size:12px; font-weight:600; white-space:nowrap; color:var(--muted);
          background:rgba(255,182,209,.06); border:1px solid var(--border);
          transition:color .2s ease, border-color .2s ease; }
  .conn::before { content:""; width:8px; height:8px; border-radius:50%; background:#8A6E7E; transition:background .2s ease; }
  .conn.on { color:var(--success); border-color:rgba(127,224,160,.30); }
  .conn.on::before { background:var(--success); box-shadow:0 0 9px rgba(127,224,160,.8); }
  .conn.off { color:var(--danger); border-color:rgba(240,138,154,.30); }
  .conn.off::before { background:var(--danger); box-shadow:0 0 9px rgba(240,138,154,.75); }
  #err { display:none; color:var(--danger); background:rgba(240,138,154,.08);
         border:1px solid rgba(240,138,154,.26); border-radius:10px;
         padding:10px 14px; font-size:13px; margin-bottom:18px; }
  #err.show { display:block; }
  main { display:flex; flex-direction:column; gap:20px; }
  .panel { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius);
           padding:20px 22px; box-shadow:var(--shadow);
           -webkit-backdrop-filter:blur(12px); backdrop-filter:blur(12px);
           transition:border-color .25s ease; }
  .panel:hover { border-color:var(--border-strong); }
  .panel-head { display:flex; align-items:baseline; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom:16px; }
  .panel-head h2 { display:flex; align-items:center; gap:9px; font-size:15px; font-weight:700; color:var(--pink); letter-spacing:.02em; }
  .panel-head h2::before { content:""; width:4px; height:14px; border-radius:2px;
                           background:linear-gradient(180deg,var(--pink-strong),var(--rose)); }
  .hint-text { font-size:12px; color:var(--faint); }
  .preview { position:relative; width:400px; max-width:100%; height:400px; margin:0 auto;
             background:
               radial-gradient(430px 300px at 50% 40%, rgba(255,143,191,.11), transparent 70%),
               linear-gradient(180deg,#261634,#1A1023);
             border:2px dashed rgba(255,182,209,.30); border-radius:18px;
             overflow:hidden; touch-action:none; }
  .preview .pet { position:absolute; left:50%; top:50%; transform:translate(-50%,-50%);
                  width:150px; height:150px; pointer-events:none; opacity:.95;
                  filter:drop-shadow(0 12px 24px rgba(255,143,191,.24)); }
  .preview .plg { position:absolute; cursor:grab; background:rgba(255,182,209,.09);
                  border:1px dashed rgba(255,182,209,.52); border-radius:10px; padding:3px;
                  box-shadow:0 5px 16px rgba(0,0,0,.28);
                  transition:border-color .16s ease, transform .16s ease, box-shadow .16s ease; }
  .preview .plg:hover { border-color:var(--pink); }
  .preview .plg[data-dragging="true"] { cursor:grabbing; border-color:var(--pink-strong);
    transform:scale(1.06); box-shadow:0 10px 24px rgba(255,143,191,.36); z-index:5; }
  .preview .plg img { display:block; border-radius:6px; }
  .preview .hint { position:absolute; left:12px; bottom:10px; font-size:12px; color:#7E637F; pointer-events:none; }
  .reset-row { margin-top:16px; display:flex; justify-content:center; }
  .btn { border:1px solid transparent; border-radius:10px; padding:9px 22px; font-size:14px;
         cursor:pointer; font-weight:700; font-family:inherit;
         transition:background .18s ease, color .18s ease, border-color .18s ease, transform .12s ease, box-shadow .18s ease; }
  .btn:active { transform:translateY(1px); }
  .btn:focus-visible { outline:2px solid var(--pink-strong); outline-offset:2px; }
  .btn:disabled { opacity:.55; cursor:default; transform:none; }
  .btn.on { background:linear-gradient(180deg,#FFC4DA,var(--pink)); color:#4A1530;
            box-shadow:0 4px 14px rgba(255,143,191,.28); }
  .btn.on:hover:not(:disabled) { background:linear-gradient(180deg,#FFD1E2,#FFB6D1); box-shadow:0 6px 18px rgba(255,143,191,.38); }
  .btn.off { background:#3A233E; color:var(--muted); }
  .btn.off:hover:not(:disabled) { background:#4A2C50; color:var(--text); }
  .btn.ghost { background:rgba(255,182,209,.06); color:var(--muted); border-color:var(--border); }
  .btn.ghost:hover:not(:disabled) { background:rgba(255,182,209,.12); color:var(--text); border-color:var(--border-strong); }
  .badge { display:inline-block; font-size:12px; padding:3px 11px; border-radius:999px; margin-left:9px; font-weight:600; vertical-align:1px; }
  .badge.on { background:rgba(46,74,50,.85); color:var(--success); }
  .badge.off { background:rgba(74,44,51,.85); color:var(--danger); }
  .card { display:flex; flex-direction:column; background:rgba(255,255,255,.025);
          border:1px solid rgba(255,182,209,.10); border-radius:14px;
          padding:18px 20px; margin-bottom:14px;
          transition:background .2s ease, border-color .2s ease; }
  .card:last-child { margin-bottom:0; }
  .card:hover { background:rgba(255,255,255,.04); border-color:rgba(255,182,209,.22); }
  .card .head-row { display:flex; align-items:flex-start; gap:16px; flex-wrap:wrap; }
  .card .side { flex:none; }
  .card .info { flex:1; min-width:0; }
  .card .name { font-size:17px; font-weight:700; color:var(--pink); display:flex; align-items:center; flex-wrap:wrap; }
  .card .desc { font-size:13px; color:var(--muted); margin-top:5px; line-height:1.65; }
  .card .ver { font-size:12px; color:var(--faint); margin-top:4px; font-variant-numeric:tabular-nums; }
  .card .pview { margin-top:12px; }
  .card .pview img { display:block; max-height:132px; border-radius:8px; border:1px solid rgba(255,182,209,.12); }
  .tier-box { margin-top:16px; padding-top:14px; border-top:1px dashed rgba(255,182,209,.18); }
  .tier-row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .tier-in { width:86px; padding:8px 10px; border-radius:10px; border:1px solid rgba(255,182,209,.22);
             background:#221527; color:var(--text); font-size:14px; text-align:center; font-family:inherit;
             transition:border-color .18s ease, box-shadow .18s ease; }
  .tier-in:focus { outline:none; border-color:var(--pink-strong); box-shadow:0 0 0 3px rgba(255,143,191,.16); }
  .tier-hint { font-size:12px; color:var(--faint); margin-top:8px; line-height:1.7; }
  #tier-msg { font-size:13px; font-weight:600; color:var(--success); }
  #tier-msg.bad { color:var(--danger); }
  .samples { display:flex; gap:18px; flex-wrap:wrap; margin-top:14px; }
  .sample { text-align:center; }
  .sample img { display:block; background:#221527; border:1px dashed rgba(255,182,209,.24);
                border-radius:10px; padding:6px; max-height:150px; transition:border-color .2s ease, transform .2s ease; }
  .sample:hover img { border-color:var(--pink); transform:translateY(-2px); }
  .sample span { display:block; font-size:12px; color:var(--muted); margin-top:7px; }
  .empty { text-align:center; color:var(--faint); font-size:13px; padding:26px 10px; border:1px dashed rgba(255,182,209,.2); border-radius:12px; }
  .foot { margin-top:26px; text-align:center; color:var(--faint); font-size:13px; }
  .foot a { color:var(--pink); text-decoration:none; }
  .foot a:hover { text-decoration:underline; }
  .toast { position:fixed; left:50%; bottom:30px; transform:translate(-50%,16px); z-index:99;
           padding:10px 18px; border-radius:999px; font-size:13px; font-weight:600;
           background:rgba(42,27,46,.96); color:var(--text); border:1px solid var(--border);
           box-shadow:0 10px 28px rgba(0,0,0,.4); opacity:0; pointer-events:none;
           transition:opacity .22s ease, transform .22s ease; }
  .toast.show { opacity:1; transform:translate(-50%,0); }
  .toast.ok { color:var(--success); border-color:rgba(127,224,160,.32); }
  .toast.bad { color:var(--danger); border-color:rgba(240,138,154,.32); }
  @media (max-width:640px) {
    body { padding:0; }
    .wrap { padding:24px 16px 34px; }
    .panel { padding:16px 14px; }
    .card { flex-direction:column; }
  }
</style>
</head>
<body>
  <div class="wrap">
    <header class="topbar">
      <div class="brand">
        <h1>💗 蕾米埃尔 Codex 桌宠 · 插件控制台</h1>
        <div class="sub">本地管理已安装插件：在下方预览区拖动插件示例，即可调整它在桌面上的相对位置，松手生效。</div>
      </div>
      <div id="conn" class="conn" role="status" aria-live="polite">连接中…</div>
    </header>
    <div id="err" role="alert">页面刷新失败，请确认桌宠仍在运行。</div>
    <main>
      <section class="panel" aria-labelledby="sec-preview">
        <div class="panel-head">
          <h2 id="sec-preview">桌面预览</h2>
          <span class="hint-text">拖动插件示例调整位置，松手后应用到桌面</span>
        </div>
        <div id="preview" class="preview" aria-label="插件相对桌宠的位置预览">
          <img class="pet" src="/api/pet" alt="桌宠" draggable="false">
          <div class="hint">拖动插件示例调整位置</div>
        </div>
        <div class="reset-row">
          <button id="reset" type="button" class="btn ghost">重置位置</button>
        </div>
      </section>
      <section class="panel" aria-labelledby="sec-plugins">
        <div class="panel-head">
          <h2 id="sec-plugins">插件列表</h2>
          <span id="plugin-count" class="hint-text"></span>
        </div>
        <div id="list">__CARDS__</div>
        <div id="empty" class="empty" hidden>暂无可用插件，将插件 manifest 放入 plugins 目录后刷新。</div>
      </section>
    </main>
    <footer class="foot">更多插件将发布在 <a href="#" id="market-link">公开插件市场</a>（敬请期待）</footer>
  </div>
  <div id="toast" class="toast" role="status" aria-live="polite"></div>
  <script>
    var PREVIEW = document.getElementById('preview');
    var CONN = document.getElementById('conn');
    var TOAST = document.getElementById('toast');
    var EMPTY = document.getElementById('empty');
    var COUNT = document.getElementById('plugin-count');
    var SCALE = 1.0;
    var drag = null;
    var toastTimer = 0;
    function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
    function esc(s) { return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
    function previewWidth() { return PREVIEW.clientWidth || 400; }
    function setConn(mode, text) { CONN.className = 'conn ' + mode; CONN.textContent = text; }
    function toast(msg, ok) {
      TOAST.textContent = msg;
      TOAST.className = 'toast show ' + (ok === false ? 'bad' : 'ok');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(function () { TOAST.className = 'toast'; }, 1900);
    }
    function tierHtmlFor(id) {
      if (id !== 'deepseek-balance') return '';
      return (
        '<div class="tier-box">' +
        '<div class="tier-row">' +
        '<span>极 &lt;</span><input id="tier1" class="tier-in" type="number" step="any" inputmode="decimal" aria-label="极档余额上限">' +
        '<span>特 &lt;</span><input id="tier2" class="tier-in" type="number" step="any" inputmode="decimal" aria-label="特档余额上限">' +
        '<span>喧 &lt;</span><input id="tier3" class="tier-in" type="number" step="any" inputmode="decimal" aria-label="喧档余额上限">' +
        '<button id="apply-tiers" type="button" class="btn ghost">应用档位</button>' +
        '<span id="tier-msg" role="status" aria-live="polite"></span>' +
        '</div>' +
        '<div class="tier-hint">三个数字为档位界限（默认 20 / 50 / 80）：余额低于第一个数为「极」，低于第二个数为「特」，低于第三个数为「喧」，其余为基础。保存后实时生效。</div>' +
        '<div class="samples">' +
        '<div class="sample"><img src="/api/preview/deepseek-balance?tier=maximum" alt="极档示例" draggable="false"><span>极 · 5.00</span></div>' +
        '<div class="sample"><img src="/api/preview/deepseek-balance?tier=blasting" alt="特档示例" draggable="false"><span>特 · 25.00</span></div>' +
        '<div class="sample"><img src="/api/preview/deepseek-balance?tier=uproar" alt="喧档示例" draggable="false"><span>喧 · 75.00</span></div>' +
        '<div class="sample"><img src="/api/preview/deepseek-balance?tier=base" alt="基础档示例" draggable="false"><span>基础 · 120.00</span></div>' +
        '</div>' +
        '</div>'
      );
    }
    function pluginButton(p) {
      return p.enabled
        ? '<button type="button" class="btn off" data-id="' + esc(p.id) + '" data-on="0" aria-label="关闭 ' + esc(p.name) + '">关闭</button>'
        : '<button type="button" class="btn on" data-id="' + esc(p.id) + '" data-on="1" aria-label="打开 ' + esc(p.name) + '">打开</button>';
    }
    function createCard(p) {
      var card = document.createElement('article');
      card.className = 'card';
      card.dataset.id = p.id;
      var status = p.enabled
        ? '<span class="badge on">已打开</span>'
        : '<span class="badge off">已关闭</span>';
      card.innerHTML =
        '<div class="head-row">' +
        '<div class="info">' +
        '<div class="name">' + esc(p.name) + status + '</div>' +
        '<div class="desc">' + esc(p.description || '') + '</div>' +
        '<div class="ver">v' + esc(p.version || '0.0.0') + ' · ' + esc(p.id) + '</div>' +
        '<div class="pview"><img src="/api/preview/' + encodeURIComponent(p.id) + '" alt="插件示例" draggable="false"></div>' +
        '</div>' +
        '<div class="side">' + pluginButton(p) + '</div>' +
        '</div>' + tierHtmlFor(p.id);
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
      if (btn) btn.outerHTML = pluginButton(p);
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
        EMPTY.hidden = plugins.length > 0;
        COUNT.textContent = plugins.length ? '共 ' + plugins.length + ' 个插件' : '';
        document.getElementById('err').classList.remove('show');
        setConn('on', '已连接');
        loadPositions();
      } catch (e) {
        document.getElementById('err').classList.add('show');
        setConn('off', '离线');
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
      var W = previewWidth();
      Object.keys(plugins).forEach(function (id) {
        var item = plugins[id];
        var div = document.createElement('div');
        div.className = 'plg';
        div.dataset.id = id;
        var img = document.createElement('img');
        img.src = '/api/preview/' + encodeURIComponent(id);
        img.alt = id;
        img.draggable = false;
        div.appendChild(img);
        img.onload = function () {
          var pw = Math.max(8, Math.round(img.naturalWidth * petScale));
          var ph = Math.max(8, Math.round(img.naturalHeight * petScale));
          img.style.width = pw + 'px';
          img.style.height = ph + 'px';
          div.style.left = clamp(W / 2 + item.x * SCALE - pw / 2, 0, W - pw) + 'px';
          div.style.top  = clamp(W / 2 + item.y * SCALE - ph / 2, 0, W - ph) + 'px';
          div.dataset.w = pw;
          div.dataset.h = ph;
        };
        img.onerror = function () { div.remove(); };
        PREVIEW.appendChild(div);
      });
    }
    function beginDrag(ev) {
      var el = ev.target && ev.target.closest ? ev.target.closest('.plg') : null;
      if (!el) return;
      ev.preventDefault();
      var im = el.querySelector('img');
      var pw = im ? im.width : 0, ph = im ? im.height : 0;
      drag = { el: el, pointerId: ev.pointerId, sx: ev.clientX, sy: ev.clientY,
               left: parseFloat(el.style.left) || 0, top: parseFloat(el.style.top) || 0,
               w: pw || parseInt(el.dataset.w || 0, 10),
               h: ph || parseInt(el.dataset.h || 0, 10) };
      el.setAttribute('data-dragging', 'true');
      try { PREVIEW.setPointerCapture(ev.pointerId); } catch (e) {}
    }
    function moveDrag(ev) {
      if (!drag || ev.pointerId !== drag.pointerId) return;
      var W = previewWidth();
      var nl = clamp(drag.left + ev.clientX - drag.sx, 0, W - drag.w);
      var nt = clamp(drag.top + ev.clientY - drag.sy, 0, W - drag.h);
      drag.el.style.left = nl + 'px';
      drag.el.style.top = nt + 'px';
    }
    function cancelDrag() {
      if (!drag) return;
      drag.el.removeAttribute('data-dragging');
      drag = null;
    }
    async function endDrag(ev) {
      if (!drag || ev.pointerId !== drag.pointerId) return;
      var el = drag.el, id = el.dataset.id;
      var left = parseFloat(el.style.left) || 0, top = parseFloat(el.style.top) || 0;
      var W = previewWidth();
      var x = Math.round((left + drag.w / 2 - W / 2) / SCALE);
      var y = Math.round((top + drag.h / 2 - W / 2) / SCALE);
      cancelDrag();
      try {
        var r = await fetch('/api/positions/' + encodeURIComponent(id), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ x: x, y: y })
        });
        var d = await r.json();
        toast(d.ok ? '位置已保存' : '位置保存失败', d.ok);
      } catch (e) { toast('位置保存失败', false); }
      loadPositions();
    }
    PREVIEW.addEventListener('pointerdown', function (ev) {
      if (ev.button !== 0) return;
      beginDrag(ev);
    });
    window.addEventListener('pointermove', moveDrag);
    window.addEventListener('pointerup', endDrag);
    window.addEventListener('pointercancel', cancelDrag);
    window.addEventListener('blur', cancelDrag);
    document.addEventListener('click', async function (ev) {
      var apply = ev.target && ev.target.closest ? ev.target.closest('#apply-tiers') : null;
      if (apply) {
        var t = [parseFloat(document.getElementById('tier1').value),
                 parseFloat(document.getElementById('tier2').value),
                 parseFloat(document.getElementById('tier3').value)];
        var msg = document.getElementById('tier-msg');
        msg.textContent = '保存中…';
        msg.className = '';
        apply.disabled = true;
        try {
          var r = await fetch('/api/tiers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tiers: t })
          });
          var d = await r.json();
          msg.textContent = d.ok ? '✓ 已更新' : '设置失败：请填写递增的三个数字';
          msg.className = d.ok ? '' : 'bad';
          if (d.ok) toast('档位已更新');
        } catch (e) {
          msg.textContent = '连接失败';
          msg.className = 'bad';
        } finally {
          apply.disabled = false;
        }
        return;
      }
      var btn = ev.target && ev.target.closest ? ev.target.closest('button[data-id]') : null;
      if (!btn || btn.disabled) return;
      var id = btn.getAttribute('data-id');
      var on = btn.getAttribute('data-on') === '1';
      btn.disabled = true;
      var prev = btn.textContent;
      btn.textContent = on ? '打开中…' : '关闭中…';
      try {
        var r = await fetch('/api/plugins/' + encodeURIComponent(id) + '/' + (on ? 'enable' : 'disable'), {
          method: 'POST'
        });
        var d = await r.json();
        toast(d.ok ? '已' + (on ? '打开' : '关闭') + '「' + id + '」' : '操作失败', d.ok);
      } catch (e) {
        toast('连接失败', false);
      }
      btn.disabled = false;
      btn.textContent = prev;
      await load();
    });
    document.getElementById('reset').addEventListener('click', async function () {
      var btn = this;
      if (btn.disabled) return;
      btn.disabled = true;
      try {
        var r = await fetch('/api/positions');
        var pos = await r.json();
        for (var id in (pos.plugins || {})) {
          await fetch('/api/positions/' + encodeURIComponent(id) + '/reset', { method: 'POST' });
        }
        toast('已重置全部位置');
      } catch (e) { toast('重置失败', false); }
      btn.disabled = false;
      loadPositions();
    });
    document.getElementById('market-link').addEventListener('click', function (ev) {
      ev.preventDefault();
      toast('公开插件市场即将上线，敬请期待');
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
    function refresh() {
      if (document.visibilityState !== 'visible') return;
      load();
      loadTiers();
    }
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') refresh();
    });
    refresh();
    setInterval(refresh, 3000);
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
