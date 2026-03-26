import asyncio
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

import db
import generator
from models import NodeCreate, TITLE_MAX_LEN


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
async def create_node(payload: NodeCreate):
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="投稿内容を入力してください")

    # 対象議題の存在確認
    if await asyncio.to_thread(db.get_topic, payload.topic_id) is None:
        raise HTTPException(status_code=404, detail="議題が見つかりません")

    # parent_id が同一トピックに属するか確認
    if payload.parent_id is not None:
        parent_node = await asyncio.to_thread(db.get_node, payload.parent_id)
        if parent_node is None or parent_node["topic_id"] != payload.topic_id:
            raise HTTPException(status_code=400, detail="parent_id が無効です")

    # 議論の文脈：祖先チェーンのみ（トークン節約）
    if payload.parent_id is not None:
        ancestor_nodes = await asyncio.to_thread(db.get_ancestor_chain, payload.parent_id)
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


@app.get("/nodes/{topic_id}")
async def get_nodes(topic_id: int):
    if await asyncio.to_thread(db.get_topic, topic_id) is None:
        raise HTTPException(status_code=404, detail="議題が見つかりません")
    return await asyncio.to_thread(db.get_nodes, topic_id)
