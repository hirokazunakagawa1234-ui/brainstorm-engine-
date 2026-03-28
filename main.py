import asyncio
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_ipaddr
from slowapi.errors import RateLimitExceeded

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

import db
import generator
from models import NodeCreate, TITLE_MAX_LEN

_ratelimit_enabled = os.environ.get("RATELIMIT_ENABLED", "true").lower() == "true"
limiter = Limiter(key_func=get_ipaddr, enabled=_ratelimit_enabled)


def _validate_env():
    missing = [k for k in ("GEMINI_API_KEY", "DATABASE_URL") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"必須の環境変数が未設定です: {', '.join(missing)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_env()
    db.init_pool()
    db.init_db()
    generator.init_client()
    yield


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    topics = await asyncio.to_thread(db.get_topics)
    return templates.TemplateResponse(request, "index.html", {"topics": topics})


@app.get("/topics")
async def topics_redirect():
    return RedirectResponse(url="/", status_code=301)


@app.post("/topics")
async def create_topic(title: str = Form(...)):
    if not title.strip():
        raise HTTPException(status_code=400, detail="議題タイトルを入力してください")
    if len(title.strip()) > TITLE_MAX_LEN:
        raise HTTPException(status_code=400, detail=f"議題タイトルは{TITLE_MAX_LEN}文字以内で入力してください")
    topic_id = await asyncio.to_thread(db.create_topic, title.strip())
    return RedirectResponse(url=f"/topics/{topic_id}", status_code=303)


@app.get("/topics/{topic_id}", response_class=HTMLResponse)
async def topic_detail(request: Request, topic_id: int):
    topic = await asyncio.to_thread(db.get_topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="議題が見つかりません")
    return templates.TemplateResponse(request, "topic.html", {"topic": topic})


@app.post("/nodes")
@limiter.limit("10/minute")
async def create_node(request: Request, payload: NodeCreate):
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="投稿内容を入力してください")

    # 対象議題の存在確認
    if await asyncio.to_thread(db.get_topic, payload.topic_id) is None:
        raise HTTPException(status_code=404, detail="議題が見つかりません")

    # 議論の文脈を構築（parent_id の存在・トピック一致確認を兼ねる）
    if payload.parent_id is not None:
        ancestor_nodes = await asyncio.to_thread(db.get_ancestor_chain, payload.parent_id)
        if not ancestor_nodes or ancestor_nodes[-1]["topic_id"] != payload.topic_id:
            raise HTTPException(status_code=400, detail="parent_id が無効です")
        context = "\n".join([f"[{n['persona']}] {n['content']}" for n in ancestor_nodes])
    else:
        context = "(新しいスレッドの開始)"

    # 3ペルソナを並列呼び出し（DBへの書き込み前に実行してDBの孤立ノードを防ぐ）
    try:
        responses = await generator.generate_all_responses(context, payload.content.strip())
    except Exception as e:
        logger.exception("AI応答の取得に失敗しました")
        raise HTTPException(status_code=502, detail="AI応答の取得に失敗しました")

    # ユーザーノードとAIノードを単一トランザクションで保存
    user_node_id = await asyncio.to_thread(
        db.create_user_and_ai_nodes,
        payload.topic_id,
        payload.parent_id,
        payload.content.strip(),
        responses,
    )

    return {"user_node_id": user_node_id}


@app.get("/health")
async def health():
    try:
        await asyncio.to_thread(db.ping)
    except Exception:
        raise HTTPException(status_code=503, detail="DB接続に失敗しました")
    return {"status": "ok"}


@app.get("/nodes/{topic_id}")
async def get_nodes(topic_id: int):
    if await asyncio.to_thread(db.get_topic, topic_id) is None:
        raise HTTPException(status_code=404, detail="議題が見つかりません")
    return await asyncio.to_thread(db.get_nodes, topic_id)
