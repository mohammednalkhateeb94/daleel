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


async def health(_: Request):
    return JSONResponse({"ok": True, "segments": library()["meta"]["segments"], "library": library()["meta"]["library_version"]})


app = Starlette(routes=[
    Route("/", index), Route("/api/start", api_start), Route("/api/ask", api_ask, methods=["POST"]),
    Route("/api/need", api_need, methods=["POST"]), Route("/api/feedback", api_feedback, methods=["POST"]),
    Route("/health", health), Mount("/static", StaticFiles(directory=STATIC), name="static"),
])
