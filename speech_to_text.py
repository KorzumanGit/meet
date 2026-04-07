"""マイク入力を SpeechRecognition でテキスト化する。"""

from __future__ import annotations

import speech_recognition as sr


def _ensure_pyaudio() -> None:
    try:
        import pyaudio  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "PyAudio がインストールされていません。macOS では次を実行してから "
            "`pip install pyaudio` してください: brew install portaudio"
        ) from e


def list_microphone_names() -> list[str | None]:
    """利用可能な入力デバイス名の一覧（SpeechRecognition / PyAudio 経由）。"""
    _ensure_pyaudio()
    return list(sr.Microphone.list_microphone_names())


def listen_and_transcribe(
    language: str = "ja-JP",
    phrase_time_limit: float | None = None,
    energy_threshold: int | None = None,
    device_index: int | None = None,
) -> str:
    """
    デフォルトマイクから音声を録音し、Google Web Speech API で認識する。
    phrase_time_limit: 秒。None の場合は無音まで待つ。
    device_index: None で既定のマイク。番号は `python main.py --list-mics` で確認。
    """
    _ensure_pyaudio()

    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 0.9
    if energy_threshold is not None:
        recognizer.energy_threshold = energy_threshold

    mic_kw: dict = {}
    if device_index is not None:
        mic_kw["device_index"] = device_index

    with sr.Microphone(**mic_kw) as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        audio = recognizer.listen(source, phrase_time_limit=phrase_time_limit)

    try:
        text = recognizer.recognize_google(audio, language=language)
    except sr.UnknownValueError:
        raise RuntimeError("音声を認識できませんでした。もう一度はっきり話してください。") from None
    except sr.RequestError as e:
        raise RuntimeError(f"音声認識サービスに接続できませんでした: {e}") from e

    return text.strip()
