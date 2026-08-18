"""Local web GUI — the zero-cost entry point for QA.

`jb-ape ui` starts a loopback-only web server (127.0.0.1, no external
dependencies, nothing leaves the machine) and serves a single-page GUI that
walks the QA journey end to end:

    配置（目标/对接方式/参数/范围 + 连接自检 + 用例预览）
    → 执行（逐条实时进度，可停止）
    → 报告（一页放行结论、白话发现、一键复制提单模板、下载 md/json）

Transparency rules (learned the hard way — "盲盒" feedback):
  * every adapter can be PROBED before a run (``/api/check``): dryrun needs
    nothing, llm gets a real ping round-trip with latency, ext waits for the
    extension heartbeat on the bridge;
  * the exact case list AND payloads are previewable before starting
    (``/api/suites``), filtered live by the selected risk categories;
  * the environment is visible (``/api/env``): whether OPENAI_API_KEY /
    OPENAI_BASE_URL are set — booleans and host only, never values.

The GUI is a thin view over the SAME engine the CLI uses (`build_qa_suite` +
`run_qa` + the QA-first renderers) — no separate logic to drift. The run
itself executes in a background thread; the page polls `/api/status` for
per-case streaming (via `run_qa(on_result=...)`).

API (JSON, loopback only):
  GET  /                       the page
  GET  /api/suites             the fixed case list incl. payloads (preview)
  GET  /api/env                which env vars are visible to the engine
  POST /api/check              connectivity probe for the chosen adapter
  POST /api/run                {url, adapter, llm_model?, …} → starts a run
  GET  /api/status             live progress + per-case verdicts + advice
  POST /api/stop               request an early stop (partial report)
  GET  /api/report?format=md|json&lang=zh|en   the finished report
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jb_ape.qa import (
    CATEGORY_LABELS,
    PLAIN_RISK,
    QAReport,
    build_qa_suite,
    demo_responses,
    load_regression_ids,
    render_qa_markdown,
    run_qa,
    save_regression,
)

DEFAULT_PORT = 8788
REGRESSION_FILE = "qa_regression.json"


def _case_json(r) -> dict:
    """Compact per-case payload for the live progress list + report view."""
    return {
        "id": r.case.id,
        "category": r.case.category,
        "category_label_zh": CATEGORY_LABELS["zh"][r.case.category],
        "category_label_en": CATEGORY_LABELS["en"][r.case.category],
        "scenario": r.case.scenario_sid,
        "technique": r.case.technique,
        "title": r.case.title,
        "verdict": r.verdict,
        "severity": r.severity,
        "level": r.level,
        "evidence": r.evidence,
        "excerpt": r.excerpt,
        "error": r.error,
        "payload": r.case.payload,
        "duration": r.duration,
        "risk_plain_zh": PLAIN_RISK["zh"][r.case.category][0],
        "risk_plain_en": PLAIN_RISK["en"][r.case.category][0],
        "fix_zh": PLAIN_RISK["zh"][r.case.category][1],
        "fix_en": PLAIN_RISK["en"][r.case.category][1],
    }


class UIRun:
    """Mutable state of the single active run (one at a time by design)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.status = "idle"  # idle|waiting-extension|running|finished|stopped|error
        self.results: list = []
        self.total = 0
        self.report: QAReport | None = None
        self.error: str | None = None
        self.stop_flag = threading.Event()
        self.lang = "zh"
        self.fail_on = "high"
        self.url = ""
        self.adapter = "dryrun"
        self.started_at = 0.0

    def snapshot(self) -> dict:
        with self.lock:
            partial = QAReport(url="", adapter="", results=list(self.results))
            counts = (self.report or partial).counts()
            return {
                "status": self.status,
                "url": self.url,
                "adapter": self.adapter,
                "total": self.total,
                "done": len(self.results),
                "results": [_case_json(r) for r in self.results],
                "counts": counts,
                "release_advice_zh": (self.report or partial).release_advice("zh"),
                "release_advice_en": (self.report or partial).release_advice("en"),
                "exit_code": (self.report.exit_code(self.fail_on)
                              if self.report else None),
                "error": self.error,
            }


def check_adapter(opts: dict) -> dict:
    """Lightweight connectivity probe for the chosen adapter — the GUI's
    "验证配置" button. Never runs a case; returns {ok, detail}."""
    adapter = opts.get("adapter", "dryrun")
    if adapter == "dryrun":
        return {"ok": True,
                "detail": "离线演示模式：无需连接目标，可直接开始"
                          "（可勾选「演示失败样例」先看报告形态）"}
    if adapter == "llm":
        model = (opts.get("llm_model") or "").strip()
        if not model:
            return {"ok": False, "detail": "缺少模型名 —— API 直连方式必填"}
        try:
            from jb_ape.targets import LLMTargetClient

            client = LLMTargetClient(model=model,
                                     base_url=opts.get("llm_base_url") or None)
            t0 = time.time()
            client.open(opts.get("url") or "https://target/")
            sub = client.submit_payload(
                "Connectivity check. Reply with the single word: pong")
            latency = round((time.time() - t0) * 1000)
            if sub.error:
                return {"ok": False, "detail": f"目标返回错误：{sub.error}"}
            reply = ""
            for resp in sub.api_responses:
                reply += str(resp.get("content", ""))
            reply = reply.strip().replace("\n", " ")[:80]
            return {"ok": True,
                    "detail": f"对接成功 · 往返 {latency}ms · 目标回复：「{reply or '(空)'}」"}
        except ImportError as exc:
            return {"ok": False,
                    "detail": f"缺少依赖：{exc} —— 在启动 jb-ape ui 的环境里 "
                              f"pip install openai 后重启"}
        except Exception as exc:  # noqa: BLE001 — probe must never crash the UI
            return {"ok": False,
                    "detail": f"连接失败：{type(exc).__name__}: {exc}"}
    if adapter == "ext":
        client = None
        try:
            from jb_ape.bridge import ExtensionBrowserClient

            client = ExtensionBrowserClient(
                port=int(opts.get("ext_port") or 8765),
                case_timeout=5, open_timeout=5)
            wait = float(opts.get("ext_wait") or 8)
            if client.wait_for_extension(timeout=wait):
                return {"ok": True,
                        "detail": f"插件已接入（{client.bridge.url} 心跳正常）· "
                                  f"请确认目标页已登录并保持在前台"}
            return {"ok": False,
                    "detail": f"未检测到插件心跳（等待 {wait:.0f}s）—— 确认 "
                              f"browser_ext/ 已加载启用、扩展未被浏览器休眠、"
                              f"端口 {client.bridge.port} 未被占用"}
        except OSError as exc:
            return {"ok": False,
                    "detail": f"本地桥启动失败（端口被占用？）：{exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False,
                    "detail": f"检测失败：{type(exc).__name__}: {exc}"}
        finally:
            if client is not None:
                with contextlib.suppress(OSError):
                    client.stop()
    return {"ok": False, "detail": f"未知对接方式: {adapter}"}


def _env_payload() -> dict:
    """Booleans + host only — env VALUES (keys) must never reach the page."""
    base = os.environ.get("OPENAI_BASE_URL", "")
    host = ""
    if base:
        with contextlib.suppress(ValueError):
            from urllib.parse import urlparse

            host = urlparse(base).netloc
    return {
        "openai_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "openai_base_url_set": bool(base),
        "openai_base_url_host": host,
    }


def _execute(run: UIRun, opts: dict) -> None:
    """Background worker: build the suite, drive one adapter, stream results."""
    browser = None
    try:
        cats = [c for c in (opts.get("categories") or []) if c]
        cases = build_qa_suite(categories=cats or None)
        if opts.get("regression_only"):
            ids = set(load_regression_ids(opts.get("regression", REGRESSION_FILE)))
            cases = [c for c in cases if c.id in ids]
        if not cases:
            run.status, run.error = "error", "没有可执行的用例（检查回归集/类别筛选）"
            return

        adapter = opts.get("adapter", "dryrun")
        judge_llm = None
        if adapter == "dryrun":
            from jb_ape.browser import DryRunBrowserClient

            browser = DryRunBrowserClient(
                responses=demo_responses(cases) if opts.get("demo") else [])
        elif adapter == "llm":
            from jb_ape.targets import LLMTargetClient

            model = (opts.get("llm_model") or "").strip()
            if not model:
                run.status, run.error = "error", "API 直连需要填写模型名"
                return
            browser = LLMTargetClient(model=model,
                                      base_url=opts.get("llm_base_url") or None)
            from jb_ape.llm import OpenAICompatibleLLM

            judge_llm = OpenAICompatibleLLM(
                model=model, base_url=opts.get("llm_base_url") or None,
                temperature=0.0)
        elif adapter == "ext":
            from jb_ape.bridge import ExtensionBrowserClient

            browser = ExtensionBrowserClient(
                port=int(opts.get("ext_port") or 8765),
                case_timeout=float(opts.get("ext_timeout") or 240.0))
            run.status = "waiting-extension"
            if not browser.wait_for_extension(
                    timeout=float(opts.get("ext_wait") or 90.0)):
                browser.stop()
                run.status, run.error = "error", (
                    "浏览器插件未接入 —— 确认已安装 browser_ext/ 扩展且目标页"
                    "已打开登录（见 browser_ext/README.md）")
                return
        else:
            run.status, run.error = "error", f"未知对接方式: {adapter}"
            return

        run.status = "running"

        def on_result(r) -> None:
            with run.lock:
                run.results.append(r)

        report = run_qa(
            opts.get("url") or "https://target/", browser, cases,
            judge_llm=judge_llm, adapter=adapter,
            on_result=on_result,
            stop_check=run.stop_flag.is_set,
        )
        with run.lock:
            run.report = report
            run.status = "stopped" if run.stop_flag.is_set() else "finished"
        if opts.get("record_failures"):
            save_regression(opts.get("regression", REGRESSION_FILE), report)
    except Exception as exc:  # noqa: BLE001 — the GUI must never crash silently
        run.status, run.error = "error", f"{type(exc).__name__}: {exc}"
    finally:
        if browser is not None and hasattr(browser, "stop"):
            with contextlib.suppress(OSError):
                browser.stop()


class UIServer:
    """Loopback-only HTTP server: static page + JSON API over one active run."""

    def __init__(self, port: int = DEFAULT_PORT, host: str = "127.0.0.1") -> None:
        self.run = UIRun()
        self._worker: threading.Thread | None = None
        # One stable suite listing per server start (fresh canary per start).
        self._suites = [{
            "id": c.id, "category": c.category,
            "category_label_zh": CATEGORY_LABELS["zh"][c.category],
            "scenario": c.scenario_sid, "technique": c.technique,
            "title": c.title, "payload": c.payload,
        } for c in build_qa_suite()]
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _json(self, code: int, obj, ctype: str = "application/json"):
                body = (obj if isinstance(obj, bytes) else
                        json.dumps(obj, ensure_ascii=False).encode("utf-8"))
                self.send_response(code)
                self.send_header("Content-Type", f"{ctype}; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self) -> dict:
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    return json.loads(self.rfile.read(length).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    return {}

            def do_GET(self):  # noqa: N802 — http.server API
                if self.path in ("/", "/index.html"):
                    self._json(200, PAGE.encode("utf-8"), "text/html")
                elif self.path.startswith("/api/suites"):
                    self._json(200, server._suites)
                elif self.path.startswith("/api/env"):
                    self._json(200, _env_payload())
                elif self.path.startswith("/api/status"):
                    self._json(200, server.run.snapshot())
                elif self.path.startswith("/api/report"):
                    from urllib.parse import parse_qs, urlparse

                    q = parse_qs(urlparse(self.path).query)
                    fmt = (q.get("format") or ["md"])[0]
                    lang = (q.get("lang") or [server.run.lang])[0]
                    rep = server.run.report
                    if rep is None:
                        self._json(409, {"error": "还没有完成的运行"})
                    elif fmt == "json":
                        self._json(200, rep.to_dict())
                    else:
                        md = render_qa_markdown(rep, lang=lang,
                                                 fail_on=server.run.fail_on)
                        self._json(200, md.encode("utf-8"), "text/markdown")
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):  # noqa: N802 — http.server API
                if self.path == "/api/stop":
                    server.run.stop_flag.set()
                    self._json(200, {"ok": True})
                    return
                if self.path == "/api/check":
                    busy = server._worker is not None and server._worker.is_alive()
                    if busy:
                        self._json(409, {"error": "已有运行在进行中，请等它结束再自检"})
                        return
                    self._json(200, check_adapter(self._body()))
                    return
                if self.path != "/api/run":
                    self._json(404, {"error": "not found"})
                    return
                if server._worker is not None and server._worker.is_alive():
                    self._json(409, {"error": "已有运行在进行中"})
                    return
                opts = self._body()
                if not opts:
                    self._json(400, {"error": "请求体不是合法 JSON"})
                    return
                server.run = UIRun()
                server.run.lang = opts.get("lang", "zh")
                server.run.fail_on = opts.get("fail_on", "high")
                server.run.url = opts.get("url") or "https://target/"
                server.run.adapter = opts.get("adapter", "dryrun")
                server.run.status = "running"
                server.run.started_at = time.time()
                cases = build_qa_suite(
                    categories=[c for c in (opts.get("categories") or []) if c]
                    or None)
                if opts.get("regression_only"):
                    ids = set(load_regression_ids(
                        opts.get("regression", REGRESSION_FILE)))
                    cases = [c for c in cases if c.id in ids]
                server.run.total = len(cases)
                server._worker = threading.Thread(
                    target=_execute, args=(server.run, opts),
                    daemon=True, name="jb-ape-ui-run")
                server._worker.start()
                self._json(200, {"ok": True, "total": server.run.total})

            def log_message(self, *_args):
                pass

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> UIServer:
        threading.Thread(target=self._server.serve_forever, daemon=True,
                         name="jb-ape-ui").start()
        return self

    def stop(self) -> None:
        self.run.stop_flag.set()
        try:
            self._server.shutdown()
            self._server.server_close()
        except OSError:
            pass


def serve(port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    """Foreground entry for `jb-ape ui` — blocks until interrupted."""
    server = UIServer(port=port).start()
    print(f"[ui] Agent 安全冒烟测试 GUI 已启动: {server.url}")
    print("[ui] 仅本机可访问（127.0.0.1）；Ctrl-C 退出。")
    if open_browser:
        with contextlib.suppress(OSError):
            webbrowser.open(server.url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n[ui] 已退出")
        server.stop()


# --- the single page (no external assets; fully offline) --------------------------

PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent 安全冒烟测试</title>
<style>
  :root {
    --bg:#f5f6f8; --card:#fff; --ink:#1c2128; --mut:#6b7280;
    --line:#e5e7eb; --brand:#2f6fed; --ok:#16a34a; --warn:#d97706;
    --bad:#dc2626; --susp:#ca8a04; --err:#6b7280;
  }
  * { box-sizing:border-box; }
  body { font:15px/1.65 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
         background:var(--bg); color:var(--ink); margin:0; }
  .wrap { max-width:920px; margin:0 auto; padding:28px 16px 80px; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:var(--mut); font-size:13px; margin-bottom:20px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:18px 20px; margin-bottom:16px; }
  .card h2 { font-size:15px; margin:0 0 12px; display:flex; align-items:center; gap:8px; }
  .step { display:inline-flex; width:22px; height:22px; border-radius:50%;
          background:var(--brand); color:#fff; font-size:12px; align-items:center;
          justify-content:center; flex:none; }
  .sect { margin-top:18px; }
  .sect > .stitle { font-size:13px; font-weight:600; color:var(--mut);
                    margin-bottom:8px; }
  label { display:block; font-size:13px; color:var(--mut); margin:10px 0 4px; }
  label.full { color:var(--ink); display:flex; gap:6px; align-items:center; }
  input[type=text], select { width:100%; padding:8px 10px; border:1px solid var(--line);
          border-radius:8px; font-size:14px; background:#fff; }
  input.bad { border-color:var(--bad); }
  .fielderr { color:var(--bad); font-size:12px; margin-top:3px; display:none; }
  .acards { display:flex; gap:10px; flex-wrap:wrap; }
  .acard { flex:1; min-width:200px; border:1px solid var(--line); border-radius:10px;
           padding:10px 12px; cursor:pointer; }
  .acard input { margin-right:6px; }
  .acard b { font-size:14px; }
  .acard .d { font-size:12px; color:var(--mut); margin-top:2px; }
  .acard.sel { border-color:var(--brand); background:#f0f5ff; }
  .hint { font-size:12px; color:var(--mut); margin-top:4px; }
  .envline { font-size:12px; margin-top:8px; color:var(--mut); }
  .envline b.ok { color:var(--ok); } .envline b.no { color:var(--bad); }
  .chips { display:flex; gap:8px; flex-wrap:wrap; margin-top:6px; }
  .chip { border:1px solid var(--line); border-radius:999px; padding:4px 12px;
          font-size:13px; cursor:pointer; user-select:none; background:#fff; }
  .chip.on { background:#e8effd; border-color:var(--brand); color:var(--brand); }
  .count-line { font-size:13px; color:var(--mut); margin-top:8px; }
  .row { display:flex; gap:12px; flex-wrap:wrap; }
  .row > div { flex:1; min-width:180px; }
  button.primary { background:var(--brand); color:#fff; border:none; border-radius:8px;
          padding:10px 26px; font-size:15px; cursor:pointer; }
  button.ghost { background:#fff; color:var(--ink); border:1px solid var(--line);
          border-radius:8px; padding:9px 18px; font-size:14px; cursor:pointer; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  .actions { display:flex; gap:12px; align-items:center; margin-top:18px; flex-wrap:wrap; }
  #checkmsg { font-size:13px; border-radius:8px; padding:8px 12px; display:none;
              flex:1; min-width:260px; }
  #checkmsg.ok { display:block; background:#e7f6ec; color:#166534; }
  #checkmsg.no { display:block; background:#fde8e8; color:#991b1b; }
  #jsmsg { display:none; background:#fff7ed; border:1px solid #fed7aa; color:#9a3412;
           border-radius:8px; padding:8px 12px; font-size:12px; margin-bottom:12px;
           font-family:ui-monospace,monospace; }
  .bar { height:8px; background:#eef0f3; border-radius:6px; overflow:hidden; margin:10px 0 6px; }
  .bar > i { display:block; height:100%; background:var(--brand); width:0;
             transition:width .3s; }
  .phase { font-size:14px; }
  .case { display:flex; align-items:center; gap:10px; padding:7px 0;
          border-bottom:1px dashed var(--line); font-size:13px; }
  .case .id { font-family:ui-monospace,monospace; color:var(--mut); width:64px; }
  .case .cat { color:var(--mut); }
  .badge { margin-left:auto; font-size:12px; border-radius:6px; padding:1px 8px; flex:none; }
  .b-pass{background:#e7f6ec;color:var(--ok);} .b-fail{background:#fde8e8;color:var(--bad);}
  .b-susp{background:#fdf4dd;color:var(--susp);} .b-error{background:#eef0f3;color:var(--err);}
  .banner { border-radius:10px; padding:12px 16px; font-size:15px; margin-bottom:12px; }
  .bn-bad{background:#fde8e8;color:#991b1b;} .bn-mid{background:#ffedd5;color:#9a3412;}
  .bn-susp{background:#fef9c3;color:#854d0e;} .bn-ok{background:#e7f6ec;color:#166534;}
  .bn-err{background:#eef0f3;color:#4b5563;}
  .counts { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
  .count { border:1px solid var(--line); border-radius:8px; padding:4px 12px;
           font-size:13px; }
  details.finding { border:1px solid var(--line); border-radius:10px;
                    margin-bottom:10px; padding:0 14px; background:#fff; }
  details.finding summary { cursor:pointer; padding:10px 0; font-size:14px;
                    display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  details.finding .body { padding:2px 0 12px; font-size:14px; }
  .kv b { color:var(--mut); font-weight:500; }
  code, pre { font-family:ui-monospace,SFMono-Regular,monospace; font-size:12.5px; }
  pre { background:#f6f7f9; border:1px solid var(--line); border-radius:8px;
        padding:8px 10px; overflow:auto; white-space:pre-wrap; word-break:break-all; }
  .pass-chips { display:flex; gap:8px; flex-wrap:wrap; font-size:13px; color:var(--mut); }
  table { border-collapse:collapse; width:100%; font-size:12.5px; }
  th,td { border:1px solid var(--line); padding:4px 8px; text-align:left; }
  .muted { color:var(--mut); }
  .okline { color:var(--ok); }
  #report, #runcard { display:none; }
  .copybtn { font-size:12px; padding:2px 10px; margin-left:8px; }
  details.preview { margin-top:8px; }
  details.preview summary { cursor:pointer; font-size:13px; color:var(--mut); }
  .pv { margin-top:8px; max-height:420px; overflow:auto; }
</style>
</head>
<body>
<div class="wrap">
  <h1>🛡️ Agent 安全冒烟测试</h1>
  <div class="sub" id="subtitle">固定基线用例 · 报告按 QA 视角输出 · 仅本机运行，不外发任何数据</div>
  <div id="jsmsg"></div>

  <div class="card" id="cfgcard">
    <h2><span class="step">1</span> 配置</h2>

    <div class="sect">
      <div class="stitle">目标地址</div>
      <input type="text" id="url" placeholder="https://你的-agent-页面/" value="https://demo/">
      <div class="fielderr" id="url-err">请填写目标地址</div>
    </div>

    <div class="sect">
      <div class="stitle">对接方式</div>
      <div class="acards">
        <label class="acard sel"><input type="radio" name="adapter" value="dryrun" checked>
          <b>演示（离线）</b><div class="d">不需要目标；可脚本化失败样例，先看报告形态</div></label>
        <label class="acard"><input type="radio" name="adapter" value="llm">
          <b>API 直连</b><div class="d">Agent 提供 OpenAI 兼容接口；需要模型名</div></label>
        <label class="acard"><input type="radio" name="adapter" value="ext">
          <b>浏览器插件（登录态）</b><div class="d">装一次 browser_ext/ 插件，复用你已登录的会话</div></label>
      </div>

      <div id="llm-fields" style="display:none">
        <div class="row">
          <div><label>模型名（必填）</label>
            <input type="text" id="llm_model" placeholder="例如 gpt-4o-mini / 内部模型名">
            <div class="fielderr" id="model-err">API 直连需要模型名</div></div>
          <div><label>Base URL（可选）</label>
            <input type="text" id="llm_base_url" placeholder="https://网关/v1">
            <div class="hint">留空时使用下方检测到的环境变量</div></div>
        </div>
        <div class="envline" id="envline">正在检测运行环境…</div>
      </div>

      <div id="ext-fields" style="display:none">
        <div class="hint">需先在浏览器加载 <b>browser_ext/</b> 扩展并登录目标页（一次性，
          见 browser_ext/README.md）。运行期间保持目标标签页在前台。</div>
        <div class="row">
          <div><label>桥端口</label><input type="text" id="ext_port" value="8765"></div>
          <div><label>单条超时（秒）</label><input type="text" id="ext_timeout" value="240"></div>
          <div><label>等待接入（秒）</label><input type="text" id="ext_wait" value="90"></div>
        </div>
      </div>

      <div id="demo-row">
        <label class="full" style="margin-top:12px">
          <input type="checkbox" id="demo"> 演示模式：脚本化 1 个高危失败 + 1 个可疑（先看报告形态）
        </label>
      </div>
    </div>

    <div class="sect">
      <div class="stitle">测试范围</div>
      <div class="chips" id="cats"></div>
      <div class="count-line" id="catline"></div>
      <details class="preview"><summary>预览将执行的用例与 payload（透明起见，点开看）</summary>
        <div class="pv" id="preview"></div>
      </details>
    </div>

    <div class="sect">
      <div class="stitle">运行选项</div>
      <div class="row">
        <div><label>CI 判定策略（fail-on）</label>
          <select id="fail_on">
            <option value="high" selected>high — 仅高危失败算失败</option>
            <option value="medium">medium — 中危也算</option>
            <option value="any">any — 任何失败都算</option>
            <option value="none">none — 只出报告不判失败</option>
          </select></div>
        <div><label>报告语言（下载用）</label>
          <select id="lang"><option value="zh" selected>中文</option><option value="en">English</option></select></div>
      </div>
      <label class="full"><input type="checkbox" id="regression_only"> 只回放回归集（修复验证用）</label>
      <label class="full"><input type="checkbox" id="record_failures"> 把失败/可疑沉淀进回归集</label>
    </div>

    <div class="actions">
      <button class="ghost" id="checkbtn">验证配置</button>
      <button class="primary" id="start">开始测试</button>
      <div id="checkmsg"></div>
    </div>
  </div>

  <div class="card" id="runcard">
    <h2><span class="step">2</span> 执行</h2>
    <div class="phase" id="phase">准备中…</div>
    <div class="bar"><i id="barfill"></i></div>
    <div id="cases"></div>
    <button class="ghost" id="stop">停止（保留已完成部分）</button>
  </div>

  <div class="card" id="report">
    <h2><span class="step">3</span> 报告</h2>
    <div id="banner"></div>
    <div class="counts" id="counts"></div>
    <div id="findings"></div>
    <h2 style="font-size:14px">通过摘要</h2>
    <div class="pass-chips" id="passchips"></div>
    <details style="margin-top:14px"><summary class="muted" style="cursor:pointer">技术附录（判定等级 / 完整 payload）</summary>
      <div id="appendix" style="margin-top:8px"></div>
    </details>
    <button class="ghost" id="dl-md">下载 Markdown 报告</button>
    <button class="ghost" id="dl-json">下载 JSON 报告</button>
  </div>
</div>
<script>
"use strict";
const $ = (id) => document.getElementById(id);
const CATS = [
  ["prompt-injection","提示词注入"], ["indirect-injection","间接注入"],
  ["sensitive-leak","敏感数据泄露"], ["tool-misuse","工具滥用"],
  ["excessive-agency","越权行为"], ["idor-access","越权数据访问"]];
const SEV = {high:"高", medium:"中", low:"低"};
const V_TXT = {pass:"通过", suspicious:"可疑", fail:"失败", error:"错误"};
const V_CLS = {pass:"b-pass", suspicious:"b-susp", fail:"b-fail", error:"b-error"};

const state = { suites: [], running: false, seen: 0, timer: null };

// ---- global error surface (transparency: JS errors are never silent) ----
function showJsError(msg) {
  const el = $("jsmsg");
  el.style.display = "block";
  el.textContent = "⚠ 页面脚本异常（可截图反馈）：" + msg;
}
window.addEventListener("error", (e) => showJsError(e.message));
window.addEventListener("unhandledrejection", (e) =>
  showJsError((e.reason && e.reason.message) || String(e.reason)));

// ---- adapter selection ----
function currentAdapter() {
  return document.querySelector("input[name=adapter]:checked").value;
}
document.querySelectorAll("input[name=adapter]").forEach(r => {
  r.onchange = () => {
    const a = currentAdapter();
    document.querySelectorAll(".acard").forEach(c =>
      c.classList.toggle("sel", c.querySelector("input").checked));
    $("llm-fields").style.display = a === "llm" ? "" : "none";
    $("ext-fields").style.display = a === "ext" ? "" : "none";
    $("demo-row").style.display = a === "dryrun" ? "" : "none";
  };
});

// ---- env line (llm) ----
fetch("/api/env").then(r => r.json()).then(env => {
  const key = env.openai_key_set
    ? "<b class='ok'>✓ 已检测到 OPENAI_API_KEY</b>"
    : "<b class='no'>✗ 未检测到 OPENAI_API_KEY</b>";
  const base = env.openai_base_url_set
    ? `<b class='ok'>✓ OPENAI_BASE_URL=${env.openai_base_url_host}</b>`
    : "<b class='no'>✗ 未设置 OPENAI_BASE_URL</b>";
  $("envline").innerHTML =
    `${key} · ${base}（如需修改：在启动 jb-ape ui 的终端里 export 后重启）`;
}).catch(() => { $("envline").textContent = "环境检测失败（本地服务未响应）"; });

// ---- categories + live case preview ----
const catState = {};
CATS.forEach(([k]) => { catState[k] = false; });
function selectedCats() { return CATS.filter(([k]) => catState[k]).map(([k]) => k); }
function renderCats() {
  $("cats").innerHTML = CATS.map(([k, label]) =>
    `<span class="chip ${catState[k] ? "on" : ""}" data-cat="${k}">${label}</span>`
  ).join("") + `<span class="chip" id="allcats">全选 / 清空</span>`;
  document.querySelectorAll("#cats .chip[data-cat]").forEach(el => {
    el.onclick = () => { catState[el.dataset.cat] = !catState[el.dataset.cat];
                         renderCats(); };
  });
  $("allcats").onclick = () => {
    const anyOff = CATS.some(([k]) => !catState[k]);
    CATS.forEach(([k]) => { catState[k] = anyOff; });
    renderCats();
  };
  updatePreview();
}
function updatePreview() {
  const sel = new Set(selectedCats());
  const list = state.suites.filter(c => sel.size === 0 || sel.has(c.category));
  $("catline").textContent =
    `已选 ${sel.size}/6 类 · 本次将执行 ${list.length} 条用例`
    + `（${sel.size === 0 ? "全部类别" : "仅所选类别"}）`;
  $("preview").innerHTML =
    `<table><tr><th>用例</th><th>类别</th><th>场景</th><th>标题 / payload</th></tr>` +
    list.map(c => `<tr><td>${c.id}</td><td>${c.category_label_zh}</td>
      <td>${c.scenario}</td><td>
      <details><summary>${esc(c.title)}</summary><pre>${esc(c.payload)}</pre></details>
      </td></tr>`).join("") + "</table>";
}

// ---- validation (inline, no alert) ----
function validate() {
  let ok = true;
  const url = $("url").value.trim();
  $("url").classList.toggle("bad", !url);
  $("url-err").style.display = url ? "none" : "block";
  if (!url) ok = false;
  if (currentAdapter() === "llm") {
    const m = $("llm_model").value.trim();
    $("llm_model").classList.toggle("bad", !m);
    $("model-err").style.display = m ? "none" : "block";
    if (!m) ok = false;
  }
  return ok;
}

function collectOpts() {
  return {
    url: $("url").value.trim() || "https://demo/",
    adapter: currentAdapter(),
    llm_model: $("llm_model").value.trim(),
    llm_base_url: $("llm_base_url").value.trim(),
    ext_port: parseInt($("ext_port").value) || 8765,
    ext_timeout: parseFloat($("ext_timeout").value) || 240,
    ext_wait: parseFloat($("ext_wait").value) || 90,
    demo: $("demo").checked,
    categories: selectedCats(),
    fail_on: $("fail_on").value,
    lang: $("lang").value,
    regression_only: $("regression_only").checked,
    record_failures: $("record_failures").checked,
  };
}

// ---- connectivity check (配置自检) ----
$("checkbtn").onclick = async () => {
  const msg = $("checkmsg");
  $("checkbtn").disabled = true;
  msg.className = ""; msg.style.display = "block";
  msg.textContent = "检测中（API 直连会向目标发一条 ping，通常几秒）…";
  try {
    const res = await fetch("/api/check", {method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(collectOpts())});
    const data = await res.json();
    if (!res.ok) { msg.className = "no"; msg.textContent = data.error || "检测失败"; return; }
    msg.className = data.ok ? "ok" : "no";
    msg.textContent = (data.ok ? "✅ " : "❌ ") + data.detail;
  } catch (e) {
    msg.className = "no";
    msg.textContent = "无法连接本地服务（jb-ape ui 是否在运行？）：" + e;
  } finally {
    $("checkbtn").disabled = false;
  }
};

// ---- start / stop (robust: every failure path restores the button) ----
function setRunning(on) {
  state.running = on;
  $("start").disabled = on;
  $("start").textContent = on ? "运行中…" : "开始测试";
  $("cfgcard").style.opacity = on ? 0.55 : 1;
  document.querySelectorAll("#cfgcard input, #cfgcard select")
    .forEach(el => { el.disabled = on; });
}
$("start").onclick = async () => {
  if (state.running) return;
  if (!validate()) return;
  setRunning(true);
  $("runcard").style.display = "";
  $("report").style.display = "none";
  $("cases").innerHTML = ""; state.seen = 0;
  $("phase").textContent = "启动中…";
  try {
    const res = await fetch("/api/run", {method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(collectOpts())});
    const data = await res.json();
    if (!res.ok) { setRunning(false); $("phase").textContent = "未启动：" + data.error; return; }
    $("phase").textContent = currentAdapter() === "ext" ? "等待浏览器插件接入…" : "执行中…";
    state.timer = setInterval(poll, 700); poll();
  } catch (e) {
    setRunning(false);
    $("phase").textContent =
      "无法连接本地服务（jb-ape ui 可能已停止）——刷新页面或重启 jb-ape ui";
    showJsError(String(e));
  }
};
$("stop").onclick = () => fetch("/api/stop", {method: "POST"});

async function poll() {
  let s;
  try {
    const res = await fetch("/api/status");
    s = await res.json();
  } catch (e) {
    clearInterval(state.timer);
    setRunning(false);
    $("phase").textContent = "与本地服务失去联系（jb-ape ui 是否还在运行？）";
    return;
  }
  const ph = {idle:"空闲", "waiting-extension":"等待浏览器插件接入…", running:"执行中",
              finished:"已完成", stopped:"已停止（部分结果）", error:"出错"};
  $("phase").textContent = `${ph[s.status] || s.status} · ${s.done}/${s.total}`;
  $("barfill").style.width = s.total ? `${Math.round(s.done * 100 / s.total)}%` : "0";
  for (; state.seen < s.results.length; state.seen++) {
    const r = s.results[state.seen];
    const row = document.createElement("div");
    row.className = "case";
    const sev = r.severity ? `·${SEV[r.severity]}` : "";
    row.innerHTML = `<span class="id">${r.id}</span>
      <span class="cat">${r.category_label_zh}</span>
      <span>${esc(r.title)}</span>
      <span class="badge ${V_CLS[r.verdict]}">${V_TXT[r.verdict]}${sev}</span>`;
    $("cases").appendChild(row);
  }
  if (s.status === "error") {
    clearInterval(state.timer);
    $("phase").textContent = "出错：" + (s.error || "未知错误");
    if (state.running) setRunning(false);
    return;
  }
  if (["finished", "stopped"].includes(s.status)) {
    clearInterval(state.timer);
    try { renderReport(s); }
    catch (e) { showJsError("报告渲染异常：" + e.message); }
    if (state.running) setRunning(false);
  }
}

// ---- report view ----
function renderReport(s) {
  $("report").style.display = "";
  const c = s.counts;
  const bn = $("banner");
  const cls = c.fail_high ? "bn-bad" : c.fail_medium ? "bn-mid"
    : c.error ? "bn-err" : c.suspicious ? "bn-susp" : "bn-ok";
  bn.className = "banner " + cls;
  bn.textContent = s.release_advice_zh;
  $("counts").innerHTML = [
    ["执行", s.done], ["通过", c.pass], ["可疑", c.suspicious],
    [`失败（高 ${c.fail_high} / 中 ${c.fail_medium}）`, c.fail], ["错误", c.error],
  ].map(([t, v]) => `<span class="count">${t} <b>${v}</b></span>`).join("");

  const findings = s.results.filter(r => r.verdict === "fail" || r.verdict === "suspicious");
  $("findings").innerHTML = findings.length ? findings.map(r => `
    <details class="finding">
      <summary>
        <span class="badge ${V_CLS[r.verdict]}">${SEV[r.severity] || ""}·${V_TXT[r.verdict]}</span>
        <b>${r.id}</b> ${r.category_label_zh} — ${esc(r.title)}
        <button class="ghost copybtn" data-ticket="${r.id}">复制提单</button>
      </summary>
      <div class="body">
        <div class="kv"><b>风险（白话）：</b>${r.risk_plain_zh}</div>
        ${r.error ? `<div class="kv"><b>执行错误：</b>${esc(r.error)}</div>` : ""}
        ${r.excerpt ? `<div class="kv"><b>证据：</b></div><pre>${esc(r.excerpt)}</pre>` : ""}
        <div class="kv"><b>复现：</b></div>
        <pre>jb-ape qa --url ${esc(s.url || "")} --adapter ${esc(s.adapter || "dryrun")} --case ${r.id}</pre>
        ${r.fix_zh ? `<div class="kv"><b>修复方向（给研发）：</b>${r.fix_zh}</div>` : ""}
        <div class="kv"><b>原始 payload：</b></div><pre>${esc(r.payload)}</pre>
      </div>
    </details>`).join("")
    : `<div class="okline">没有失败或可疑项 🎉</div>`;

  const per = {};
  s.results.forEach(r => {
    per[r.category_label_zh] = per[r.category_label_zh] || [0, 0];
    per[r.category_label_zh][1] += 1;
    if (r.verdict === "pass") per[r.category_label_zh][0] += 1;
  });
  $("passchips").innerHTML = Object.entries(per)
    .map(([k, d]) => `${d[0] === d[1] ? "✅" : "⚠️"} ${k} ${d[0]}/${d[1]} 通过`)
    .join(" · ");

  $("appendix").innerHTML = `<table><tr><th>用例</th><th>场景</th><th>技术</th>
    <th>判定等级</th><th>结果</th><th>严重度</th></tr>` +
    s.results.map(r => `<tr><td>${r.id}</td><td>${r.scenario}</td><td>${r.technique}</td>
    <td>${r.level}</td><td>${V_TXT[r.verdict]}</td><td>${r.severity ? SEV[r.severity] : "-"}</td></tr>`).join("")
    + "</table>";

  document.querySelectorAll("[data-ticket]").forEach(btn => {
    btn.onclick = (e) => { e.preventDefault(); copyTicket(findings
      .find(r => r.id === btn.dataset.ticket), s); };
  });
}
function esc(s) { return String(s ?? "").replace(/[&<>]/g,
  m => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[m])); }
function copyTicket(r, s) {
  const txt = [
    `标题：【Agent安全】${r.id} ${r.category_label_zh}（${SEV[r.severity] || ""}危·${
      r.verdict === "fail" ? "已证实" : "待确认"}）`,
    `严重级：${r.severity === "high" ? "High" : r.severity === "medium" ? "Medium" : "Low"}`,
    `风险（白话）：${r.risk_plain_zh}`,
    `复现：jb-ape qa --url ${s.url || ""} --adapter ${s.adapter || "dryrun"} --case ${r.id}`,
    r.excerpt ? `证据：${r.excerpt}` : "",
    `修复方向：${r.fix_zh}`,
  ].filter(Boolean).join("\\n");
  navigator.clipboard.writeText(txt).then(
    () => alert("提单内容已复制，直接粘贴到缺陷系统即可"),
    () => prompt("复制失败，请手动复制：", txt));
}
$("dl-md").onclick = () => download("qa-report.md", `/api/report?format=md&lang=${$("lang").value}`);
$("dl-json").onclick = () => download("qa-report.json", "/api/report?format=json");
async function download(name, url) {
  const res = await fetch(url);
  if (!res.ok) { alert("报告尚未生成"); return; }
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; a.click();
  URL.revokeObjectURL(a.href);
}

// ---- boot ----
fetch("/api/suites").then(r => r.json()).then(cases => {
  state.suites = cases;
  $("subtitle").textContent =
    `${cases.length} 条固定基线用例 · 配置可先验证 · 用例可先预览 · 仅本机运行，不外发任何数据`;
  renderCats();
}).catch(() => showJsError("用例清单加载失败"));
</script>
</body>
</html>
"""
