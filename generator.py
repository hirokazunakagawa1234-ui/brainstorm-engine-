import os
import asyncio
from typing import Optional
from google import genai
from google.genai import types

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

# ペルソナごとの最大出力トークン数
MAX_TOKENS = {
    "claude":  2000,
    "chatgpt": 2048,
    "chaos":   2048,
}


def init_client():
    global _client
    _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


async def _call_one(persona: str, context: str, user_message: str):
    prompt = f"議論の文脈:\n{context}\n\n新しい投稿:\n{user_message}"
    response = await _client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=PERSONAS[persona],
            max_output_tokens=MAX_TOKENS[persona],
        ),
    )
    return persona, response.text


async def generate_all_responses(context: str, user_message: str):
    """3ペルソナを並列呼び出しして {persona: text} を返す。"""
    tasks = [_call_one(p, context, user_message) for p in PERSONAS]
    results = await asyncio.gather(*tasks)
    return dict(results)
