"""Slack などから受け取った音声ファイルを Whisper でテキスト化する。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent / ".env")


def transcribe_audio_file(path: Path, *, language: str | None = None) -> str:
    """ローカルファイルを Whisper で文字起こしする。language は省略時は自動判定。"""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY が設定されていません。")

    client = OpenAI(api_key=api_key)
    with path.open("rb") as f:
        kwargs: dict = {"model": "whisper-1", "file": f}
        if language:
            kwargs["language"] = language
        transcript = client.audio.transcriptions.create(**kwargs)
    text = (transcript.text or "").strip()
    if not text:
        raise RuntimeError("音声からテキストを得られませんでした。")
    return text
