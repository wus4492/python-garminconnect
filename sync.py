import os
import json
import datetime

import gspread
from google.oauth2.service_account import Credentials
from garminconnect import Garmin

# ---- Garmin 登入 ----
client = Garmin(os.environ["GARMIN_USER"], os.environ["GARMIN_PASSWORD"])
client.login()

# ---- 抓昨天的資料 ----
yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

stats = client.get_stats(yesterday)
steps = stats.get("totalSteps", 0)
resting_hr = stats.get("restingHeartRate", "")
calories = stats.get("totalKilocalories", "")

sleep_data = client.get_sleep_data(yesterday)
sleep_seconds = (
    sleep_data.get("dailySleepDTO", {}).get("sleepTimeSeconds") or 0
)
sleep_hours = round(sleep_seconds / 3600, 2)

# ---- 連 Google Sheet ----
key_json = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_KEY"])
creds = Credentials.from_service_account_info(
    key_json,
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(os.environ["SPREADSHEET_ID"]).sheet1

# ---- 寫入一列 ----
sheet.append_row([yesterday, steps, sleep_hours, resting_hr, calories])
print(f"已寫入 {yesterday}：步數 {steps}、睡眠 {sleep_hours} 小時")

run: python sync.py
