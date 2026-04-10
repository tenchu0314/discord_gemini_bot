import os
import re
import asyncio
import discord
from google import genai
from google.genai import types
from dotenv import load_dotenv
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

# .envファイルがあれば読み込む（ローカルテスト用）
load_dotenv()

# 環境変数の取得
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not DISCORD_BOT_TOKEN or not GOOGLE_API_KEY:
    print("Error: DISCORD_BOT_TOKEN or GOOGLE_API_KEY is not set.")
    print("環境変数に DISCORD_BOT_TOKEN と GOOGLE_API_KEY を設定してください。")
    exit(1)

# Gemini クライアントの初期化
gemini_client = genai.Client(api_key=GOOGLE_API_KEY)


@retry(
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=lambda retry_state: print(
        f"Retrying Gemini API call (attempt {retry_state.attempt_number}/5)..."
    ),
)
def generate_content(prompt):
    """Gemini API にリクエストを送信 (リトライ機能付き)"""
    return gemini_client.models.generate_content(
        model="gemini-3.1-pro-preview",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[{"google_search": {}}],
        ),
    )


# Discord クライアントの初期化設定
intents = discord.Intents.default()
intents.message_content = True  # メッセージの内容を読み取るために必要
client = discord.Client(intents=intents)


def split_message(text, limit=2000):
    """Discordの2000文字制限に合わせてメッセージを分割する"""
    msgs = []
    # Discordの2000文字制限を超えないように分割
    while len(text) > 0:
        msgs.append(text[:limit])
        text = text[limit:]
    return msgs


def remove_thinking(text):
    """推論ブロック（<think>...</think> など）を除去する"""
    if not text:
        return ""
    # <think>...</think> や <thought>...</thought> のようなタグを中身ごと削除
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    return text.strip()


@client.event
async def on_ready():
    print(f"Logged in as {client.user} ({client.user.id})")
    print("Bot is ready and waiting for mentions!")


@client.event
async def on_message(message):
    # ボット自身のメッセージは無視
    if message.author == client.user:
        return

    # ボットへのメンションがあるか確認
    if client.user in message.mentions:
        # メッセージからメンション部分を削除してプロンプトを作成
        # 例: "@DiscordBot こんにちは" -> "こんにちは"
        prompt = message.content.replace(f"<@{client.user.id}>", "").strip()

        if not prompt:
            await message.channel.send(
                "何か質問を入力してください。（例: `@Botの名前 富士山の高さは？`）"
            )
            return

        # Discordの「入力中...」ステータスを表示
        async with message.channel.typing():
            try:
                # Gemini API にリクエストを送信 (ブロッキング処理を回避するため別スレッドで実行)
                response = await asyncio.to_thread(generate_content, prompt)

                # レスポンスから推論部分を削除
                reply_text = remove_thinking(response.text)

                if not reply_text:
                    reply_text = "（回答が空になりました）"

                # 2000文字制限で分割して送信
                for index, chunk in enumerate(split_message(reply_text)):
                    if index == 0:
                        # 最初のメッセージは返信として送信
                        await message.reply(chunk)
                    else:
                        # 続きのメッセージは通常の投稿として送信
                        await message.channel.send(chunk)

            except Exception as e:
                print(f"Error during Gemini API call: {e}")
                await message.reply(
                    "申し訳ありません、エラーが発生しました。ログを確認してください。"
                )


# ボットの起動
if __name__ == "__main__":
    client.run(DISCORD_BOT_TOKEN)
