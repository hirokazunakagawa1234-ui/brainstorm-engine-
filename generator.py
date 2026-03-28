import os
import asyncio
import logging
from typing import Optional
from google import genai
from google.genai import types
from google.api_core import exceptions as google_exceptions

logger = logging.getLogger(__name__)

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

_client: Optional[genai.Client] = None

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

# ペルソナごとの最大出力トークン数
# gemini-2.5-flash は思考トークンが別計上されるため、出力トークンを余裕を持って設定
MAX_TOKENS = {
    "claude":  8192,
    "chatgpt": 8192,
    "chaos":   8192,
}


def init_client():
    global _client
    _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def close_client():
    global _client
    _client = None


async def _call_one(persona: str, context: str, user_message: str):
    prompt = f"議論の文脈:\n{context}\n\n新しい投稿:\n{user_message}"
    try:
        response = await _client.aio.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=PERSONAS[persona],
                max_output_tokens=MAX_TOKENS[persona],
            ),
        )
    except google_exceptions.PermissionDenied:
        raise RuntimeError(f"{persona}: Gemini APIキーが無効または期限切れです")
    except google_exceptions.ResourceExhausted:
        raise RuntimeError(f"{persona}: Gemini APIのクォータを超過しました")
    except google_exceptions.InvalidArgument as e:
        raise RuntimeError(f"{persona}: APIリクエストが不正です: {e}")

    if response.text is None:
        raise RuntimeError(f"{persona}: AI応答のテキストが空でした（安全フィルター等の可能性）")
    candidate = response.candidates[0] if response.candidates else None
    if candidate and candidate.finish_reason.name == "MAX_TOKENS":
        logger.warning("%s: finish_reason=MAX_TOKENS（トークン上限到達）", persona)
    return persona, response.text


RESPONSE_TIMEOUT = 30  # seconds


async def generate_all_responses(context: str, user_message: str):
    """3ペルソナを並列呼び出しして {persona: text} を返す。"""
    tasks = [asyncio.ensure_future(_call_one(p, context, user_message)) for p in PERSONAS]
    try:
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=RESPONSE_TIMEOUT)
    except asyncio.TimeoutError:
        for t in tasks:
            t.cancel()
        raise RuntimeError(f"AI応答がタイムアウトしました（{RESPONSE_TIMEOUT}秒）")
    return dict(results)
