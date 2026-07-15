import os
import json
import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from garminconnect import Garmin

# ---- 用台灣時間算「昨天」 ----
tz = ZoneInfo("Asia/Taipei")
yesterday = (datetime.datetime.now(tz).date() - datetime.timedelta(days=1)).isoformat()

# ---- Garmin 登入 ----
client = Garmin(os.environ["GARMIN_USER"], os.environ["GARMIN_PASSWORD"])
client.login()

# ---- 連 Google Sheet ----
key_json = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_KEY"])
creds = Credentials.from_service_account_info(
    key_json,
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)
gc = gspread.authorize(creds)
sh = gc.open_by_key(os.environ["SPREADSHEET_ID"])


def get_or_create_sheet(title, headers):
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=3000, cols=30)
        ws.append_row(headers)
        return ws


def pace_from_speed(speed_mps):
    """m/s 轉成 分:秒/km"""
    if not speed_mps or speed_mps <= 0:
        return ""
    sec = 1000 / speed_mps
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


def fmt_time(seconds):
    if not seconds:
        return ""
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def safe(fn, default=None):
    """API 呼叫失敗不要讓整個腳本掛掉"""
    try:
        return fn()
    except Exception as e:
        print(f"警告：{fn.__name__ if hasattr(fn, '__name__') else '某項資料'} 抓取失敗：{e}")
        return default


# ========================================
# 1. 每日健康
# ========================================
health_sheet = get_or_create_sheet("每日健康", [
    "日期", "步數", "睡眠(時)", "深睡(時)", "REM(時)", "淺睡(時)", "睡眠分數",
    "靜止心率", "HRV", "平均壓力", "身體電量最高", "身體電量最低",
    "中強度分鐘", "高強度分鐘", "卡路里",
])

stats = safe(lambda: client.get_stats(yesterday), {}) or {}

sleep_data = safe(lambda: client.get_sleep_data(yesterday), {}) or {}
sleep_dto = sleep_data.get("dailySleepDTO", {}) or {}
to_hr = lambda s: round((s or 0) / 3600, 2)
sleep_score = ((sleep_dto.get("sleepScores") or {}).get("overall") or {}).get("value", "")

hrv_data = safe(lambda: client.get_hrv_data(yesterday), {}) or {}
hrv = (hrv_data.get("hrvSummary") or {}).get("lastNightAvg", "")

health_sheet.append_row([
    yesterday,
    stats.get("totalSteps", ""),
    to_hr(sleep_dto.get("sleepTimeSeconds")),
    to_hr(sleep_dto.get("deepSleepSeconds")),
    to_hr(sleep_dto.get("remSleepSeconds")),
    to_hr(sleep_dto.get("lightSleepSeconds")),
    sleep_score,
    stats.get("restingHeartRate", ""),
    hrv,
    stats.get("averageStressLevel", ""),
    stats.get("bodyBatteryHighestValue", ""),
    stats.get("bodyBatteryLowestValue", ""),
    stats.get("moderateIntensityMinutes", ""),
    stats.get("vigorousIntensityMinutes", ""),
    stats.get("totalKilocalories", ""),
])

# ========================================
# 2. 訓練狀態（VO2Max / 準備度 / 負荷）
# ========================================
train_sheet = get_or_create_sheet("訓練狀態", [
    "日期", "VO2Max", "訓練準備度分數", "準備度評級", "急性負荷",
    "最大心率(當日跑步)",
])

vo2max = ""
metrics = safe(lambda: client.get_max_metrics(yesterday), []) or []
if metrics:
    generic = (metrics[0].get("generic") or {})
    vo2max = generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue") or ""

readiness_score = ""
readiness_level = ""
readiness = safe(lambda: client.get_training_readiness(yesterday), []) or []
if readiness:
    readiness_score = readiness[0].get("score", "")
    readiness_level = readiness[0].get("level", "")

acute_load = ""
status = safe(lambda: client.get_training_status(yesterday), {}) or {}
most_recent = status.get("mostRecentTrainingStatus") or {}
latest = (most_recent.get("latestTrainingStatusData") or {})
if latest:
    first_device = next(iter(latest.values()), {}) or {}
    acute_load = first_device.get("acuteTrainingLoadDTO", {}).get("dailyAcuteLoad", "") if isinstance(first_device.get("acuteTrainingLoadDTO"), dict) else ""

# ========================================
# 3. 跑步紀錄（含跑步動態）
# ========================================
run_sheet = get_or_create_sheet("跑步紀錄", [
    "日期", "開始時間", "活動名稱", "距離(km)", "時間(分)", "平均配速(分/km)",
    "平均心率", "最大心率", "平均步頻(spm)", "最大步頻", "平均步幅(cm)",
    "垂直振幅(cm)", "觸地時間(ms)", "平均功率(W)", "爬升(m)", "卡路里",
    "有氧訓練效果", "無氧訓練效果", "訓練負荷", "活動ID",
])

split_sheet = get_or_create_sheet("分段紀錄", [
    "日期", "活動ID", "第幾圈", "圈距(km)", "圈時間",
    "配速(分/km)", "平均心率", "最大心率", "步頻(spm)", "類型",
])

activities = safe(lambda: client.get_activities_by_date(yesterday, yesterday), []) or []

run_count = 0
day_max_hr = ""
for act in activities:
    type_key = (act.get("activityType") or {}).get("typeKey", "")
    if "running" not in type_key:
        continue

    act_id = act.get("activityId", "")
    max_hr = act.get("maxHR", "")
    if max_hr and (day_max_hr == "" or max_hr > day_max_hr):
        day_max_hr = max_hr

    run_sheet.append_row([
        yesterday,
        (act.get("startTimeLocal") or "")[11:16],
        act.get("activityName", ""),
        round((act.get("distance") or 0) / 1000, 2),
        round((act.get("duration") or 0) / 60, 1),
        pace_from_speed(act.get("averageSpeed")),
        act.get("averageHR", ""),
        max_hr,
        act.get("averageRunningCadenceInStepsPerMinute", ""),
        act.get("maxRunningCadenceInStepsPerMinute", ""),
        round(act.get("avgStrideLength") or 0, 1) or "",
        act.get("avgVerticalOscillation", ""),
        act.get("avgGroundContactTime", ""),
        act.get("avgPower", ""),
        act.get("elevationGain", ""),
        act.get("calories", ""),
        act.get("aerobicTrainingEffect", ""),
        act.get("anaerobicTrainingEffect", ""),
        act.get("activityTrainingLoad", ""),
        act_id,
    ])
    run_count += 1

    # ---- 每圈分段 ----
    try:
        splits = client.get_activity_splits(act_id)
        laps = splits.get("lapDTOs", []) or []
        rows = []
        for i, lap in enumerate(laps, start=1):
            rows.append([
                yesterday,
                act_id,
                i,
                round((lap.get("distance") or 0) / 1000, 3),
                fmt_time(lap.get("duration")),
                pace_from_speed(lap.get("averageSpeed")),
                lap.get("averageHR", ""),
                lap.get("maxHR", ""),
                lap.get("averageRunCadence", ""),
                lap.get("intensityType", "") or "",
            ])
        if rows:
            split_sheet.append_rows(rows)
    except Exception as e:
        print(f"活動 {act_id} 分段抓取失敗：{e}")

# 訓練狀態列（放在跑步迴圈後，才能填入當日跑步最大心率）
train_sheet.append_row([
    yesterday, vo2max, readiness_score, readiness_level, acute_load, day_max_hr,
])

print(f"完成：健康 1 筆、訓練狀態 1 筆、跑步 {run_count} 筆（{yesterday}）")
