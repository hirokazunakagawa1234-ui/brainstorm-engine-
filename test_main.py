import os
import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/test")
os.environ.setdefault("RATELIMIT_ENABLED", "false")

from main import app
from models import NodeCreate, CONTENT_MAX_LEN, TITLE_MAX_LEN
from pydantic import ValidationError

_dt = datetime(2026, 1, 1)
SAMPLE_TOPIC = {"id": 1, "title": "テスト議題", "created_at": _dt}
SAMPLE_NODE = {"id": 1, "topic_id": 1, "parent_id": None, "persona": "user",
               "content": "テスト投稿", "created_at": _dt}
SAMPLE_RESPONSES = {"claude": "ジョブズ応答", "chatgpt": "実装応答", "chaos": "カオス応答"}


@pytest.fixture
def client():
    with patch("db.init_pool"), patch("db.init_db"), patch("generator.init_client"):
        with TestClient(app) as c:
            yield c


# ── GET / ──────────────────────────────────────────────────────────────────────

def test_index_returns_html_with_topics(client):
    with patch("db.get_topics", return_value=[SAMPLE_TOPIC]):
        resp = client.get("/")
    assert resp.status_code == 200
    assert "テスト議題" in resp.text


# ── GET /topics ────────────────────────────────────────────────────────────────

# ── GET /health ───────────────────────────────────────────────────────────────

def test_health_ok(client):
    with patch("db.ping"):
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_db_down(client):
    with patch("db.ping", side_effect=Exception("connection refused")):
        resp = client.get("/health")
    assert resp.status_code == 503


def test_topics_redirects_to_root(client):
    resp = client.get("/topics", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/"


# ── POST /topics ───────────────────────────────────────────────────────────────

def test_create_topic_success(client):
    with patch("db.create_topic", return_value=1):
        resp = client.post("/topics", data={"title": "新しい議題"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/topics/1"


def test_create_topic_empty_title(client):
    resp = client.post("/topics", data={"title": "   "})
    assert resp.status_code == 400


def test_create_topic_title_too_long(client):
    resp = client.post("/topics", data={"title": "あ" * (TITLE_MAX_LEN + 1)})
    assert resp.status_code == 400


# ── GET /topics/{id} ──────────────────────────────────────────────────────────

def test_topic_detail_found(client):
    with patch("db.get_topic", return_value=SAMPLE_TOPIC):
        resp = client.get("/topics/1")
    assert resp.status_code == 200


def test_topic_detail_not_found(client):
    with patch("db.get_topic", return_value=None):
        resp = client.get("/topics/999")
    assert resp.status_code == 404


# ── GET /nodes/{topic_id} ─────────────────────────────────────────────────────

def test_get_nodes_success(client):
    with patch("db.get_topic", return_value=SAMPLE_TOPIC), \
         patch("db.get_nodes", return_value=[SAMPLE_NODE]):
        resp = client.get("/nodes/1")
    assert resp.status_code == 200
    assert resp.json()[0]["persona"] == "user"


def test_get_nodes_topic_not_found(client):
    with patch("db.get_topic", return_value=None):
        resp = client.get("/nodes/999")
    assert resp.status_code == 404


# ── POST /nodes ───────────────────────────────────────────────────────────────

def test_create_node_new_thread(client):
    with patch("db.get_topic", return_value=SAMPLE_TOPIC), \
         patch("generator.generate_all_responses",
               new_callable=AsyncMock, return_value=SAMPLE_RESPONSES), \
         patch("db.create_user_and_ai_nodes", return_value=10):
        resp = client.post("/nodes", json={"topic_id": 1, "content": "新スレッド投稿"})
    assert resp.status_code == 200
    assert resp.json()["user_node_id"] == 10


def test_create_node_reply(client):
    parent = {**SAMPLE_NODE, "id": 5, "topic_id": 1}
    with patch("db.get_topic", return_value=SAMPLE_TOPIC), \
         patch("db.get_ancestor_chain", return_value=[parent]), \
         patch("generator.generate_all_responses",
               new_callable=AsyncMock, return_value=SAMPLE_RESPONSES), \
         patch("db.create_user_and_ai_nodes", return_value=11):
        resp = client.post("/nodes", json={"topic_id": 1, "parent_id": 5, "content": "返信"})
    assert resp.status_code == 200
    assert resp.json()["user_node_id"] == 11


def test_create_node_empty_content(client):
    resp = client.post("/nodes", json={"topic_id": 1, "content": "   "})
    assert resp.status_code == 400


def test_create_node_content_too_long(client):
    resp = client.post("/nodes", json={"topic_id": 1, "content": "a" * (CONTENT_MAX_LEN + 1)})
    assert resp.status_code == 422  # pydantic バリデーションエラー


def test_create_node_topic_not_found(client):
    with patch("db.get_topic", return_value=None):
        resp = client.post("/nodes", json={"topic_id": 999, "content": "テスト"})
    assert resp.status_code == 404


def test_create_node_parent_belongs_to_different_topic(client):
    parent = {**SAMPLE_NODE, "id": 5, "topic_id": 99}  # 別トピック
    with patch("db.get_topic", return_value=SAMPLE_TOPIC), \
         patch("db.get_ancestor_chain", return_value=[parent]):
        resp = client.post("/nodes", json={"topic_id": 1, "parent_id": 5, "content": "テスト"})
    assert resp.status_code == 400


def test_create_node_parent_not_exist(client):
    with patch("db.get_topic", return_value=SAMPLE_TOPIC), \
         patch("db.get_ancestor_chain", return_value=[]):  # 空 = 存在しない
        resp = client.post("/nodes", json={"topic_id": 1, "parent_id": 999, "content": "テスト"})
    assert resp.status_code == 400


def test_create_node_ai_failure_returns_502(client):
    with patch("db.get_topic", return_value=SAMPLE_TOPIC), \
         patch("generator.generate_all_responses",
               new_callable=AsyncMock, side_effect=RuntimeError("secret api error")):
        resp = client.post("/nodes", json={"topic_id": 1, "content": "テスト"})
    assert resp.status_code == 502
    assert "secret api error" not in resp.text  # 内部エラーが露出しないこと


def test_create_node_ai_failure_does_not_write_to_db(client):
    with patch("db.get_topic", return_value=SAMPLE_TOPIC), \
         patch("generator.generate_all_responses",
               new_callable=AsyncMock, side_effect=RuntimeError("timeout")), \
         patch("db.create_user_and_ai_nodes") as mock_write:
        client.post("/nodes", json={"topic_id": 1, "content": "テスト"})
    mock_write.assert_not_called()  # AI失敗時はDBに書かれないこと


def test_create_node_topic_id_zero(client):
    resp = client.post("/nodes", json={"topic_id": 0, "content": "テスト"})
    assert resp.status_code == 422


def test_create_node_topic_id_negative(client):
    resp = client.post("/nodes", json={"topic_id": -1, "content": "テスト"})
    assert resp.status_code == 422


def test_create_node_parent_id_zero(client):
    resp = client.post("/nodes", json={"topic_id": 1, "parent_id": 0, "content": "テスト"})
    assert resp.status_code == 422


def test_create_node_ai_response_text_none(client):
    """AI が response.text=None を返したとき（安全フィルター等）502 になること"""
    with patch("db.get_topic", return_value=SAMPLE_TOPIC), \
         patch("generator.generate_all_responses",
               new_callable=AsyncMock,
               side_effect=RuntimeError("claude: AI応答のテキストが空でした（安全フィルター等の可能性）")):
        resp = client.post("/nodes", json={"topic_id": 1, "content": "テスト"})
    assert resp.status_code == 502
    assert "AI応答のテキストが空でした" not in resp.text  # 内部エラーが露出しないこと


# ── models ────────────────────────────────────────────────────────────────────

def test_node_create_valid():
    node = NodeCreate(topic_id=1, content="テスト")
    assert node.content == "テスト"
    assert node.parent_id is None


def test_node_create_content_at_max_length():
    node = NodeCreate(topic_id=1, content="a" * CONTENT_MAX_LEN)
    assert len(node.content) == CONTENT_MAX_LEN


def test_node_create_content_over_max_length():
    with pytest.raises(ValidationError):
        NodeCreate(topic_id=1, content="a" * (CONTENT_MAX_LEN + 1))
