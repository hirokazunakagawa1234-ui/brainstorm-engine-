import os
import asyncio
from typing import Optional
from google import genai
from google.genai import types

_client: Optional[genai.Client] = None

PERSONAS = {
    "claude": """
        あなたはソクラテス式問答の達人AIです。
        アイデアの本質的な矛盾や見落としを、鋭い問いかけによって浮き彫りにしてください。
        答えを与えるのではなく、相手が自分で気づくような問いを3つ以内で投げかけてください。
        各問いは短く鋭く、日本語で3〜4文以内に収めてください。
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
