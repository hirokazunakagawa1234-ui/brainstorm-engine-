# ブレインストーミング議論エンジン 設計計画

## プロジェクト概要

ユーザーが議題を投稿すると、複数のAIペルソナが自動的に議論を展開するWebアプリ。
ツリー構造で議論の流れを可視化し、インタラクティブなブレインストーミングを実現する。

---

## インフラ構成

| レイヤー | サービス | 無料枠 |
|--------|---------|--------|
| Web ホスティング | Render (Web Service) | 無料プラン |
| データベース | Neon (PostgreSQL) | 0.5GB・永続・無料 |
| AI API | Anthropic Claude API | 従量課金 |

**Neon を採用する理由：**
- サーバーレス PostgreSQL で永続ストレージが無料
- Render の環境変数に `DATABASE_URL` を設定するだけで接続可能
- ブランチ機能で開発/本番 DB を分離できる

---

## ディレクトリ構成

```
brainstorm-engine/
├── main.py              # FastAPIエントリーポイント
├── generator.py         # AIペルソナ生成
├── models.py            # Pydanticモデル
├── db.py                # PostgreSQL操作（psycopg2）
├── .env                 # ANTHROPIC_API_KEY, DATABASE_URL（gitignore対象）
├── requirements.txt     # 依存パッケージ
├── render.yaml          # Renderデプロイ設定
├── templates/
│   └── index.html       # Jinja2テンプレート
└── static/
    └── app.js           # ツリー描画・投稿処理
```

---

## ペルソナ設計

```python
PERSONAS = {
    "claude": """
        あなたは批判的・本質的な思考が得意なAIです。
        アイデアの弱点を指摘しつつ、改善案も必ず出してください。
        返答は3〜5文で簡潔に。
    """,
    "chatgpt": """
        あなたは実装・構造思考が得意なAIです。
        具体的な技術設計や手順に落とし込んでください。
        返答は3〜5文で簡潔に。
    """,
    "chaos": """
        あなたは型破りな発想をするAIです。
        前提をぶち壊す視点や、誰も思いつかない角度から意見を出してください。
        返答は3〜5文で簡潔に。
    """
}
```

| ペルソナ | 役割 | 思考スタイル |
|--------|------|------------|
| `claude` | 批評・本質抽出 | 弱点指摘 + 改善案提示 |
| `chatgpt` | 実装・構造化 | 技術設計・手順分解 |
| `chaos` | 破壊的創造 | 前提崩し・奇抜な発想 |

---

## DB設計（PostgreSQL / Neon）

### `topics` テーブル
```sql
CREATE TABLE topics (
    id         SERIAL PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### `nodes` テーブル（議論ツリーの各ノード）
```sql
CREATE TABLE nodes (
    id         SERIAL PRIMARY KEY,
    topic_id   INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    parent_id  INTEGER REFERENCES nodes(id) ON DELETE CASCADE,  -- NULLならルートノード
    persona    TEXT NOT NULL,                                    -- "user" | "claude" | "chatgpt" | "chaos"
    content    TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### SQLite との主な差分

| 項目 | SQLite（旧） | PostgreSQL（新） |
|------|------------|----------------|
| 自動採番 | `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` |
| 日時型 | `DATETIME` | `TIMESTAMP` |
| プレースホルダ | `?` | `%s` |
| 接続方法 | ファイルパス | 接続文字列（`DATABASE_URL`） |

---

## APIエンドポイント設計（FastAPI）

| Method | Path | 説明 |
|--------|------|------|
| `GET` | `/` | トップページ（議題一覧） |
| `POST` | `/topics` | 新しい議題を作成 |
| `GET` | `/topics/{topic_id}` | 議題詳細ページ（ツリー表示） |
| `POST` | `/nodes` | ユーザー投稿 → 全ペルソナが自動返答 |
| `GET` | `/nodes/{topic_id}` | ツリーデータをJSON取得（JS用） |

---

## 処理フロー

```
ユーザーが議題 or コメントを投稿
        ↓
main.py: POST /nodes を受信
        ↓
db.py: ユーザーノードをDBに保存（Neon PostgreSQL）
        ↓
generator.py: 各ペルソナ (claude / chatgpt / chaos) に対して
              Claude API を呼び出し（システムプロンプト切り替え）
        ↓
db.py: 3つのAIノードをDBに保存（parent_id = ユーザーノードID）
        ↓
フロントエンド: app.js がツリーを再描画
```

---

## db.py 設計

```python
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS topics (
                    id         SERIAL PRIMARY KEY,
                    title      TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS nodes (
                    id         SERIAL PRIMARY KEY,
                    topic_id   INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                    parent_id  INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
                    persona    TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

def create_topic(title: str) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO topics (title) VALUES (%s) RETURNING id", (title,))
            return cur.fetchone()[0]

def get_topics() -> list:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM topics ORDER BY created_at DESC")
            return cur.fetchall()

def create_node(topic_id: int, parent_id: int | None, persona: str, content: str) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO nodes (topic_id, parent_id, persona, content) VALUES (%s, %s, %s, %s) RETURNING id",
                (topic_id, parent_id, persona, content)
            )
            return cur.fetchone()[0]

def get_nodes(topic_id: int) -> list:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM nodes WHERE topic_id = %s ORDER BY created_at ASC",
                (topic_id,)
            )
            return cur.fetchall()
```

---

## generator.py 設計

```python
import anthropic

client = anthropic.Anthropic()  # ANTHROPIC_API_KEY は .env から自動読み込み

def generate_response(persona: str, context: str, user_message: str) -> str:
    """
    指定ペルソナでClaude APIを呼び出し、返答テキストを返す。

    Args:
        persona:      "claude" | "chatgpt" | "chaos"
        context:      議論のこれまでの流れ（スレッド全文）
        user_message: 今回のユーザー投稿

    Returns:
        AIの返答テキスト
    """
    system_prompt = PERSONAS[persona]
    messages = [
        {"role": "user", "content": f"議論の文脈:\n{context}\n\n新しい投稿:\n{user_message}"}
    ]
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text
```

---

## フロントエンド設計

### index.html（Jinja2）
- 議題一覧表示
- 新規議題投稿フォーム

### topics/{id}（Jinja2）
- ツリー状の議論表示
- ペルソナ別の色分け表示
- 各ノードへの返信フォーム

### app.js
- `GET /nodes/{topic_id}` でツリーデータ取得
- DOM操作でインデント付きツリーを描画
- 投稿フォームの非同期送信（fetch API）
- 投稿後に自動的にツリーを再描画

---

## ペルソナ別UI色分け

| ペルソナ | 色 | ラベル |
|--------|-----|--------|
| `user` | グレー | 🧑 You |
| `claude` | 青紫 | 🔵 批評家 |
| `chatgpt` | 緑 | 🟢 設計者 |
| `chaos` | オレンジ | 🟠 カオス |

---

## 依存パッケージ（requirements.txt）

```
fastapi
uvicorn[standard]
anthropic
python-dotenv
jinja2
python-multipart
psycopg2-binary
```

---

## 環境変数（.env）

```
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://user:password@ep-xxxx.neon.tech/neondb?sslmode=require
```

---

## 実装ステップ

1. **Neon セットアップ** — Neon コンソールでプロジェクト作成・`DATABASE_URL` を取得
2. **プロジェクト初期化** — ディレクトリ作成・`requirements.txt` 作成・`.env` 設定
3. **db.py** — PostgreSQL接続・`init_db()` / CRUD関数実装
4. **models.py** — Pydanticスキーマ定義
5. **generator.py** — ペルソナ別Claude API呼び出し実装
6. **main.py** — FastAPIルーティング・起動時に `init_db()` 呼び出し
7. **templates/index.html** — 議題一覧・ツリー表示UI
8. **static/app.js** — 非同期投稿・ツリー再描画
9. **動作確認** — ローカルで `uvicorn main:app --reload`
10. **Renderデプロイ** — `render.yaml` 作成・`DATABASE_URL` / `ANTHROPIC_API_KEY` を環境変数設定

---

## Renderデプロイ設定

```yaml
# render.yaml
services:
  - type: web
    name: brainstorm-engine
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: ANTHROPIC_API_KEY
        sync: false  # Renderダッシュボードで手動設定
      - key: DATABASE_URL
        sync: false  # Neon コンソールから取得した接続文字列を設定
```

---

## 注意事項

- Neon の無料プランは 0.5GB・永続ストレージ。本プロジェクトの用途では十分な容量
- Neon はサーバーレスのためコールドスタートが発生することがある（初回接続に数秒かかる場合あり）
- `psycopg2-binary` を使用（Render のビルド環境でコンパイル不要）
- Claude API のレートリミットに注意（1投稿で3回API呼び出しが発生）
- `.env` は `.gitignore` に追加し、絶対にコミットしない
