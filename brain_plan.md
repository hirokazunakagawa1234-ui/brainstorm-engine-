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
├── requirements.txt     # 依存パッケージ
├── render.yaml          # Renderデプロイ設定
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
| `claude` | ジョブズ（ビジョナリー） | 完璧主義・美意識・ビジョンで何が足りないかを鋭く指摘 | 2000 |
| `chatgpt` | 設計者 | 技術設計・手順分解 | 2048 |
| `chaos` | カオス | 前提崩し・奇抜な発想 | 2048 |

```python
PERSONAS = {
    "claude": """
        あなたはスティーブ・ジョブズの人格を持つビジョナリーAIです。
        以下の特徴で話してください。

        【人格】
        - 「それだけじゃ世界は変わらない」と常に上を求める完璧主義者
        - ユーザーは自分が何を欲しいか知らない。本当に必要なものを示すのがリーダーだと信じる
        - 細部へのこだわりと美意識を持ち、中途半端な発想を嫌う
        - 「これはinsanely greatか？」という基準で全てを判断する

        【回答スタイル】
        - 一人称で力強く語る（「いいか、」「本当に大切なのは、」）
        - アイデアの可能性を見抜き、何が足りないかを短く鋭く指摘する
        - 3〜4文で、シンプルかつ印象的に締める
        - 日本語で回答する
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
    """,
}

MAX_TOKENS = {
    "claude":  2000,
    "chatgpt": 2048,
    "chaos":   2048,
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
    parent_id  INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
    persona    TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

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
db.py: 議題・parent_id の存在確認（parent_id は同一トピック内か検証）
        ↓
db.py: 祖先チェーンを再帰CTE（1クエリ）で取得し文脈を構築
        ↓
generator.py: 各ペルソナ (claude / chatgpt / chaos) に対して
              asyncio.gather() で並列呼び出し（タイムアウト30秒）
        ↓  ← AI失敗時はここでHTTP 502を返し、DBへの書き込みは行わない
db.py: ユーザーノード＋3AIノードを単一トランザクションで保存
        ↓
フロントエンド: topic.html の JS がツリーを再描画
```

---

## 依存パッケージ（requirements.txt）

```
fastapi
uvicorn[standard]
google-genai
python-dotenv
jinja2
python-multipart
psycopg2-binary
```

---

## 環境変数（.env）

```
GEMINI_API_KEY=AIza...
DATABASE_URL=postgresql://user:password@ep-xxxx.neon.tech/neondb?sslmode=require
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
    envVars:
      - key: GEMINI_API_KEY
        sync: false
      - key: DATABASE_URL
        sync: false
```

---

## 注意事項

- Neon の無料プランは 0.5GB・永続ストレージ
- Neon はサーバーレスのためコールドスタートが発生することがある
- `psycopg2-binary` を使用（Render のビルド環境でコンパイル不要）
- Gemini API の無料枠は 15RPM（1投稿で3回呼び出しが発生するため注意）
- `.env` は `.gitignore` に追加し、絶対にコミットしない
- Render 無料プランは15分アイドルでスリープ（初回アクセスに30〜60秒かかる場合あり）

---

## 品質改善履歴（2026-03-26）

### 非同期・パフォーマンス
- 全 DB コールを `asyncio.to_thread()` でラップ → asyncエンドポイントのイベントループブロッキングを解消
- `SimpleConnectionPool` → `ThreadedConnectionPool` に変更（スレッドセーフ）
- `get_ancestor_chain` のN+1クエリを再帰CTE（`WITH RECURSIVE`）で1クエリに統合

### データ整合性
- ユーザーノード＋AIノードを `create_user_and_ai_nodes` で単一トランザクション化（クラッシュ時の孤立ノード防止）
- AI呼び出しをDB書き込みより前に実行（AI失敗時にDBへの書き込みを行わない）
- `parent_id` が同一トピックに属するか検証する処理を追加

### セキュリティ・バリデーション
- 入力長の上限を追加（`title`: 200字、`content`: 2000字）
- AI失敗時の502レスポンスから内部エラー文字列の露出を除去
- Gemini API 呼び出しに30秒タイムアウトを設定

### コード品質
- 未使用の `TopicCreate` モデルを削除
- `db.py` の冗長な `load_dotenv` を削除
- `TemplateResponse` の引数順序を新 Starlette API に合わせて修正

### テスト
- `test_main.py` を新規追加（21ケース：正常系・異常系・バリデーション・AI失敗・孤立ノード防止）
- `requirements-dev.txt` を作成しテスト依存（pytest・httpx・pytest-asyncio）を本番と分離

---

## 追加改善（2026-03-26 第2弾）

### 可用性・運用
- `GET /health` を実装（Render ヘルスチェック用）
- `db.ping()` を追加し `/health` で DB 疎通確認 → DB 障害時は 503 を返す
- `ThreadedConnectionPool` に `connect_timeout=10` を追加（Neon コールドスタート時のハング防止）

### パフォーマンス
- `POST /nodes` で `get_node` + `get_ancestor_chain` の二重 DB 呼び出しを解消
  → `get_ancestor_chain` の末尾ノードで `topic_id` 検証を兼ねることで1往復削減

### コード品質
- `db.create_node`（使われていたデッドコード）を削除
- `generator.py` のモデル名 `"gemini-2.5-flash"` を `MODEL_NAME` 定数に抽出

### テスト
- `/health` の正常系・DB障害系テストを追加（計 23 件）

---

## 追加改善（2026-03-28）

### バグ修正
- `generator.py`: `response.text` が `None`（安全フィルター等）の場合に RuntimeError を送出するよう修正
- `templates/topic.html`: `buildTree` で孤立ノード（親が存在しないノード）を roots にフォールバックするよう修正

### コード品質
- `db.py`: 未使用のデッドコード `get_node` を削除
- `requirements.txt`: 全パッケージをバージョンピン留め（再現性確保）

### バリデーション強化
- `models.py`: `NodeCreate.content` に `min_length=1` を追加
- `models.py`: `NodeCreate.topic_id` に `ge=1`（正数制約）を追加

### フロントエンド
- `index.html`: タイトル `<input>` に `maxlength="200"` を追加（即時フィードバック）
- `topic.html`: 本文 `<textarea>` に `maxlength="2000"` を追加
- `topic.html`: `loadTree()` に try/catch を追加（ネットワーク障害時の無限スピナー解消）
- `topic.html`: `submitPost()` でサーバーが返す `detail` メッセージをそのまま表示

### 運用
- `render.yaml`: `healthCheckPath: /health` を追加（Render が `/health` を監視）
