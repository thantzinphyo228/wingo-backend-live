import os
import time
import threading
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- DATABASE SETUP ----------
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["wingo_database"]
collection = db["wingo_30s_history"]
events_col = db["pattern_events"]

collection.create_index("period", unique=True)

# ---------- ENV CREDENTIALS ----------
PHONE = os.getenv("WINGO_PHONE")
PASSWORD = os.getenv("WINGO_PASSWORD")

# ---------- SELENIUM FUNCTIONS ----------

def handle_popups(driver):
    try:
        btns = driver.find_elements(By.CSS_SELECTOR, ".closeBtn, .acitveBtn")
        if btns:
            for btn in btns:
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(0.5)
    except:
        pass

def perform_login(driver):
    print("🔑 Performing secure auto-login flow...", flush=True)
    wait = WebDriverWait(driver, 15)
    try:
        driver.get("https://www.cklottery.club/#/login")
        time.sleep(4)
        handle_popups(driver)
        
        wait.until(EC.presence_of_element_located((By.NAME, "userNumber"))).send_keys(PHONE)
        driver.find_element(By.XPATH, "//input[@type='password']").send_keys(PASSWORD)

        login_btn = driver.find_element(By.XPATH, "//button[contains(@class, 'active')]")
        driver.execute_script("arguments[0].click();", login_btn)
        print("✅ Login အောင်မြင်စွာ ဝင်ပြီးပါပြီ။", flush=True)
        time.sleep(8)
        return True
    except Exception as e:
        print(f"❌ Auto-Login Failed: {e}", flush=True)
        return False

def navigate_to_wingo_30s(driver):
    print("🎮 Navigating to WinGo Game Page...", flush=True)
    driver.get("https://www.cklottery.club/#/home/AllLotteryGames/WinGo?id=1")
    print("✅ Win Go Page ကို ရောက်ရှိပါပြီ။", flush=True)
    time.sleep(5)
    handle_popups(driver)
    
    print("⏳ 30 Seconds ပွဲစဉ်သို့ ပြောင်းလဲနေပါသည်...", flush=True)
    wait = WebDriverWait(driver, 10)
    try:
        thirty_sec_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(text(), '30s')]")))
        driver.execute_script("arguments[0].click();", thirty_sec_btn)
        print("✅ 30s ပြောင်းလဲမှု အောင်မြင်သည်။", flush=True)
    except Exception as e:
        print(f"⚠️ Fallback သုံးပါမည်။ Error: {e}", flush=True)
        try:
            tabs = driver.find_elements(By.CLASS_NAME, "GameList__C-item")
            for tab in tabs:
                if "30s" in tab.text:
                    driver.execute_script("arguments[0].click();", tab)
                    print("✅ Fallback ဖြင့် 30s ပြောင်းလဲမှု အောင်မြင်သည်။", flush=True)
                    break
        except Exception as fb_err:
            print(f"❌ Both Navigation Methods Failed: {fb_err}", flush=True)
    time.sleep(3)

def get_latest_row_data(driver):
    handle_popups(driver)
    try:
        row = driver.find_element(By.CSS_SELECTOR, ".GameRecord__C-body .van-row")
        period = row.find_element(By.CSS_SELECTOR, "div.van-col--9").text.strip()
        number = row.find_element(By.CSS_SELECTOR, ".GameRecord__C-body-num").text.strip()
        result = row.find_element(By.CSS_SELECTOR, "div.van-col--5 span").text.strip()
        return period, number, result
    except Exception as e:
        print(f"⚠️ Row Data Read Error: {e}", flush=True)
        return None, None, None

def check_and_log_patterns(trigger_period):
    latest_docs = list(collection.find().sort("period", -1).limit(50))
    if len(latest_docs) < 7:
        return
        
    first_result = latest_docs[0]['result']
    streak_count = 0
    
    for doc in latest_docs:
        if doc['result'] == first_result:
            streak_count += 1
        else:
            break
            
    if streak_count >= 7:
        streak_start_period = latest_docs[streak_count - 1]['period']
        pattern_type = f"{streak_count}_STREAK_{first_result.upper()}"
        
        existing_event = events_col.find_one({"streak_start_period": streak_start_period})
        
        if not existing_event:
            events_col.insert_one({
                "trigger_period": trigger_period,
                "streak_start_period": streak_start_period,
                "pattern_type": pattern_type,
                "timestamp": latest_docs[0].get('timestamp')
            })
            print(f"🚨 New Pattern Inserted: {streak_count}-Streak {first_result.upper()} ({trigger_period})", flush=True)
        else:
            events_col.update_one(
                {"streak_start_period": streak_start_period},
                {"$set": {"pattern_type": pattern_type}}
            )
            print(f"🔄 Pattern Updated Dynamic: {streak_count}-Streak {first_result.upper()} ({trigger_period})", flush=True)

    if len(latest_docs) >= 9:
        current_8 = latest_docs[:8]
        ninth_item = latest_docs[8]
        is_alternating = True
        for i in range(7):
            if current_8[i]['result'] == current_8[i+1]['result']:
                is_alternating = False
                break
                
        if is_alternating and current_8[7]['result'] == ninth_item['result']:
            if not events_col.find_one({"trigger_period": trigger_period, "pattern_type": "8_ZIGZAG"}):
                events_col.insert_one({
                    "trigger_period": trigger_period,
                    "streak_start_period": trigger_period,
                    "pattern_type": "8_ZIGZAG",
                    "timestamp": latest_docs[0].get('timestamp')
                })
                print(f"🚨 Pattern Detected: 8-Period ZIGZAG ({trigger_period})", flush=True)

def run_scraper_bot():
    print("🤖 Starting Headless Selenium Scraper Thread with Light-Weight Memory Optimization...", flush=True)
    
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit=537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # 🚀 Render 512MB RAM ပေါ်တွင် မအေးခဲစေရန် ရုပ်ပုံများနှင့် အန်နီမေးရှင်းများ ပိတ်ဆို့သည့် စနစ်
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--disable-software-rasterizer")
    
    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(40)
        
        navigate_to_wingo_30s(driver)
        
        last_period = ""
        print("🚀 Scraper Loop is now active...", flush=True)
        
        while True:
            try:
                handle_popups(driver)
                period_el = driver.find_element(By.CLASS_NAME, "TimeLeft__C-id")
                p_num = period_el.text
                
                if len(p_num) < 10 or p_num == last_period:
                    time.sleep(1)
                    continue

                time.sleep(5) 
                period, number, result = get_latest_row_data(driver)
                
                if period and number and result:
                    data_doc = {
                        "period": period,
                        "number": int(number) if number.isdigit() else number,
                        "result": result,
                        "game_type": "30s",
                        "timestamp": datetime.utcnow()
                    }
                    try:
                        collection.insert_one(data_doc)
                        check_and_log_patterns(period)
                        print(f"💾 Saved to Cloud MongoDB: {period} | {result}", flush=True)
                    except DuplicateKeyError:
                        pass
                    last_period = p_num
                    
            except Exception as loop_error:
                current_url = driver.current_url
                print(f"⚠️ Loop Exception! URL='{current_url}' | Title='{driver.title}'", flush=True)
                
                if "login" in current_url:
                    if perform_login(driver):
                        navigate_to_wingo_30s(driver)
                else:
                    print("🔄 Re-navigating to WinGo page to fix lag or popups...", flush=True)
                    navigate_to_wingo_30s(driver)
                
                time.sleep(3)
                
    except Exception as fatal_bot_error:
        print(f"🔥 FATAL BOT THREAD ERROR: {fatal_bot_error}", flush=True)
    finally:
        if driver:
            print("🛑 Closing Driver instance.", flush=True)
            driver.quit()

# ---------- API ENDPOINTS ----------

def count_five_streaks_after(trigger_period):
    future_docs = list(collection.find({"period": {"$gt": trigger_period}}).sort("period", 1).limit(120))
    if not future_docs: return 0
    five_streak_count, current_streak, last_result = 0, 1, future_docs[0]['result']
    for i in range(1, len(future_docs)):
        current_res = future_docs[i]['result']
        if current_res == last_result:
            current_streak += 1
            if current_streak == 5: five_streak_count += 1
        else:
            current_streak, last_result = 1, current_res
    return five_streak_count

@app.get("/api/wingo30s")
def get_latest_results():
    return list(collection.find({}, {"_id": 0}).sort("period", -1).limit(10))

@app.get("/api/patterns")
def get_pattern_analytics():
    events = list(events_col.find({}, {"_id": 0}).sort("trigger_period", -1).limit(15))
    for event in events:
        event["five_streak_count"] = count_five_streaks_after(event["trigger_period"])
    return events

@app.on_event("startup")
def startup_event():
    threading.Thread(target=run_scraper_bot, daemon=True).start()