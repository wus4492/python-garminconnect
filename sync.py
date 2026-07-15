pythonimport os
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

# ========================================
# 第一部分：每日健康數據 → 第一個分頁
# ========================================
stats = client.get_stats(yesterday)
steps = stats.get("totalSteps", "")
resting_hr = stats.get("restingHeartRate", "")
calories = stats.get("totalKilocalories", "")
stress = stats.get("averageStressLevel", "")
body_battery_high = stats.get("bodyBatteryHighestValue", "")
body_battery_low = stats.get("bodyBatteryLowestValue", "")

sleep_data = client.get_sleep_data(yesterday)
sleep_dto = sleep_data.get("dailySleepDTO", {}) or {}
sleep_seconds = sleep_dto.get("sleepTimeSeconds") or 0
sleep_hours = round(sleep_seconds / 3600, 2)
deep_sleep = round((sleep_dto.get("deepSleepSeconds") or 0) / 3600, 2)

daily_sheet = sh.sheet1
daily_sheet.append_row([
    yesterday, steps, sleep_hours, deep_sleep,
    resting_hr, stress, body_battery_high, body_battery_low, calories,
])

# ========================================
# 第二部分：跑步活動詳細數據 → 「跑步紀錄」分頁
# ========================================
RUN_HEADERS = [
    "日期", "開始時間", "距離(km)", "時間(分)", "平均配速(分/km)",
    "平均心率", "最大心率", "步頻(spm)", "爬升(m)", "卡路里",
    "有氧訓練效果", "無氧訓練效果", "VO2Max",
]

try:
    run_sheet = sh.worksheet("跑步紀錄")
except gspread.WorksheetNotFound:
    run_sheet = sh.add_worksheet(title="跑步紀錄", rows=1000, cols=20)
    run_sheet.append_row(RUN_HEADERS)

activities = client.get_activities_by_date(yesterday, yesterday)

run_count = 0
for act in activities:
    type_key = (act.get("activityType") or {}).get("typeKey", "")
    if "running" not in type_key:
        continue  # 只記錄跑步，其他運動跳過

    distance_km = round((act.get("distance") or 0) / 1000, 2)
    duration_min = round((act.get("duration") or 0) / 60, 1)

    # 配速：m/s 換算成 分:秒 /km
    speed = act.get("averageSpeed") or 0
    if speed > 0:
        pace_sec = 1000 / speed
        pace = f"{int(pace_sec // 60)}:{int(pace_sec % 60):02d}"
    else:
        pace = ""

    start_time = (act.get("startTimeLocal") or "")[11:16]  # 只取 HH:MM

    run_sheet.append_row([
        yesterday,
        start_time,
        distance_km,
        duration_min,
        pace,
        act.get("averageHR", ""),
        act.get("maxHR", ""),
        act.get("averageRunningCadenceInStepsPerMinute", ""),
        act.get("elevationGain", ""),
        act.get("calories", ""),
        act.get("aerobicTrainingEffect", ""),
        act.get("anaerobicTrainingEffect", ""),
        act.get("vO2MaxValue", ""),
    ])
    run_count += 1

print(f"完成：每日數據 1 筆、跑步紀錄 {run_count} 筆（{yesterday}）")

