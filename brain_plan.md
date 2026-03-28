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
| AI API | Google Gemini API (gemini-2.5-flash) | 無料（15RPM・100万TPM） |

---

## ディレクトリ構成

```
brainstorm-engine/
├── main.py              # FastAPIエントリーポイント
├── generator.py         # AIペルソナ生成
├── models.py            # Pydanticモデル
├── db.py                # PostgreSQL操作（psycopg2 接続プール）
├── .env                 # GEMINI_API_KEY, DATABASE_URL（gitignore対象）
├── requirements.txt     # 本番依存パッケージ（バージョンピン留め）
├── requirements-dev.txt # テスト依存パッケージ（バージョンピン留め）
├── render.yaml          # Renderデプロイ設定
├── test_main.py         # 自動テスト（27ケース）
├── templates/
│   ├── index.html       # 議題一覧ページ
│   └── topic.html       # 議題詳細・ツリー表示ページ
└── static/
    └── .gitkeep
```

---

## ペルソナ設計

| ペルソナ | 役割 | 思考スタイル | 最大トークン |
|--------|------|------------|------------|
| `claude` | ジョブズ（ビジョナリー） | 完璧主義・美意識。指摘の後に「だからこそ〜すべきだ」で具体提案 | 8192 |
| `chatgpt` | 設計者 | 技術設計・手順分解。「〜という方法が考えられる」形で実装アイデアを提案 | 8192 |
| `chaos` | カオス | 前提崩し。崩した後に「だったら〜はどうか」で奇抜な具体案を提案 | 8192 |

```python
PERSONAS = {
    "claude": """
        あなたはスティーブ・ジョブズの人格を持つビジョナリーAIです。

        【人格】
        - 「それだけじゃ世界は変わらない」と常に上を求める完璧主義者
        - ユーザーは自分が何を欲しいか知らない。本当に必要なものを示すのがリーダーだと信じる
        - 細部へのこだわりと美意識を持ち、中途半端な発想を嫌う
        - 「これはinsanely greatか？」という基準で全てを判断する

        【回答スタイル】
        - 一人称で力強く語る（「いいか、」「本当に大切なのは、」）
        - 何が足りないかを鋭く指摘した上で、「だからこそ、〜すべきだ」という形で具体的なアイデアを必ず一つ提案する
        - 提案は抽象論ではなく、製品・体験・仕組みとして想像できる粒度にする
        - 3〜4文で、シンプルかつ印象的に締める
        - 日本語で回答する
    """,
    "chatgpt": """
        あなたは実装・構造思考が得意なAIです。
        議論を受けて、具体的な実装アイデアや仕組みを必ず一つ提案してください。
        提案は「〜という方法が考えられる」「〜を導入すると解決できる」など、
        実際に着手できる粒度で述べてください。
        返答は3〜5文で簡潔に。
    """,
    "chaos": """
        あなたは型破りな発想をするAIです。
        前提をぶち壊す視点を示した上で、「だったら〜というアイデアはどうか」という形で
        誰も思いつかない具体的なアイデアを必ず一つ提案してください。
        提案は奇抜でも構わないが、議題に関連していること。
        返答は3〜5文で簡潔に。
    """,
}
```

---

## ペルソナ別UI色分け

| ペルソナ | 色 | ラベル |
|--------|-----|--------|
| `user` | グレー | 🧑 You |
| `claude` | 青紫 | 💡 ジョブズ |
| `chatgpt` | 緑 | 🟢 設計者 |
| `chaos` | オレンジ | 🟠 カオス |

---

## DB設計（PostgreSQL / Neon）

### `topics` テーブル
```sql
CREATE TABLE IF NOT EXISTS topics (
    id         SERIAL PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_topics_created_at ON topics(created_at DESC);
```

### `nodes` テーブル（議論ツリーの各ノード）
```sql
CREATE TABLE IF NOT EXISTS nodes (
    id         SERIAL PRIMARY KEY,
    topic_id   INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    parent_id  INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
    persona    TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_nodes_topic_id  ON nodes(topic_id);
CREATE INDEX IF NOT EXISTS idx_nodes_parent_id ON nodes(parent_id);
```

---

## APIエンドポイント設計（FastAPI）

| Method | Path | 説明 |
|--------|------|------|
| `GET` | `/` | トップページ（議題一覧） |
| `GET` | `/health` | ヘルスチェック（DB疎通確認） |
| `POST` | `/topics` | 新しい議題を作成 |
| `GET` | `/topics/{topic_id}` | 議題詳細ページ（ツリー表示） |
| `POST` | `/nodes` | ユーザー投稿 → 全ペルソナが自動返答（10回/分 制限） |
| `GET` | `/nodes/{topic_id}` | ツリーデータをJSON取得（JS用） |

---

## 処理フロー

```
ユーザーが議題 or コメントを投稿
        ↓
main.py: POST /nodes を受信（slowapi で 10回/分 レート制限）
        ↓
db.py: 議題の存在確認 → parent_id が同一トピック内か検証
        ↓
db.py: 祖先チェーンを再帰CTE（1クエリ）で取得し文脈を構築
        ↓
generator.py: 各ペルソナ (claude / chatgpt / chaos) に対して
              asyncio.gather() で並列呼び出し（タイムアウト30秒）
        ↓  ← AI失敗時はここで HTTP 502 を返し、DBへの書き込みは行わない
db.py: ユーザーノード＋3AIノードを単一トランザクションで保存
        ↓
フロントエンド: topic.html の JS がツリーを再描画
```

---

## 依存パッケージ

### requirements.txt（本番・バージョンピン留め）
```
fastapi==0.115.0
uvicorn[standard]==0.30.6
google-genai==1.47.0
python-dotenv==1.0.1
Jinja2==3.1.4
python-multipart==0.0.12
psycopg2-binary==2.9.11
slowapi==0.1.9
```

### requirements-dev.txt（テスト・バージョンピン留め）
```
-r requirements.txt
pytest==8.3.3
httpx==0.28.1
pytest-asyncio==0.24.0
```

---

## 環境変数（.env）

```
GEMINI_API_KEY=AIza...
DATABASE_URL=postgresql://user:password@ep-xxxx.neon.tech/neondb?sslmode=require
RATELIMIT_ENABLED=true   # テスト時は false に設定
```

---

## Renderデプロイ設定

```yaml
services:
  - type: web
    name: brainstorm-engine
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /health
    envVars:
      - key: GEMINI_API_KEY
        sync: false
      - key: DATABASE_URL
        sync: false
```

---

## 注意事項

- Neon の無料プランは 0.5GB・永続ストレージ
- Neon はサーバーレスのためコールドスタートが発生することがある（`connect_timeout=10` で対策済み）
- `psycopg2-binary` を使用（Render のビルド環境でコンパイル不要）
- Gemini API の無料枠は 15RPM（1投稿で3回呼び出しが発生するため実質 5投稿/分 が上限）
- `.env` は `.gitignore` に追加し、絶対にコミットしない
- Render 無料プランは15分アイドルでスリープ（初回アクセスに30〜60秒かかる場合あり）
- `gemini-2.5-flash` は thinking tokens が出力トークンとは別計上されるため `max_output_tokens=8192` に設定

---

## 改善履歴

### 2026-03-26
- 全 DB コールを `asyncio.to_thread()` でラップ（イベントループブロッキング解消）
- `SimpleConnectionPool` → `ThreadedConnectionPool` に変更（スレッドセーフ）
- `get_ancestor_chain` の N+1 クエリを再帰 CTE で 1 クエリに統合
- ユーザーノード＋AIノードを単一トランザクション化（孤立ノード防止）
- `parent_id` の同一トピック検証を追加
- 入力長の上限を追加（`title`: 200字、`content`: 2000字）
- AI 失敗時の 502 レスポンスから内部エラー文字列の露出を除去
- Gemini API 呼び出しに 30 秒タイムアウトを設定
- `GET /health` を実装（DB 疎通確認・障害時 503）
- `ThreadedConnectionPool` に `connect_timeout=10` を追加
- `test_main.py` を新規追加（23 ケース）・`requirements-dev.txt` を分離

### 2026-03-28
- `response.text=None`（安全フィルター）時に RuntimeError を送出
- `max_output_tokens` を全ペルソナ 8192 に引き上げ（thinking tokens 別計上による途切れ対策）
- `finish_reason=MAX_TOKENS` 時にログ警告を出力
- `db.get_node` デッドコード削除
- `PooledConn` に `readonly` フラグ追加（読み取り時の不要 COMMIT を廃止）
- `PooledConn.__exit__` で rollback 失敗時に壊れた接続をプールから除去
- `SELECT *` を全クエリで明示カラム列挙に変更
- `nodes.topic_id` / `nodes.parent_id` / `topics.created_at` にインデックス追加
- `NodeCreate.content` に `min_length=1`、`topic_id` に `ge=1`、`parent_id` に `ge=1` を追加
- `slowapi` による `POST /nodes` レート制限（10回/分、`X-Forwarded-For` 対応）
- `import logging` をモジュールトップレベルに移動
- `index.html`: 送信中ボタン無効化、`maxlength="200"` 追加
- `topic.html`: `maxlength="2000"` 追加、`loadTree()` エラーハンドリング、429 日本語メッセージ
- `render.yaml`: `healthCheckPath: /health` 追加
- 全依存パッケージをバージョンピン留め
- テスト 27 ケースに拡充（`topic_id=0/-1`・`parent_id=0`・`response.text=None` を追加）
- 各ペルソナのプロンプトを「具体的なアイデア提案を必ず含める」形に改善
