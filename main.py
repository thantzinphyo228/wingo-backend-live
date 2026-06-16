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

# App မှ လှမ်းခေါ်လျှင် CORS Block မဖြစ်အောင် ခွင့်ပြုခြင်း
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

# Index တည်ဆောက်ခြင်း
collection.create_index("period", unique=True)

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

def get_latest_row_data(driver):
    handle_popups(driver)
    try:
        row = driver.find_element(By.CSS_SELECTOR, ".GameRecord__C-body .van-row")
        period = row.find_element(By.CSS_SELECTOR, "div.van-col--9").text.strip()
        number = row.find_element(By.CSS_SELECTOR, ".GameRecord__C-body-num").text.strip()
        result = row.find_element(By.CSS_SELECTOR, "div.van-col--5 span").text.strip()
        return period, number, result
    except:
        return None, None, None

def check_and_log_patterns(trigger_period):
    latest_docs = list(collection.find().sort("period", -1).limit(10))
    if len(latest_docs) < 10:
        return
        
    current_7 = latest_docs[:7]
    eighth_item = latest_docs[7]
    
    is_all_big = all(d['result'] == 'Big' for d in current_7)
    is_all_small = all(d['result'] == 'Small' for d in current_7)
    
    # ၇ ကြိမ်ဆက်တိုက် (7-Streak) စစ်ဆေးခြင်း
    if is_all_big and eighth_item['result'] == 'Small':
        if not events_col.find_one({"trigger_period": trigger_period, "pattern_type": "7_STREAK_BIG"}):
            events_col.insert_one({
                "trigger_period": trigger_period,
                "pattern_type": "7_STREAK_BIG",
                "timestamp": latest_docs[0].get('timestamp')
            })
            print(f"🚨 Pattern Detected: 7-Streak BIG ({trigger_period})")
            
    elif is_all_small and eighth_item['result'] == 'Big':
        if not events_col.find_one({"trigger_period": trigger_period, "pattern_type": "7_STREAK_SMALL"}):
            events_col.insert_one({
                "trigger_period": trigger_period,
                "pattern_type": "7_STREAK_SMALL",
                "timestamp": latest_docs[0].get('timestamp')
            })
            print(f"🚨 Pattern Detected: 7-Streak SMALL ({trigger_period})")

    # ၈ ကြိမ် ဇစ်ဇက် (8-Period Alternating) စစ်ဆေးခြင်း
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
                "pattern_type": "8_ZIGZAG",
                "timestamp": latest_docs[0].get('timestamp')
            })
            print(f"🚨 Pattern Detected: 8-Period ZIGZAG ({trigger_period})")

def run_scraper_bot():
    """Cloud ပေါ်တွင် မျက်နှာပြင်မပါဘဲ ၂၄ နာရီပတ်လုံး Background Thread အနေဖြင့် မောင်းမည့် Bot"""
    print("🤖 Starting Headless Selenium Scraper Thread...")
    
    options = Options()
    options.add_argument("--headless=new") # Cloud ပေါ်တွင် Background မောင်းရန်
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    
    driver = webdriver.Chrome(options=options)
    last_period = ""
    
    try:
        driver.get("https://www.cklottery.club/#/home/AllLotteryGames/WinGo?id=1")
        time.sleep(5)
        
        while True:
            try:
                handle_popups(driver)
                period_el = driver.find_element(By.CLASS_NAME, "TimeLeft__C-id")
                p_num = period_el.text
                
                if len(p_num) < 10 or p_num == last_period:
                    time.sleep(1)
                    continue

                time.sleep(5) # ရလဒ်ထွက်လာရန် စောင့်ခြင်း
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
                        print(f"💾 Saved to Cloud MongoDB: {period} | {result}")
                    except DuplicateKeyError:
                        pass
                    last_period = p_num
                    
            except Exception as e:
                print(f"⚠️ Loop Error: {e}")
                time.sleep(2)
    finally:
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

# App စတင်ပွင့်သည်နှင့် Bot မောင်းမည့် Thread ကိုပါ တစ်ပါတည်း စတင်ခြင်း
@app.on_event("startup")
def startup_event():
    threading.Thread(target=run_scraper_bot, daemon=True).start()