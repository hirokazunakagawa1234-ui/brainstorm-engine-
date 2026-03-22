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
db.py: ユーザーノードをDBに保存（Neon PostgreSQL）
        ↓
generator.py: 各ペルソナ (claude / chatgpt / chaos) に対して
              asyncio.gather() で並列呼び出し
        ↓
db.py: 3つのAIノードをDBに保存（parent_id = ユーザーノードID）
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
