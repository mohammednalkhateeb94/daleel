"""خادم «دليل»: صفحة واحدة + أربع نقاط API. لا حسابات ولا قاعدة بيانات."""
import hmac
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import engine
from .library import library

STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_Q = 300

# حد بسيط لعدد الأسئلة من العنوان نفسه (في الذاكرة؛ يكفي خادماً واحداً)
RATE_PER_MIN = int(os.getenv("DALEEL_RATE_PER_MIN", "12"))
RATE_PER_DAY = int(os.getenv("DALEEL_RATE_PER_DAY", "300"))
_hits: dict[str, deque] = defaultdict(deque)


def _client(req: Request) -> str:
    fwd = req.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else "") or (req.client.host if req.client else "?")


def _limited(req: Request) -> bool:
    now, q = time.time(), _hits[_client(req)]
    while q and now - q[0] > 86400:
        q.popleft()
    if len(q) >= RATE_PER_DAY or sum(1 for t in q if now - t < 60) >= RATE_PER_MIN:
        return True
    q.append(now)
    return False


def _admin(req: Request) -> bool:
    """نقاط التشغيل التي تكلّف مالاً لا تعمل إلا بمفتاح الإدارة (DALEEL_ADMIN_KEY في إعدادات الخادم)."""
    key = os.getenv("DALEEL_ADMIN_KEY", "")
    given = req.headers.get("x-admin-key") or req.query_params.get("key") or ""
    return bool(key) and hmac.compare_digest(key.encode(), given.encode())


def _forbidden():
    return JSONResponse({"error": "forbidden"}, status_code=403)


async def _body(req: Request) -> dict | None:
    try:
        b = await req.json()
    except Exception:  # noqa: BLE001
        return None
    return b if isinstance(b, dict) else None


def _bad():
    return JSONResponse({"error": "bad request"}, status_code=400)


async def index(_: Request):
    return FileResponse(STATIC / "index.html")


async def api_start(_: Request):
    return JSONResponse(engine.start())


async def api_ask(req: Request):
    body = await _body(req)
    if body is None:
        return _bad()
    if _limited(req):
        return JSONResponse({"error": "rate_limited"}, status_code=429)
    q = str(body.get("question", ""))[:MAX_Q]
    ctx = body.get("context") if isinstance(body.get("context"), dict) else {}
    shown = ctx.get("shown") if isinstance(ctx.get("shown"), list) else []
    kind = ctx.get("kind") if ctx.get("kind") in engine.FOLLOW_KINDS else None
    ctx = {"previous_question": str(ctx.get("previous_question", ""))[:MAX_Q], "shown": [str(x) for x in shown][:10], "kind": kind}
    # استدعاء النموذج متزامن: يُشغَّل في خيط منفصل حتى لا يتوقف الخادم لبقية الزوار
    return JSONResponse(await run_in_threadpool(engine.ask, q, ctx if ctx["previous_question"] else None))


async def api_need(req: Request):
    body = await _body(req)
    if body is None:
        return _bad()
    shown = body.get("shown") if isinstance(body.get("shown"), list) else []
    seg = body.get("segment") if isinstance(body.get("segment"), str) else None
    return JSONResponse(engine.by_need(str(body.get("need", "")), tuple(str(x) for x in shown)[:10], seg))


async def api_feedback(req: Request):
    body = await _body(req)
    if body is None:
        return _bad()
    v = body.get("value")
    if v not in ("yes", "partial", "no"):
        return JSONResponse({"error": "bad value"}, status_code=400)
    shown = [str(x) for x in body.get("shown", [])][:10] if isinstance(body.get("shown"), list) else []
    return JSONResponse(engine.feedback(str(body.get("decision_id", ""))[:20], v, body.get("need"), shown))


async def api_followup(req: Request):
    """خيارات «ما الذي بقي؟» التي لا تحتاج سؤالاً: غير واضح، تفصيل، مصدر، مختص. تُسجَّل بنوعها."""
    if _limited(req):
        return JSONResponse({"error": "rate_limited"}, status_code=429)
    body = await _body(req)
    if body is None:
        return _bad()
    kind = body.get("kind")
    if kind not in ("UNCLEAR", "EXPAND", "SOURCE", "SPECIALIST"):
        return JSONResponse({"error": "bad kind"}, status_code=400)
    shown = [str(x) for x in body.get("shown", [])][:10] if isinstance(body.get("shown"), list) else []
    return JSONResponse(engine.followup(kind, str(body.get("decision_id", ""))[:20], shown, bool(body.get("has_detail"))))


async def api_refer(req: Request):
    """«أريد مختصاً» بعد «لا» أو «جزئياً»: قرار REFER مسجّل."""
    if _limited(req):
        return JSONResponse({"error": "rate_limited"}, status_code=429)
    body = await _body(req)
    if body is None:
        return _bad()
    return JSONResponse(engine.refer(str(body.get("decision_id", ""))[:20]))


async def selftest(req: Request):
    """فحص سريع لاتصال النموذج دون كشف أي سر: سؤال ثابت واحد. يتطلب مفتاح الإدارة."""
    if not _admin(req):
        return _forbidden()
    from . import router
    t0 = time.time()
    try:
        out = await run_in_threadpool(router.decide, "هل القرآن من تأليف محمد؟")
        meta = out.pop("_meta", {})
        return JSONResponse({"llm_ok": True, "decision": out, "meta": meta})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"llm_ok": False, "error": type(e).__name__, "detail": str(e)[:200],
                             "ms": int((time.time() - t0) * 1000)})


_EVAL = {"running": False, "started": 0.0, "progress": "", "result": None, "error": None}


def _eval_worker(name, runs, systems):
    import json as _json
    from . import evaluation
    try:
        res = evaluation.run_all(name, systems, runs, progress=lambda s, c: _EVAL.update(progress=f"{s}:{c}"))
        _EVAL["result"] = res
        out = Path(__file__).resolve().parent.parent / "eval" / "results"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"latest_{name}.json").write_text(_json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    except Exception as e:  # noqa: BLE001
        _EVAL["error"] = f"{type(e).__name__}: {e}"[:300]
    finally:
        _EVAL["running"] = False


async def eval_run(req: Request):
    """يشغّل التقييم في الخلفية على الخادم. يتطلب مفتاح الإدارة، ومرة كل 10 دقائق على الأكثر."""
    import threading
    if not _admin(req):
        return _forbidden()
    if _EVAL["running"]:
        return JSONResponse({"status": "running", "progress": _EVAL["progress"]})
    if time.time() - _EVAL["started"] < 600:
        return JSONResponse({"status": "cooldown", "seconds_left": int(600 - (time.time() - _EVAL["started"]))})
    name = req.query_params.get("set", "dev")
    if name not in ("dev", "heldout", "register"):
        return JSONResponse({"error": "bad set"}, status_code=400)
    try:
        runs = max(1, min(3, int(req.query_params.get("runs", "1"))))
    except ValueError:
        return _bad()
    systems = tuple(x for x in req.query_params.get("systems", "daleel,bm25,general").split(",") if x in ("daleel", "bm25", "general", "general_pre"))
    _EVAL.update(running=True, started=time.time(), progress="", error=None)
    threading.Thread(target=_eval_worker, args=(name, runs, systems), daemon=True).start()
    return JSONResponse({"status": "started", "set": name, "runs": runs, "systems": systems})


async def eval_latest(req: Request):
    res = _EVAL["result"]
    if _EVAL["running"]:
        return JSONResponse({"status": "running", "progress": _EVAL["progress"]})
    if _EVAL["error"]:
        return JSONResponse({"status": "error", "error": _EVAL["error"]})
    if not res:
        return JSONResponse({"status": "none"})
    view = req.query_params.get("view", "summary")
    if view == "summary":
        return JSONResponse({**{k: v for k, v in res.items() if k != "systems"},
                             "systems": {s: {k: v for k, v in d.items() if k != "cases"} for s, d in res["systems"].items()}})
    sysname = req.query_params.get("system", "daleel")
    cases = res["systems"].get(sysname, {}).get("cases", [])
    if req.query_params.get("only") == "fail":
        cases = [c for c in cases if not c["ok"] or c.get("unsafe")]
    return JSONResponse({"system": sysname, "cases": cases})


async def health(_: Request):
    return JSONResponse({"ok": True, "segments": library()["meta"]["segments"], "library": library()["meta"]["library_version"]})


app = Starlette(routes=[
    Route("/", index), Route("/api/start", api_start), Route("/api/ask", api_ask, methods=["POST"]),
    Route("/api/need", api_need, methods=["POST"]), Route("/api/feedback", api_feedback, methods=["POST"]),
    Route("/api/refer", api_refer, methods=["POST"]), Route("/api/followup", api_followup, methods=["POST"]),
    Route("/health", health), Route("/api/selftest", selftest),
    Route("/api/eval/run", eval_run), Route("/api/eval/latest", eval_latest), Mount("/static", StaticFiles(directory=STATIC), name="static"),
])
