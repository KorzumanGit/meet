#!/usr/bin/env python3
"""
音声 → テキスト → OpenAI で日時抽出 → Google Calendar + Meet 作成。
タイムゾーン: Asia/Tokyo 固定。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import tkinter as tk
from tkinter import scrolledtext

from schedule_pipeline import run_schedule_pipeline
from speech_to_text import listen_and_transcribe, list_microphone_names


def main() -> int:
    parser = argparse.ArgumentParser(description="音声で予定登録 + Google Meet 発行")
    parser.add_argument(
        "--list-mics",
        action="store_true",
        help="利用可能なマイクの番号一覧を表示して終了する",
    )
    parser.add_argument(
        "--device-index",
        type=int,
        default=None,
        metavar="N",
        help="使うマイクの番号（--list-mics で確認。省略時は OS の既定マイク）",
    )
    parser.add_argument(
        "--text",
        type=str,
        default=None,
        help="デバッグ用: マイクを使わずこのテキストで処理する",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        help="OpenAI モデル名（既定: gpt-4o）",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="完了後に簡易ウィンドウでも結果を表示する",
    )
    args = parser.parse_args()

    if args.list_mics:
        try:
            names = list_microphone_names()
        except RuntimeError as e:
            print(f"エラー: {e}", file=sys.stderr)
            return 1
        print("入力デバイス一覧（--device-index で指定）:")
        for i, name in enumerate(names):
            label = name if name else "(名称なし)"
            print(f"  [{i}] {label}")
        return 0

    if args.text:
        spoken = args.text.strip()
        print(f"[入力テキスト] {spoken}\n")
    else:
        print("--- 音声入力モード ---", flush=True)
        print(
            "  1. 静かな環境で、マイクの許可を求められたら「許可」してください（"
            "システム設定 → プライバシーとセキュリティ → マイク）。",
            flush=True,
        )
        print(
            "  2. 次に環境ノイズを測定します。そのあと予定の内容を話してください。",
            flush=True,
        )
        print(
            '  3. 例:「明日の午後3時から企画ミーティング」。話し終えたら少し黙ってください。',
            flush=True,
        )
        print("録音待ち…\n", flush=True)
        try:
            spoken = listen_and_transcribe(device_index=args.device_index)
        except RuntimeError as e:
            print(f"エラー: {e}", file=sys.stderr)
            return 1
        print(f"認識結果: {spoken}\n")

    try:
        result = run_schedule_pipeline(spoken, model=args.model)
    except (EnvironmentError, ValueError, RuntimeError) as e:
        print(f"処理エラー: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    except Exception as e:
        print(f"カレンダー登録エラー: {e}", file=sys.stderr)
        return 1

    print(f"件名: {result.title}")
    print(f"開始: {result.start_iso}")
    print(f"終了: {result.end_iso}")
    kind_labels = {
        "task": "タスク（30分・Meet なし）",
        "meeting": "ミーティング（1時間・Meet 付き）",
        "calendar": "カレンダーのみ（1時間・Meet なし）",
    }
    print(f"種別: {kind_labels.get(result.kind, result.kind)}\n")

    print("--- 作成完了 ---")
    print(f"タイトル: {result.event_summary}")
    if result.kind == "task" or result.kind == "calendar":
        print("Google Meet: （この種別では発行していません）")
    elif result.meet_url:
        print(f"Google Meet: {result.meet_url}")
    else:
        print("Google Meet URL を取得できませんでした（管理者設定や API の制限の可能性があります）。")
    if result.calendar_link:
        print(f"カレンダーイベント: {result.calendar_link}")

    if args.gui:
        _show_result_gui(
            result.event_summary,
            result.meet_url,
            result.calendar_link,
            kind=result.kind,
        )

    return 0


def _show_result_gui(
    title: str,
    meet_url: str | None,
    html_link: str,
    *,
    kind: str = "meeting",
) -> None:
    root = tk.Tk()
    root.title("予定を作成しました")
    root.geometry("520x220")
    root.resizable(True, True)

    frame = tk.Frame(root, padx=12, pady=12)
    frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(frame, text="件名", font=("Helvetica", 11, "bold")).pack(anchor=tk.W)
    text = scrolledtext.ScrolledText(frame, height=3, wrap=tk.WORD, font=("Helvetica", 12))
    text.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
    text.insert(tk.END, title)
    text.configure(state=tk.DISABLED)

    lines = []
    if kind == "task" or kind == "calendar":
        lines.append("Google Meet: （この種別では発行していません）")
    elif meet_url:
        lines.append(f"Google Meet:\n{meet_url}")
    else:
        lines.append("Google Meet URL は取得できませんでした。")
    if html_link:
        lines.append(f"\nカレンダー:\n{html_link}")

    tk.Label(frame, text="リンク", font=("Helvetica", 11, "bold")).pack(anchor=tk.W)
    links = scrolledtext.ScrolledText(frame, height=6, wrap=tk.WORD, font=("Helvetica", 11))
    links.pack(fill=tk.BOTH, expand=True)
    links.insert(tk.END, "\n".join(lines))
    links.configure(state=tk.DISABLED)

    tk.Button(frame, text="閉じる", command=root.destroy).pack(pady=(8, 0))
    root.mainloop()


if __name__ == "__main__":
    raise SystemExit(main())
