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
sheet = gc.open_by_key(os.environ["SPREADSHEET_ID"]).sheet1

HEADERS = [
    "日期", "類型",
    # --- 每日健康 ---
    "步數", "睡眠(時)", "深睡(時)", "REM(時)", "睡眠分數",
    "靜止心率", "HRV", "平均壓力", "身體電量最高", "身體電量最低",
    # --- 訓練狀態 ---
    "VO2Max", "訓練準備度", "準備度評級", "急性負荷",
    # --- 跑步 / 分段共用 ---
    "開始時間", "活動名稱", "第幾圈", "圈類型",
    "距離(km)", "時間(分)", "配速(分/km)",
    "平均心率", "最大心率", "步頻(spm)", "步幅(cm)",
    "垂直振幅(cm)", "觸地時間(ms)", "功率(W)", "爬升(m)",
    "卡路里", "有氧訓練效果", "無氧訓練效果", "訓練負荷", "活動ID",
]
N = len(HEADERS)

# 如果第一列是空的，就寫入表頭
if not sheet.row_values(1):
    sheet.append_row(HEADERS)


def make_row(**kwargs):
    """依表頭名稱填值，其餘留空"""
    row = [""] * N
    for key, val in kwargs.items():
        row[HEADERS.index(key)] = val
    return row


def pace_from_speed(speed_mps):
    if not speed_mps or speed_mps <= 0:
        return ""
    sec = 1000 / speed_mps
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


def safe(fn, default=None):
    try:
        return fn()
    except Exception as e:
        print(f"警告：某項資料抓取失敗：{e}")
        return default


rows = []

# ========================================
# 1. 「每日」列：健康 + 訓練狀態
# ========================================
stats = safe(lambda: client.get_stats(yesterday), {}) or {}

sleep_data = safe(lambda: client.get_sleep_data(yesterday), {}) or {}
sleep_dto = sleep_data.get("dailySleepDTO", {}) or {}
to_hr = lambda s: round((s or 0) / 3600, 2)
sleep_score = ((sleep_dto.get("sleepScores") or {}).get("overall") or {}).get("value", "")

hrv_data = safe(lambda: client.get_hrv_data(yesterday), {}) or {}
hrv = (hrv_data.get("hrvSummary") or {}).get("lastNightAvg", "")

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
latest = ((status.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {})
if latest:
    first_device = next(iter(latest.values()), {}) or {}
    atl = first_device.get("acuteTrainingLoadDTO")
    if isinstance(atl, dict):
        acute_load = atl.get("dailyAcuteLoad", "")

rows.append(make_row(**{
    "日期": yesterday,
    "類型": "每日",
    "步數": stats.get("totalSteps", ""),
    "睡眠(時)": to_hr(sleep_dto.get("sleepTimeSeconds")),
    "深睡(時)": to_hr(sleep_dto.get("deepSleepSeconds")),
    "REM(時)": to_hr(sleep_dto.get("remSleepSeconds")),
    "睡眠分數": sleep_score,
    "靜止心率": stats.get("restingHeartRate", ""),
    "HRV": hrv,
    "平均壓力": stats.get("averageStressLevel", ""),
    "身體電量最高": stats.get("bodyBatteryHighestValue", ""),
    "身體電量最低": stats.get("bodyBatteryLowestValue", ""),
    "VO2Max": vo2max,
    "訓練準備度": readiness_score,
    "準備度評級": readiness_level,
    "急性負荷": acute_load,
    "卡路里": stats.get("totalKilocalories", ""),
}))

# ========================================
# 2. 「跑步」列 + 「分段」列
# ========================================
activities = safe(lambda: client.get_activities_by_date(yesterday, yesterday), []) or []

run_count = 0
for act in activities:
    type_key = (act.get("activityType") or {}).get("typeKey", "")
    if "running" not in type_key:
        continue

    act_id = act.get("activityId", "")
    run_count += 1

    rows.append(make_row(**{
        "日期": yesterday,
        "類型": "跑步",
        "開始時間": (act.get("startTimeLocal") or "")[11:16],
        "活動名稱": act.get("activityName", ""),
        "距離(km)": round((act.get("distance") or 0) / 1000, 2),
        "時間(分)": round((act.get("duration") or 0) / 60, 1),
        "配速(分/km)": pace_from_speed(act.get("averageSpeed")),
        "平均心率": act.get("averageHR", ""),
        "最大心率": act.get("maxHR", ""),
        "步頻(spm)": act.get("averageRunningCadenceInStepsPerMinute", ""),
        "步幅(cm)": round(act.get("avgStrideLength") or 0, 1) or "",
        "垂直振幅(cm)": act.get("avgVerticalOscillation", ""),
        "觸地時間(ms)": act.get("avgGroundContactTime", ""),
        "功率(W)": act.get("avgPower", ""),
        "爬升(m)": act.get("elevationGain", ""),
        "卡路里": act.get("calories", ""),
        "有氧訓練效果": act.get("aerobicTrainingEffect", ""),
        "無氧訓練效果": act.get("anaerobicTrainingEffect", ""),
        "訓練負荷": act.get("activityTrainingLoad", ""),
        "活動ID": act_id,
    }))

    # ---- 每圈分段 ----
    try:
        splits = client.get_activity_splits(act_id)
        laps = splits.get("lapDTOs", []) or []
        for i, lap in enumerate(laps, start=1):
            rows.append(make_row(**{
                "日期": yesterday,
                "類型": "分段",
                "第幾圈": i,
                "圈類型": lap.get("intensityType", "") or "",
                "距離(km)": round((lap.get("distance") or 0) / 1000, 3),
                "時間(分)": round((lap.get("duration") or 0) / 60, 2),
                "配速(分/km)": pace_from_speed(lap.get("averageSpeed")),
                "平均心率": lap.get("averageHR", ""),
                "最大心率": lap.get("maxHR", ""),
                "步頻(spm)": lap.get("averageRunCadence", ""),
                "活動ID": act_id,
            }))
    except Exception as e:
        print(f"活動 {act_id} 分段抓取失敗：{e}")

# ---- 一次寫入所有列 ----
sheet.append_rows(rows)
print(f"完成：共寫入 {len(rows)} 列（每日 1、跑步 {run_count}、分段 {len(rows) - 1 - run_count}）（{yesterday}）")
