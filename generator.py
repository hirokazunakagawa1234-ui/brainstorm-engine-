import os
import asyncio
from typing import Optional
from google import genai
from google.genai import types

_client: Optional[genai.Client] = None

PERSONAS = {
    "claude": """
        あなたは批評・本質抽出の専門家AIです。
        以下の4つの観点からアイデアを評価し、必ず下記フォーマットで回答してください。

        【評価観点】
        - 実現可能性：技術・リソース・時間的に実現できるか
        - コスト・リスク：想定されるコストや失敗リスクは何か
        - ユーザー視点：実際に使う人にとって価値があるか
        - 本質的課題：そもそもの前提や目的に問題はないか

        【回答フォーマット】
        ① 最も重大な弱点（観点を明示して具体的に）
        ② その根拠（なぜそれが問題か）
        ③ 改善提案（実行可能な具体策）

        簡潔に、日本語で回答してください。
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
            max_output_tokens=2048,
        ),
    )
    return persona, response.text


async def generate_all_responses(context: str, user_message: str):
    """3ペルソナを並列呼び出しして {persona: text} を返す。"""
    tasks = [_call_one(p, context, user_message) for p in PERSONAS]
    results = await asyncio.gather(*tasks)
    return dict(results)
