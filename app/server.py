"""خادم «دليل»: صفحة واحدة + أربع نقاط API. لا حسابات ولا قاعدة بيانات."""
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import engine
from .library import library

STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_Q = 300


async def index(_: Request):
    return FileResponse(STATIC / "index.html")


async def api_start(_: Request):
    return JSONResponse(engine.start())


async def api_ask(req: Request):
    body = await req.json()
    q = str(body.get("question", ""))[:MAX_Q]
    ctx = body.get("context") or {}
    ctx = {"previous_question": str(ctx.get("previous_question", ""))[:MAX_Q],
           "shown": [str(x) for x in ctx.get("shown", [])][:10]}
    return JSONResponse(engine.ask(q, ctx if ctx["previous_question"] else None))


async def api_need(req: Request):
    body = await req.json()
    return JSONResponse(engine.by_need(str(body.get("need", "")), tuple(body.get("shown", []))[:10]))


async def api_feedback(req: Request):
    body = await req.json()
    v = body.get("value")
    if v not in ("yes", "partial", "no"):
        return JSONResponse({"error": "bad value"}, status_code=400)
    return JSONResponse(engine.feedback(str(body.get("decision_id", ""))[:20], v, body.get("need")))


async def selftest(_: Request):
    """فحص سريع لاتصال النموذج دون كشف أي سر: سؤال ثابت واحد."""
    import time
    from . import router
    t0 = time.time()
    try:
        out = router.decide("هل القرآن من تأليف محمد؟")
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
    """يشغّل التقييم في الخلفية على الخادم (مرة كل 10 دقائق على الأكثر لضبط الكلفة)."""
    import threading
    import time
    if _EVAL["running"]:
        return JSONResponse({"status": "running", "progress": _EVAL["progress"]})
    if time.time() - _EVAL["started"] < 600:
        return JSONResponse({"status": "cooldown", "seconds_left": int(600 - (time.time() - _EVAL["started"]))})
    name = req.query_params.get("set", "dev")
    if name not in ("dev", "heldout"):
        return JSONResponse({"error": "bad set"}, status_code=400)
    runs = max(1, min(3, int(req.query_params.get("runs", "1"))))
    systems = tuple(x for x in req.query_params.get("systems", "daleel,bm25,general").split(",") if x in ("daleel", "bm25", "general"))
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
    Route("/health", health), Route("/api/selftest", selftest),
    Route("/api/eval/run", eval_run), Route("/api/eval/latest", eval_latest), Mount("/static", StaticFiles(directory=STATIC), name="static"),
])
