/**
 * iOS ショートカット / Siri からの音声テキストを受け、Google Meet 付きカレンダー登録と Slack 通知を行う API。
 *
 * ## 必要な Google OAuth スコープ（リフレッシュトークン取得時に指定）
 * - https://www.googleapis.com/auth/calendar.events
 *
 * Meet リンク: events.insert で conferenceDataVersion: 1 と
 * conferenceData.createRequest（conferenceSolutionKey: hangoutsMeet）
 *
 * 日時解析: chrono-node の日本語ロケール（`ja`）+ dayjs（Asia/Tokyo）
 */

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import axios from "axios";
import type { OAuth2Client } from "google-auth-library";
import dayjs from "dayjs";
import "dayjs/locale/ja";
import timezone from "dayjs/plugin/timezone";
import utc from "dayjs/plugin/utc";
import { ja } from "chrono-node";
import cors from "cors";
import dotenv from "dotenv";
import express, { type Request, type Response } from "express";
import { google, type calendar_v3 } from "googleapis";

// cwd に依存せず ios-shortcut-api/.env を読む（start_services 以外の起動でも SLACK_* 等が効く）
dotenv.config({ path: path.join(__dirname, "..", ".env") });

dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.locale("ja");

const TZ = "Asia/Tokyo";

/** Meet 発行結果を投稿する既定チャンネル（上書き: 環境変数 SLACK_CHANNEL_ID） */
const DEFAULT_SLACK_CHANNEL_ID = "C0AR1VBT3ED";

// ---------------------------------------------------------------------------
// 日時解析: chrono-node (ja) + フォールバック
// ---------------------------------------------------------------------------

export interface ParsedWindow {
  start: dayjs.Dayjs;
  end: dayjs.Dayjs;
  summary: string;
}

/**
 * 音声入力や IME 由来の全角数字（１３）などを半角にし、chrono / 正規表現が読めるようにする。
 */
function stripNoise(text: string): string {
  return text.normalize("NFKC").replace(/\s+/g, " ").trim();
}

/** 終了が未指定のときのデフォルト（分）— ミーティングは 1 時間単位 */
const DEFAULT_DURATION_MIN = 60;

/** Google カレンダー API のイベント色（5 = 黄） */
const MEET_EVENT_COLOR_ID = "5";
/** タスク枠（Meet なし）用（9 = 青） */
const TASK_EVENT_COLOR_ID = "9";

/** 「から30分」「1時間」など */
function parseDurationMinutes(text: string): number {
  const h = text.match(/(\d+)\s*時間/);
  if (h) return parseInt(h[1], 10) * 60;
  const m = text.match(/(\d+)\s*分(?:間)?/);
  if (m) return parseInt(m[1], 10);
  return DEFAULT_DURATION_MIN;
}

/**
 * 件名: 日時・接続詞を除いた残り（例: 「明日の13時に田中さんと打ち合わせ」→「田中さんと打ち合わせ」）
 */
function extractSummary(raw: string): string {
  let s = raw.trim();
  s = s.replace(/明日の|今日の|明後日の|明々後日の|昨日の|一昨日の|来週の|今週の|先週の/g, " ");
  s = s.replace(
    /今日|明日|明後日|明々後日|一昨日|昨日|来週|今週|先週/g,
    " "
  );
  s = s.replace(
    /月曜日?|火曜日?|水曜日?|木曜日?|金曜日?|土曜日?|日曜日?/g,
    " "
  );
  // 「4月5日の」「5日の」など日付表現を件名から除外（「1月5日」のうち 5日 だけ消さないよう (?<![月]) を単独 N日 に使用）
  s = s.replace(/\d{1,2}\s*月\s*\d{1,2}\s*日の?/g, " ");
  s = s.replace(/(?<![月])\d{1,2}\s*日の?/g, " ");
  s = s.replace(/午前|午後|AM|PM|am|pm/g, " ");
  s = s.replace(/\d{1,2}\s*時(?:(\d{1,2})\s*分)?に?/g, " ");
  s = s.replace(/から|まで|間|約/g, " ");
  s = s.replace(/\d+\s*(分|時間)(?:間)?/g, " ");
  s = s.replace(/を組んで|を組む|をセットして/g, " ");
  s = s.replace(
    /というタスクを入れて|のタスクを入れて|タスクを入れて|というタスク|という予定を入れて|の予定を入れて|予定を入れて|スケジュールを入れて/g,
    " "
  );
  s = s.replace(/\s+/g, " ").trim();
  s = s.replace(/^に\s+/g, "").trim();
  if (s.length < 2) return "ミーティング";
  return s.slice(0, 120);
}

/** 発話に「タスク」「予定」があればタスク枠（30分・Meet なし）。「スケジュールを入れて」も同趣旨。 */
function isTaskCalendarIntent(text: string): boolean {
  const t = stripNoise(text).normalize("NFKC");
  if (t.includes("タスク") || t.includes("たすく")) return true;
  if (t.includes("予定") || t.includes("よてい")) return true;
  if (/(?:スケジュール|すけじゅーる)\s*(?:を\s*)?(?:入れて|追加して|登録して|いれて)/.test(t)) {
    return true;
  }
  return false;
}

/** Meet リンクを付けるのはミーティング系ワードがあるときのみ（Google Meet / meets / ミーツ 等） */
function isMeetingMeetIntent(text: string): boolean {
  const t = stripNoise(text).normalize("NFKC");
  return /ミーティング|打ち合わせ|会議|Google\s*Meet|グーグル\s*Meet|ミーツ|Meets|Meet|MEET|meet|MTG|mtg|Zoom|zoom|ズーム|オンライン会議|Web会議|Teams|teams|Webミーティング|ウェブミーティング/i.test(
    t
  );
}

/** 月なし「N日」: 参照日以降で最も近い N 日（当月で過ぎていれば翌月） */
function nextOccurrenceDayOfMonth(ref: dayjs.Dayjs, dayOfMonth: number): dayjs.Dayjs {
  let t = ref.clone().tz(TZ).startOf("day").date(dayOfMonth);
  if (t.date() !== dayOfMonth) {
    t = ref.clone().tz(TZ).endOf("month").startOf("day");
  }
  if (t.isBefore(ref.clone().tz(TZ).startOf("day"))) {
    t = t.add(1, "month").date(dayOfMonth);
    if (t.date() !== dayOfMonth) {
      t = t.endOf("month").startOf("day");
    }
  }
  return t;
}

/**
 * chrono が拾わない「5日の16時」のような月なし・日のみ + 時刻
 */
function tryParseDayOfMonthWithTime(raw: string, refTokyo: dayjs.Dayjs): ParsedWindow | null {
  if (/\d{1,2}\s*月\s*\d{1,2}\s*日/.test(raw)) {
    return null;
  }
  const re =
    /(?<![月])(\d{1,2})\s*日\s*(?:の\s*)?(?:(午前|午後|AM|PM|am|pm)\s*)?(\d{1,2})\s*時(?:\s*(\d{1,2})\s*分)?/i;
  const m = raw.match(re);
  if (!m) {
    return null;
  }
  const dayOfMonth = parseInt(m[1], 10);
  const ampm = m[2];
  let h = parseInt(m[3], 10);
  const minute = m[4] ? parseInt(m[4], 10) : 0;
  if (dayOfMonth < 1 || dayOfMonth > 31 || minute > 59) {
    return null;
  }
  if (!ampm && h > 23) {
    return null;
  }
  if (ampm) {
    if (ampm === "午後" || ampm.toLowerCase() === "pm") {
      if (h < 12) h += 12;
    } else if (ampm === "午前" || ampm.toLowerCase() === "am") {
      if (h === 12) h = 0;
    }
  }

  const dayStart = nextOccurrenceDayOfMonth(refTokyo, dayOfMonth);
  const start = dayStart.hour(h).minute(minute).second(0).millisecond(0);

  const dur = parseDurationMinutes(raw);
  let end = start.add(dur, "minute");
  if (end.isBefore(start) || end.isSame(start)) {
    end = start.add(DEFAULT_DURATION_MIN, "minute");
  }

  if (start.isBefore(refTokyo.subtract(1, "minute"))) {
    throw new Error("開始時刻が過去になっています。日付・時刻を確認してください");
  }

  return { start, end, summary: extractSummary(raw) };
}

/** chrono 失敗時用レガシー（簡易日本語） */
function parseMeetingLegacy(text: string): ParsedWindow {
  const raw = stripNoise(text);
  if (!raw) throw new Error("テキストが空です");

  const nowTokyo = dayjs().tz(TZ);
  const fromDayOnly = tryParseDayOfMonthWithTime(raw, nowTokyo);
  if (fromDayOnly) {
    return fromDayOnly;
  }
  let d = nowTokyo.tz(TZ).startOf("day");
  if (/明後日/.test(raw)) d = d.add(2, "day");
  else if (/明日/.test(raw)) d = d.add(1, "day");
  else if (/今日/.test(raw)) d = d.add(0, "day");

  const m1 = raw.match(/(?:午前|AM|am)?\s*(\d{1,2})\s*時\s*(?:(\d{1,2})\s*分)?/);
  if (!m1) {
    throw new Error(
      "開始時刻が読み取れません（例: 明日15時、今日18時30分、来週月曜の午後3時）。全角の１３時も利用できます。"
    );
  }
  let hour = parseInt(m1[1], 10);
  const minute = m1[2] ? parseInt(m1[2], 10) : 0;
  if (/午後|PM|pm/.test(raw) && hour < 12) hour += 12;
  if (/午前/.test(raw) && hour === 12) hour = 0;

  let start = d.hour(hour).minute(minute).second(0).millisecond(0);
  const durationMin = parseDurationMinutes(raw);
  let end = start.add(durationMin, "minute");
  if (end.isBefore(start) || end.isSame(start)) end = start.add(DEFAULT_DURATION_MIN, "minute");

  if (start.isBefore(nowTokyo.subtract(1, "minute"))) {
    throw new Error("開始時刻が過去になっています。日付・時刻を確認してください");
  }

  return { start, end, summary: extractSummary(raw) };
}

/**
 * chrono-node（日本語）で日時を解釈し、開始・終了を dayjs(Asia/Tokyo) で返す。
 * 件名はテキストから日時表現を除いて抽出する。
 */
export function parseMeetingFromText(text: string): ParsedWindow {
  const raw = stripNoise(text);
  if (!raw) throw new Error("テキストが空です");

  const refTokyo = dayjs().tz(TZ);
  const fromDayOnly = tryParseDayOfMonthWithTime(raw, refTokyo);
  if (fromDayOnly) {
    return fromDayOnly;
  }

  const refInstant = new Date();
  const results = ja.parse(
    raw,
    { instant: refInstant, timezone: TZ },
    { forwardDate: true }
  );

  if (results.length > 0 && results[0].start) {
    const pr = results[0];
    const startJs = pr.start.date();
    let start = dayjs(startJs).tz(TZ);
    let end: dayjs.Dayjs;

    if (pr.end) {
      end = dayjs(pr.end.date()).tz(TZ);
    } else {
      const dur = parseDurationMinutes(raw);
      end = start.add(dur, "minute");
    }

    if (end.isBefore(start) || end.isSame(start)) {
      end = start.add(DEFAULT_DURATION_MIN, "minute");
    }

    if (start.isBefore(refTokyo.subtract(1, "minute"))) {
      throw new Error("開始時刻が過去になっています。日付・時刻を確認してください");
    }

    return { start, end, summary: extractSummary(raw) };
  }

  return parseMeetingLegacy(raw);
}

/** @deprecated 互換用エイリアス */
export const parseMeetingFromJapanese = parseMeetingFromText;

// ---------------------------------------------------------------------------
// Google Calendar + Slack (axios)
// ---------------------------------------------------------------------------

const SLACK_USER_ID_RE = /^U[A-Za-z0-9]+$/;

/** コンテナ内: /usr/src/data/google_tokens（ホストの meet/data をマウント） */
function googleTokensDirectory(): string {
  const d = process.env.GOOGLE_TOKENS_DIR?.trim();
  if (d) {
    return path.isAbsolute(d) ? d : path.resolve(process.cwd(), d);
  }
  return path.resolve(process.cwd(), "..", "data", "google_tokens");
}

function tokenJsonPathForSlackUser(slackUserId: string): string {
  return path.join(googleTokensDirectory(), `${slackUserId}.json`);
}

/** meet/data/google_tokens/*.json と同じ形式（refresh_token, client_id, client_secret） */
function readGoogleCredentialsFromTokenJsonFile(full: string): {
  clientId: string;
  clientSecret: string;
  refreshToken: string;
} {
  if (!fs.existsSync(full)) {
    throw new Error(`Google トークン JSON が見つかりません: ${full}`);
  }
  const raw = JSON.parse(fs.readFileSync(full, "utf8")) as {
    refresh_token?: string;
    client_id?: string;
    client_secret?: string;
  };
  if (!raw.refresh_token) {
    throw new Error(`トークン JSON に refresh_token がありません: ${full}`);
  }
  const clientId = raw.client_id || process.env.GOOGLE_CLIENT_ID || "";
  const clientSecret = raw.client_secret || process.env.GOOGLE_CLIENT_SECRET || "";
  if (!clientId || !clientSecret) {
    throw new Error(
      "トークン JSON 使用時は JSON 内の client_id / client_secret、または .env の GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET が必要です"
    );
  }
  return {
    clientId,
    clientSecret,
    refreshToken: raw.refresh_token,
  };
}

/**
 * Google 資格情報を解決する。
 * - `slackUserId` あり: `GOOGLE_TOKENS_DIR`（既定: ../data/google_tokens）/ `<U>.json`
 * - なし: `GOOGLE_TOKEN_FILE` または env の refresh_token（従来どおり）
 */
function loadGoogleCredentials(slackUserId?: string | null): {
  clientId: string;
  clientSecret: string;
  refreshToken: string;
} {
  const id = slackUserId?.trim();
  if (id) {
    if (!SLACK_USER_ID_RE.test(id)) {
      throw new Error(`不正な slack_user_id: ${id}`);
    }
    const full = tokenJsonPathForSlackUser(id);
    return readGoogleCredentialsFromTokenJsonFile(full);
  }

  const tokenFile = process.env.GOOGLE_TOKEN_FILE?.trim();
  if (tokenFile) {
    const full = path.isAbsolute(tokenFile)
      ? tokenFile
      : path.resolve(process.cwd(), tokenFile);
    return readGoogleCredentialsFromTokenJsonFile(full);
  }

  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  const refreshToken = process.env.GOOGLE_REFRESH_TOKEN;
  if (!clientId || !clientSecret || !refreshToken) {
    throw new Error(
      "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN を設定するか、GOOGLE_TOKEN_FILE でトークン JSON を指定してください"
    );
  }
  return { clientId, clientSecret, refreshToken };
}

function getOAuthClient(slackUserId?: string | null): OAuth2Client {
  const { clientId, clientSecret, refreshToken } = loadGoogleCredentials(slackUserId);
  const oauth2 = new google.auth.OAuth2(clientId, clientSecret);
  oauth2.setCredentials({ refresh_token: refreshToken });
  return oauth2;
}

/** refresh_token が利用可能か。`slackUserId` 指定時はそのユーザーの JSON のみを見る（グローバル .env にフォールバックしない）。 */
function hasGoogleCredentialsConfigured(slackUserId?: string | null): boolean {
  const id = slackUserId?.trim();
  if (id) {
    if (!SLACK_USER_ID_RE.test(id)) return false;
    try {
      const full = tokenJsonPathForSlackUser(id);
      if (!fs.existsSync(full)) return false;
      const raw = JSON.parse(fs.readFileSync(full, "utf8")) as { refresh_token?: string };
      return !!raw.refresh_token;
    } catch {
      return false;
    }
  }
  const f = process.env.GOOGLE_TOKEN_FILE?.trim();
  if (f) {
    const full = path.isAbsolute(f) ? f : path.resolve(process.cwd(), f);
    if (!fs.existsSync(full)) return false;
    try {
      const raw = JSON.parse(fs.readFileSync(full, "utf8")) as { refresh_token?: string };
      return !!raw.refresh_token;
    } catch {
      return false;
    }
  }
  return !!process.env.GOOGLE_REFRESH_TOKEN?.trim();
}

/**
 * C0AR1VBT3ED への実行結果通知で、未設定時に @daisuke_kouzuma 相当とする Slack メンバー ID（上書き: SLACK_CHANNEL_RESULT_MENTION_USER_ID）
 */
const SLACK_CHANNEL_C0AR1VBT3ED_DEFAULT_MENTION_USER_ID = "U04GPG87CKA";

/**
 * 実行結果を Slack に返すときの先頭メンション。
 * 投稿先が C0AR1VBT3ED のときのみ付与（@daisuke_kouzuma。Slack 上は <@U...>）。
 * 優先: SLACK_CHANNEL_RESULT_MENTION_USER_ID → SLACK_SHORTCUT_NOTIFY_USER_ID → SLACK_OAUTH_USER_ID → 上記デフォルト
 */
function slackResultMentionPrefix(): string {
  const channel = process.env.SLACK_CHANNEL_ID?.trim() || DEFAULT_SLACK_CHANNEL_ID;
  if (channel !== "C0AR1VBT3ED") {
    return "";
  }
  const id =
    process.env.SLACK_CHANNEL_RESULT_MENTION_USER_ID?.trim() ||
    process.env.SLACK_SHORTCUT_NOTIFY_USER_ID?.trim() ||
    process.env.SLACK_OAUTH_USER_ID?.trim() ||
    SLACK_CHANNEL_C0AR1VBT3ED_DEFAULT_MENTION_USER_ID;
  if (id && SLACK_USER_ID_RE.test(id)) {
    return `<@${id}> `;
  }
  return "";
}

function isInsufficientScopeForCalendarsGet(e: unknown): boolean {
  const err = e as {
    code?: number;
    response?: { status?: number; data?: { error?: { errors?: { reason?: string }[] } } };
  };
  if (err?.code === 403 || err?.response?.status === 403) return true;
  const errors = err?.response?.data?.error?.errors;
  return Array.isArray(errors) && errors.some((x) => x?.reason === "insufficientPermissions");
}

/**
 * .env の GOOGLE_CALENDAR_OWNER_EMAIL と、トークンが指す primary カレンダーが一致するか検証する。
 * calendar.events のみのトークンでは calendars.get が 403 になるため、その場合は警告してスキップ（所有者検証に calendar.readonly を OAuth で追加すると検証可能）。
 * @returns 検証できた場合 true、スコープ不足でスキップした場合 false
 */
async function assertCalendarOwnerMatches(auth: OAuth2Client): Promise<boolean> {
  const want = process.env.GOOGLE_CALENDAR_OWNER_EMAIL?.trim();
  if (!want) {
    throw new Error(
      "GOOGLE_CALENDAR_OWNER_EMAIL を .env に必ず設定してください（例: daisuke.k@humbull.co）。未設定では誤ったアカウントに書き込む可能性があります。"
    );
  }

  const cal = google.calendar({ version: "v3", auth });
  try {
    const { data } = await cal.calendars.get({ calendarId: "primary" });
    const ownerId = (data.id || "").toLowerCase();
    const expected = want.toLowerCase();
    if (ownerId !== expected) {
      throw new Error(
        `このトークンの primary カレンダーは「${data.id}」です。GOOGLE_CALENDAR_OWNER_EMAIL は「${want}」です。` +
          `一致させるには、${want} で Google 連携した refresh_token を設定してください。` +
          `GOOGLE_TOKEN_FILE を使う場合は、meet/data/google_tokens/ のうち「${want} が Slack から OAuth した」JSON のパスに差し替えてください（別ユーザーの JSON のままだと他人のカレンダーになります）。`
      );
    }
    return true;
  } catch (e) {
    if (isInsufficientScopeForCalendarsGet(e)) {
      console.warn(
        "calendars.get(primary) をスキップ（スコープ不足）。予定の作成（events.insert）は続行します。所有者検証が必要なら calendar.readonly を OAuth で追加してください。"
      );
      return false;
    }
    throw e;
  }
}

/**
 * Calendar API 推奨: オフセット付き UTC（toISOString）と timeZone を併用すると timeZone が無視され、
 * 表示や Meet 紐付けがずれることがある。壁時計 + timeZone のみ渡す。
 * @see https://developers.google.com/calendar/api/v3/reference/events
 */
function toGoogleCalendarDateTime(d: dayjs.Dayjs): calendar_v3.Schema$EventDateTime {
  const local = d.tz(TZ);
  return {
    dateTime: local.format("YYYY-MM-DDTHH:mm:ss"),
    timeZone: TZ,
  };
}

function logGoogleApiError(e: unknown): string {
  if (e && typeof e === "object" && "response" in e) {
    const data = (e as { response?: { data?: unknown } }).response?.data;
    if (data !== undefined) return JSON.stringify(data);
  }
  return e instanceof Error ? e.message : String(e);
}

/** Calendar API が返す参加 URL（meet.google.com 等）を優先して抽出 */
function extractMeetJoinUrlFromEvent(data: calendar_v3.Schema$Event): string | null {
  const top = data.hangoutLink?.trim();
  if (top) return top;
  const eps = data.conferenceData?.entryPoints ?? [];
  for (const ep of eps) {
    const u = ep.uri?.trim();
    if (u && /meet\.google\.com|meetings\.google\.com/i.test(u)) {
      return u;
    }
  }
  const video = eps.find((e) => e.entryPointType === "video")?.uri?.trim();
  if (video) return video;
  const cd = data.conferenceData as { hangoutLink?: string | null } | undefined;
  if (cd?.hangoutLink?.trim()) return cd.hangoutLink.trim();
  return null;
}

async function createMeetEvent(params: {
  summary: string;
  start: dayjs.Dayjs;
  end: dayjs.Dayjs;
  /** 指定時はその Slack ユーザー用トークンを使用し、GOOGLE_CALENDAR_OWNER_EMAIL との照合は行わない */
  slackUserId?: string;
}): Promise<{ eventId: string; hangoutLink: string | null | undefined; htmlLink: string | null | undefined }> {
  if (!params.end.isAfter(params.start)) {
    throw new Error("終了時刻は開始時刻より後である必要があります");
  }

  const auth = getOAuthClient(params.slackUserId);
  if (!params.slackUserId) {
    await assertCalendarOwnerMatches(auth);
  }

  const cal = google.calendar({ version: "v3", auth });
  const calendarId =
    process.env.GOOGLE_CALENDAR_ID?.trim() || "primary";

  const requestId = crypto.randomUUID();

  const body: calendar_v3.Schema$Event = {
    summary: params.summary,
    colorId: MEET_EVENT_COLOR_ID,
    start: toGoogleCalendarDateTime(params.start),
    end: toGoogleCalendarDateTime(params.end),
    reminders: { useDefault: true },
    conferenceData: {
      createRequest: {
        requestId,
        conferenceSolutionKey: { type: "hangoutsMeet" },
      },
    },
  };

  let res;
  try {
    res = await cal.events.insert({
      calendarId,
      conferenceDataVersion: 1,
      requestBody: body,
    });
  } catch (e) {
    throw new Error(`Google Calendar events.insert 失敗: ${logGoogleApiError(e)}`);
  }

  const data = res.data;
  if (!data.id) {
    throw new Error("Google Calendar が event id を返しませんでした");
  }

  const hangoutLink = extractMeetJoinUrlFromEvent(data);

  return {
    eventId: data.id,
    hangoutLink,
    htmlLink: data.htmlLink,
  };
}

async function createCalendarEventWithoutConference(params: {
  summary: string;
  start: dayjs.Dayjs;
  end: dayjs.Dayjs;
  slackUserId?: string;
}): Promise<{ eventId: string; htmlLink: string | null | undefined }> {
  if (!params.end.isAfter(params.start)) {
    throw new Error("終了時刻は開始時刻より後である必要があります");
  }

  const auth = getOAuthClient(params.slackUserId);
  if (!params.slackUserId) {
    await assertCalendarOwnerMatches(auth);
  }

  const cal = google.calendar({ version: "v3", auth });
  const calendarId =
    process.env.GOOGLE_CALENDAR_ID?.trim() || "primary";

  const body: calendar_v3.Schema$Event = {
    summary: params.summary,
    colorId: TASK_EVENT_COLOR_ID,
    start: toGoogleCalendarDateTime(params.start),
    end: toGoogleCalendarDateTime(params.end),
    reminders: { useDefault: true },
  };

  let res;
  try {
    res = await cal.events.insert({
      calendarId,
      requestBody: body,
    });
  } catch (e) {
    throw new Error(`Google Calendar events.insert 失敗: ${logGoogleApiError(e)}`);
  }

  const data = res.data;
  if (!data.id) {
    throw new Error("Google Calendar が event id を返しませんでした");
  }

  return { eventId: data.id, htmlLink: data.htmlLink };
}

/** Slack 用: 開始 〜 終了（東京、同一日は終了は HH:mm） */
function formatSlackDatetimeRange(start: dayjs.Dayjs, end: dayjs.Dayjs): string {
  const s = start.tz(TZ).format("YYYY-MM-DD HH:mm");
  const endTokyo = end.tz(TZ);
  const e = endTokyo.isSame(start.tz(TZ), "day")
    ? endTokyo.format("HH:mm")
    : endTokyo.format("YYYY-MM-DD HH:mm");
  return `${s} 〜 ${e}`;
}

function buildSlackMessage(params: {
  summary: string;
  start: dayjs.Dayjs;
  end: dayjs.Dayjs;
  meetUrl: string;
  calendarUrl?: string | null;
}): string {
  const when = formatSlackDatetimeRange(params.start, params.end);
  const calLine =
    params.calendarUrl != null && params.calendarUrl !== ""
      ? `📅 Google カレンダー: ${params.calendarUrl}\n`
      : "";
  return (
    `🗓️ 会議をセットしました\n` +
    `👤 件名: ${params.summary}\n` +
    `⏰ 日時: ${when} (${TZ})\n` +
    calLine +
    `🔗 Google Meet: ${params.meetUrl}`
  );
}

function buildTaskSlackMessage(params: {
  summary: string;
  start: dayjs.Dayjs;
  end: dayjs.Dayjs;
  calendarUrl?: string | null;
}): string {
  const when = formatSlackDatetimeRange(params.start, params.end);
  const calLine =
    params.calendarUrl != null && params.calendarUrl !== ""
      ? `📅 Google カレンダー: ${params.calendarUrl}\n`
      : "";
  return (
    `🗓️ タスクをカレンダーに入れました（30分・Meet なし）\n` +
    `👤 件名: ${params.summary}\n` +
    `⏰ 日時: ${when} (${TZ})\n` +
    calLine
  );
}

/** タスクでもミーティング明示でもないとき（1時間・Meet なし） */
function buildCalendarBlockSlackMessage(params: {
  summary: string;
  start: dayjs.Dayjs;
  end: dayjs.Dayjs;
  calendarUrl?: string | null;
}): string {
  const when = formatSlackDatetimeRange(params.start, params.end);
  const calLine =
    params.calendarUrl != null && params.calendarUrl !== ""
      ? `📅 Google カレンダー: ${params.calendarUrl}\n`
      : "";
  return (
    `🗓️ カレンダーに入れました（1時間・Meet なし）\n` +
    `👤 件名: ${params.summary}\n` +
    `⏰ 日時: ${when} (${TZ})\n` +
    calLine
  );
}

async function postSlack(text: string): Promise<void> {
  const webhook = process.env.SLACK_WEBHOOK_URL;
  const token = process.env.SLACK_BOT_TOKEN;
  const channel = process.env.SLACK_CHANNEL_ID?.trim() || DEFAULT_SLACK_CHANNEL_ID;

  // SLACK_BOT_TOKEN があるときは chat.postMessage を優先（<@U...> メンションが Webhook より確実）
  if (token) {
    const r = await axios.post<{ ok?: boolean; error?: string }>(
      "https://slack.com/api/chat.postMessage",
      { channel, text, unfurl_links: false, unfurl_media: false },
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json; charset=utf-8",
        },
        validateStatus: () => true,
      }
    );
    const j = r.data;
    if (!j.ok) throw new Error(`Slack API 失敗: ${j.error || r.status}`);
    return;
  }

  if (webhook) {
    const r = await axios.post(
      webhook,
      { text, unfurl_links: false, unfurl_media: false },
      { validateStatus: () => true }
    );
    if (r.status < 200 || r.status >= 300) {
      throw new Error(`Slack Webhook 失敗: ${r.status} ${String(r.data)}`);
    }
    return;
  }

  throw new Error(
    "SLACK_WEBHOOK_URL または SLACK_BOT_TOKEN を設定してください（Bot 利用時は既定で " +
      DEFAULT_SLACK_CHANNEL_ID +
      " に投稿）"
  );
}

export type MeetJobOptions = {
  /** true のとき本文に「タスク／予定」が無くても 30 分・Meet なし（予定として入れる） */
  forceTask?: boolean;
  /**
   * true のとき、本文に「ミーティング」等が無くても Google Meet 付きで予定を作成する。
   * Siri / ショートカットで「いつ・誰と」だけ聞く場合、本文に会議キーワードが無いと Meet なし分岐になるため、JSON で `meet: true` を送る。
   */
  forceGoogleMeet?: boolean;
  /**
   * 指定時は `meet/data/google_tokens/<U>.json` をそのリクエスト専用の Google トークンとして使う（本文の `slack_user_id` と一致させる）。
   */
  slackUserId?: string;
};

function parseForceTaskFromBody(body: unknown): boolean {
  if (!body || typeof body !== "object") return false;
  const o = body as Record<string, unknown>;
  if (o.task === true || o.task === "true" || o.task === 1) return true;
  if (
    typeof o.scheduleMode === "string" &&
    o.scheduleMode.trim().toLowerCase() === "task"
  ) {
    return true;
  }
  return false;
}

/** 本番 OAuth 案内・エラーヒント用（`ios-shortcut-api/.env` の OAUTH_SERVER_PUBLIC_URL、未設定時は meet.humbull.co） */
function publicOauthBaseForHints(): string {
  return (process.env.OAUTH_SERVER_PUBLIC_URL || "https://meet.humbull.co").replace(
    /\/$/,
    ""
  );
}

function parseOptionalSlackUserIdFromBody(body: unknown): string | undefined {
  if (!body || typeof body !== "object") return undefined;
  const o = body as Record<string, unknown>;
  const raw = o.slack_user_id ?? o.slackUserId;
  if (typeof raw !== "string") return undefined;
  const s = raw.trim();
  return s || undefined;
}

/** POST /api/meet の JSON で Meet 付きを強制（本文のキーワード判定をスキップ） */
function parseForceGoogleMeetFromBody(body: unknown): boolean {
  if (!body || typeof body !== "object") return false;
  const o = body as Record<string, unknown>;
  const keys = [
    "meet",
    "forceGoogleMeet",
    "googleMeet",
    "withGoogleMeet",
    "conference",
  ] as const;
  for (const k of keys) {
    const v = o[k];
    if (v === true || v === 1) return true;
    if (v === "true" || v === "1") return true;
  }
  return false;
}

async function runMeetJob(
  text: string,
  jobId: string,
  opts?: MeetJobOptions
): Promise<void> {
  const parsed = parseMeetingFromText(text);
  /** JSON の `meet: true` 明示時はタスク分岐より優先し、必ず Meet 付きジョブへ */
  const explicitMeet = Boolean(opts?.forceGoogleMeet);
  const taskMode =
    (Boolean(opts?.forceTask) || isTaskCalendarIntent(text)) && !explicitMeet;
  const wantMeet = explicitMeet || isMeetingMeetIntent(text);
  const slackUserId = opts?.slackUserId;
  const slackLog = slackUserId ?? "default";

  if (taskMode) {
    const end = parsed.start.add(30, "minute");
    const created = await createCalendarEventWithoutConference({
      summary: parsed.summary,
      start: parsed.start,
      end,
      slackUserId,
    });
    const mention = slackResultMentionPrefix();
    const slackBody =
      mention +
      buildTaskSlackMessage({
        summary: parsed.summary,
        start: parsed.start,
        end,
        calendarUrl: created.htmlLink,
      });
    await postSlack(slackBody);
    console.log(
      `[meet job ${jobId}] task ok event=${created.eventId} htmlLink=${created.htmlLink ?? ""} slackUser=${slackLog} forceTask=${opts?.forceTask ? "yes" : "no"} slackMention=${mention ? "yes" : "no"}`
    );
    return;
  }

  const end = parsed.start.add(1, "hour");

  if (!wantMeet) {
    const created = await createCalendarEventWithoutConference({
      summary: parsed.summary,
      start: parsed.start,
      end,
      slackUserId,
    });
    const mention = slackResultMentionPrefix();
    const slackBody =
      mention +
      buildCalendarBlockSlackMessage({
        summary: parsed.summary,
        start: parsed.start,
        end,
        calendarUrl: created.htmlLink,
      });
    await postSlack(slackBody);
    console.log(
      `[meet job ${jobId}] calendar-only ok event=${created.eventId} htmlLink=${created.htmlLink ?? ""} slackUser=${slackLog} forceGoogleMeet=${opts?.forceGoogleMeet ? "yes" : "no"} slackMention=${mention ? "yes" : "no"}`
    );
    return;
  }

  const meeting = { ...parsed, end };

  const created = await createMeetEvent({
    summary: meeting.summary,
    start: meeting.start,
    end: meeting.end,
    slackUserId,
  });

  if (!created.hangoutLink) {
    console.warn(
      `[meet job ${jobId}] Google Calendar は成功したが hangoutLink が空です。Workspace の Meet 設定や conferenceData を確認してください。eventId=${created.eventId}`
    );
  }

  const meetUrl = created.hangoutLink || "(Google Meet の URL を取得できませんでした)";
  const mention = slackResultMentionPrefix();
  if (!mention && (process.env.SLACK_BOT_TOKEN || process.env.SLACK_WEBHOOK_URL)) {
    const ch = process.env.SLACK_CHANNEL_ID?.trim() || DEFAULT_SLACK_CHANNEL_ID;
    if (ch === "C0AR1VBT3ED") {
      console.warn(
        `[meet job ${jobId}] Slack メンションなし: C0AR1VBT3ED 向けに SLACK_CHANNEL_RESULT_MENTION_USER_ID 等を確認してください`
      );
    }
  }
  const slackBody =
    mention +
    buildSlackMessage({
      summary: meeting.summary,
      start: meeting.start,
      end: meeting.end,
      meetUrl,
      calendarUrl: created.htmlLink,
    });

  await postSlack(slackBody);
  console.log(
    `[meet job ${jobId}] ok event=${created.eventId} htmlLink=${created.htmlLink ?? ""} hangout=${created.hangoutLink ? "yes" : "no"} slackUser=${slackLog} forceGoogleMeet=${opts?.forceGoogleMeet ? "yes" : "no"} slackMention=${mention ? "yes" : "no"}`
  );
}

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------

const app = express();
app.set("trust proxy", true);

const corsOptions: cors.CorsOptions = {
  origin: (origin, cb) => {
    if (!origin) {
      cb(null, true);
      return;
    }
    const allow = process.env.CORS_ORIGINS?.split(",").map((s) => s.trim()).filter(Boolean);
    if (!allow || allow.length === 0) {
      cb(null, true);
      return;
    }
    if (allow.includes(origin)) {
      cb(null, true);
      return;
    }
    cb(null, false);
  },
  methods: ["GET", "POST", "OPTIONS"],
  allowedHeaders: ["Content-Type", "Authorization", "X-Api-Key", "x-api-key"],
  optionsSuccessStatus: 204,
};

app.use(cors(corsOptions));
app.use(express.json({ limit: "256kb" }));

function checkApiKey(req: Request, res: Response): boolean {
  const expected = process.env.API_KEY;
  if (!expected) return true;
  const got = req.header("x-api-key") || req.query.api_key;
  if (got !== expected) {
    res.status(401).json({ error: "Unauthorized" });
    return false;
  }
  return true;
}

/** カレンダー所有者のメールを返すため、API_KEY 未設定時は localhost のみ許可 */
function checkCalendarStatusAccess(req: Request, res: Response): boolean {
  if (process.env.API_KEY) {
    return checkApiKey(req, res);
  }
  const ip = req.ip || req.socket.remoteAddress || "";
  if (
    ip === "127.0.0.1" ||
    ip === "::1" ||
    ip === "::ffff:127.0.0.1"
  ) {
    return true;
  }
  res.status(403).json({
    error:
      "この URL はカレンダー情報を含むため、API_KEY 未設定時は localhost からのみ利用できます。iPhone から確認するには .env に API_KEY を設定し、x-api-key ヘッダを付けてください。",
  });
  return false;
}

/**
 * GET /api/google-calendar-status
 * 現在のトークンがどの Google カレンダー（primary ID）に紐づくか表示。.env の GOOGLE_CALENDAR_OWNER_EMAIL と一致するか確認用。
 */
app.get("/api/google-calendar-status", async (req: Request, res: Response) => {
  if (!checkCalendarStatusAccess(req, res)) return;

  const expected = process.env.GOOGLE_CALENDAR_OWNER_EMAIL?.trim() || null;

  if (!hasGoogleCredentialsConfigured()) {
    res.json({
      ok: false,
      credentialsConfigured: false,
      expectedOwnerEmail: expected,
      primaryCalendarId: null,
      ownerMatchesExpected: false,
      message:
        "トークン未設定です。daisuke.k@humbull.co で OAuth したあと GOOGLE_TOKEN_FILE または GOOGLE_REFRESH_TOKEN を設定してください。",
    });
    return;
  }

  try {
    const auth = getOAuthClient();
    const cal = google.calendar({ version: "v3", auth });
    try {
      const { data } = await cal.calendars.get({ calendarId: "primary" });
      const primaryId = data.id ?? null;
      const ownerMatchesExpected = !!(
        expected &&
        primaryId &&
        primaryId.toLowerCase() === expected.toLowerCase()
      );
      res.json({
        ok: ownerMatchesExpected,
        credentialsConfigured: true,
        expectedOwnerEmail: expected,
        primaryCalendarId: primaryId,
        ownerMatchesExpected,
        message: ownerMatchesExpected
          ? "このトークンで作成される予定は、上記 primaryCalendarId のカレンダーに入ります（ショートカット経由も同じ）。"
          : `トークンは「${primaryId}」の Google アカウント用です。.env の GOOGLE_CALENDAR_OWNER_EMAIL（${expected}）と違うため、OAuth を「${expected}」でやり直し、トークンを差し替えてください。`,
      });
    } catch (inner) {
      if (isInsufficientScopeForCalendarsGet(inner)) {
        res.json({
          ok: null,
          credentialsConfigured: true,
          expectedOwnerEmail: expected,
          primaryCalendarId: null,
          ownerMatchesExpected: null,
          scopeInsufficient: true,
          message:
            "トークンはありますが calendars.get に必要なスコープがありません。予定の作成は calendar.events で可能です。所有者検証が必要なら Google Cloud の OAuth 同意画面に calendar.readonly を追加し、再 OAuth してください。",
        });
        return;
      }
      throw inner;
    }
  } catch (e) {
    res.status(500).json({
      ok: false,
      error: logGoogleApiError(e),
    });
  }
});

/**
 * POST /api/meet
 * Body: { "text": "音声内容", "task"?: true, "meet"?: true, "slack_user_id"?: "U..." }
 * - task: true または scheduleMode: "task" … 30 分・Meet なし（ただし **meet: true と併記した場合は meet を優先**し Meet 付きジョブを実行）
 * - meet（ブール true 可）/ forceGoogleMeet … **必ず** Meet 付きジョブ（タスク本文・task フラグより優先）
 * - slack_user_id: 指定時は meet/data/google_tokens/<U>.json のみを使用（未指定時は .env の GOOGLE_TOKEN_FILE 等）
 * 即座に 200 を返し、Meet / Slack は非同期で実行（Siri の待ち時間短縮）
 */
app.post("/api/meet", (req: Request, res: Response) => {
  if (!checkApiKey(req, res)) return;

  const text =
    (req.body?.text as string) || (req.body?.voiceTranscript as string) || "";
  if (!text.trim()) {
    res.status(400).json({ ok: false, error: "text または voiceTranscript が必要です" });
    return;
  }
  const forceTask = parseForceTaskFromBody(req.body);
  const forceGoogleMeet = parseForceGoogleMeetFromBody(req.body);
  const slackUserIdRaw = parseOptionalSlackUserIdFromBody(req.body);
  if (slackUserIdRaw && !SLACK_USER_ID_RE.test(slackUserIdRaw)) {
    res.status(400).json({
      ok: false,
      error: "slack_user_id は U で始まる Slack メンバー ID 形式である必要があります",
    });
    return;
  }
  const slackUserId = slackUserIdRaw;

  if (!hasGoogleCredentialsConfigured(slackUserId)) {
    const base = publicOauthBaseForHints();
    const hintDefault = `単一トークンなら ios-shortcut-api/.env の GOOGLE_TOKEN_FILE 等。ユーザー別ならブラウザで ${base}/oauth/start?slack_user_id=U... を開き、VM の meet/data/google_tokens/<U>.json を生成してください。`;
    const hint =
      slackUserId != null && slackUserId !== ""
        ? `slack_user_id=${slackUserId} 用のトークンがありません。${base}/oauth/start?slack_user_id=${encodeURIComponent(
            slackUserId
          )} で Google を許可し、コンテナから見て data/google_tokens/${slackUserId}.json が存在するか確認してください。`
        : `Google カレンダーが未連携です。${hintDefault}`;
    res.status(503).json({
      ok: false,
      error: "Google カレンダーが未連携、または指定 slack_user_id のトークンがありません。",
      hint,
    });
    return;
  }
  if (!process.env.GOOGLE_CALENDAR_OWNER_EMAIL?.trim()) {
    res.status(503).json({
      ok: false,
      error: "GOOGLE_CALENDAR_OWNER_EMAIL が未設定です。",
    });
    return;
  }

  const jobId = crypto.randomUUID();
  const message = forceGoogleMeet
    ? "受け付けました。Meet 付きでカレンダー登録と Slack 通知をバックグラウンドで実行します。"
    : forceTask
      ? "受け付けました（30分・Meet なし）。Slack 通知はバックグラウンドで実行されます。"
      : "受け付けました。本文の解釈に応じて Meet の有無が決まります。バックグラウンドで実行されます。";

  res.status(200).json({
    ok: true,
    accepted: true,
    jobId,
    message,
  });

  setImmediate(() => {
    void (async () => {
      try {
        await runMeetJob(text, jobId, {
          forceTask,
          forceGoogleMeet,
          slackUserId,
        });
      } catch (e) {
        const msg =
          e instanceof Error ? e.message : logGoogleApiError(e);
        console.error(`[meet job ${jobId}]`, e);
        try {
          await postSlack(
            slackResultMentionPrefix() +
              `❌ 会議の自動作成に失敗しました（job: ${jobId}）\n${msg}`
          );
        } catch (slackErr) {
          console.error(`[meet job ${jobId}] Slack エラー通知も失敗`, slackErr);
        }
      }
    })();
  });
});

/**
 * Google OAuth 開始へ誘導（実体は meet/oauth_server.py の 8888 /oauth/start）。
 * ブラウザ: http://127.0.0.1:3847/auth/google?slack_user_id=Uxxxx
 */
app.get("/auth/google", (req: Request, res: Response) => {
  const q = (req.query.slack_user_id as string | undefined)?.trim();
  const fromEnv = process.env.SLACK_OAUTH_USER_ID?.trim();
  const slackUserId = q || fromEnv;
  const oauthBase = (
    process.env.OAUTH_SERVER_PUBLIC_URL || "http://127.0.0.1:8888"
  ).replace(/\/$/, "");

  if (!slackUserId || !SLACK_USER_ID_RE.test(slackUserId)) {
    res.status(200).type("html").send(`<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><title>Google カレンダー連携</title></head>
<body>
  <h1>Google カレンダー連携</h1>
  <p>Slack のプロフィールで「メンバー ID」（<code>U</code> で始まる）を確認し、下に入力してください。</p>
  <form method="get" action="/auth/google">
    <label>slack_user_id: <input name="slack_user_id" pattern="U[A-Za-z0-9]+" required placeholder="Uxxxxxxxx" size="16"></label>
    <button type="submit">認証 URL へ進む</button>
  </form>
  <p><small>事前に <code>meet</code> で <code>oauth_server</code>（ポート 8888）を起動してください（例: <code>./start_services.sh</code>）。<br>
  OAuth 完了後、<code>meet/data/google_tokens/&lt;Slack ID&gt;.json</code> が作成されます。<code>ios-shortcut-api/.env</code> の <code>GOOGLE_TOKEN_FILE</code> をそのパスに合わせてください。</small></p>
</body></html>`);
    return;
  }

  const target = `${oauthBase}/oauth/start?slack_user_id=${encodeURIComponent(slackUserId)}`;
  res.redirect(302, target);
});

app.get("/health", (_req: Request, res: Response) => {
  res.json({ ok: true });
});

const port = Number(process.env.PORT) || 3847;

async function main(): Promise<void> {
  if (process.env.SKIP_GOOGLE_CALENDAR_VERIFY === "true") {
    console.warn(
      "SKIP_GOOGLE_CALENDAR_VERIFY: Google カレンダー所有者の起動時検証をスキップしました（本番では使わないでください）"
    );
  } else if (!hasGoogleCredentialsConfigured()) {
    console.warn(
      "Google refresh_token 未設定。OAuth 後にトークンを配置してください: http://127.0.0.1:" +
        port +
        "/auth/google?slack_user_id=U... （8888 の oauth_server が必要）"
    );
  } else if (!process.env.GOOGLE_CALENDAR_OWNER_EMAIL?.trim()) {
    console.warn(
      "GOOGLE_CALENDAR_OWNER_EMAIL 未設定。誤ったアカウントに書き込む可能性があります。"
    );
  } else {
    try {
      const auth = getOAuthClient();
      const verified = await assertCalendarOwnerMatches(auth);
      if (verified) {
        console.log(
          `Google Calendar: primary カレンダーは ${process.env.GOOGLE_CALENDAR_OWNER_EMAIL} と一致（検証済み）`
        );
      } else {
        console.warn(
          "Google Calendar: 所有者はスコープ不足のため未検証。予定作成は可能です。calendar.readonly を付与して再 OAuth すると検証できます。"
        );
      }
    } catch (e) {
      console.error(
        "起動失敗: トークンが GOOGLE_CALENDAR_OWNER_EMAIL と一致しません。GOOGLE_TOKEN_FILE / GOOGLE_REFRESH_TOKEN を差し替えてください。"
      );
      console.error(e);
      process.exit(1);
    }
  }

  app.listen(port, () => {
    console.log(`ios-shortcut-meet-api listening on http://127.0.0.1:${port}`);
    console.log(
      `POST /api/meet  body: { "text": "..." }  optional: { "task": true } → 30分・Meetなし / { "meet": true } → Meet強制`
    );
    console.log(
      `Google 連携: http://127.0.0.1:${port}/auth/google?slack_user_id=U... → oauth_server (${process.env.OAUTH_SERVER_PUBLIC_URL || "http://127.0.0.1:8888"})`
    );
  });
}

if (require.main === module) {
  void main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
