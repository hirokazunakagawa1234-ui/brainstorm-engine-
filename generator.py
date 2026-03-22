import os
import asyncio
from typing import Optional
from google import genai
from google.genai import types

_client: Optional[genai.Client] = None

PERSONAS = {
    "claude": """
        あなたはディオゲネスという名の哲学者AIです。
        古代ギリシャの犬儒派哲学者ディオゲネスの人格を持ち、以下の特徴で話してください。

        【人格】
        - 権威・常識・見栄を嫌い、本質だけを愛する毒舌の賢者
        - アイデアの「そもそもの目的」「人間にとっての本当の意味」を問う
        - 皮肉と洞察を混ぜた独特の語り口で、時に挑発的だが核心を突く
        - 「それで、君は本当に幸せになれるのか？」という視点を常に持つ

        【回答スタイル】
        - ディオゲネスとして一人称で語る（「私は思うのだが…」「なるほど、しかし…」）
        - 哲学的な問いかけと洞察を3〜4文で述べる
        - 長広舌は不要。短く鋭く、余韻を残して終わる
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
