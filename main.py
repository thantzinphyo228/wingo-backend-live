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
    # Long streaks (စံချိန်အရှည်ကြီးများ) ကိုပါ လှမ်းမိစေရန် limit ကို ၅၀ အထိ တိုးမြှင့်ထားပါတယ်
    latest_docs = list(collection.find().sort("period", -1).limit(50))
    if len(latest_docs) < 7:
        return
        
    first_result = latest_docs[0]['result'] # 'Big' သို့မဟုတ် 'Small'
    streak_count = 0
    
    # 🔄 လက်ရှိရလဒ်အတိုင်း နောက်ကြောင်းပြန်ပြီး Streak အစစ်အမှန်ကို ရေတွက်ခြင်း
    for doc in latest_docs:
        if doc['result'] == first_result:
            count += 1
        else:
            break
            
    # Streak က ၇ ကြိမ်နှင့်အထက် ရှိပါက Pattern အဖြစ် သတ်မှတ်မည်
    if streak_count >= 7:
        # ဤ Streak ကြီး လုံးဝစတင်ခဲ့သည့် ပွဲစဉ် (Period) ID ကို ရှာဖွေခြင်း
        streak_start_period = latest_docs[streak_count - 1]['period']
        pattern_type = f"{streak_count}_STREAK_{first_result.upper()}"
        
        # ယခု Streak စတင်မှုသည် ဒေတာဘေ့စ်ထဲတွင် မှတ်တမ်းတင်ပြီးသား ရှိ/မရှိ စစ်ဆေးခြင်း
        existing_event = events_col.find_one({"streak_start_period": streak_start_period})
        
        if not existing_event:
            # လုံးဝအသစ်စတင်သော Streak ဖြစ်ပါက ဒေတာအသစ်အဖြစ် စတင်သိမ်းဆည်းမည်
            events_col.insert_one({
                "trigger_period": trigger_period,
                "streak_start_period": streak_start_period,
                "pattern_type": pattern_type,
                "timestamp": latest_docs[0].get('timestamp')
            })
            print(f"🚨 New Pattern Inserted: {streak_count}-Streak {first_result.upper()} ({trigger_period})")
        else:
            # အကယ်၍ ရှိပြီးသား Streak အဟောင်း ဆက်လက်ရှည်လျားလာခြင်း ဖြစ်ပါက ဒေတာအသစ်ထပ်မတိုးဘဲ 
            # စာသားအမည်ကိုသာ တိုးမြှင့်ပေးမည် (ဥပမာ- 7-Streak မှ 8, 9-Streak သို့ ဒိုင်နမစ် အပ်ဒိတ်လုပ်ခြင်း)
            events_col.update_one(
                {"streak_start_period": streak_start_period},
                {"$set": {"pattern_type": pattern_type}}
            )
            print(f"🔄 Pattern Updated Dynamic: {streak_count}-Streak {first_result.upper()} ({trigger_period})")

    # -------------------------------------------------------------
    # ၈ ကြိမ် ဇစ်ဇက် (8-Period Alternating) စစ်ဆေးခြင်း (ပုံမှန်အတိုင်း ဆက်ထားပါမည်)
    # -------------------------------------------------------------
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
                    "streak_start_period": trigger_period, # ဇစ်ဇက်အတွက်ပါ standard ကိုက်ညီအောင်ထားခြင်း
                    "pattern_type": "8_ZIGZAG",
                    "timestamp": latest_docs[0].get('timestamp')
                })
                print(f"🚨 Pattern Detected: 8-Period ZIGZAG ({trigger_period})")

def run_scraper_bot():
    """Cloud ပေါ်တွင် မျက်နှာပြင်မပါဘဲ ၂၄ နာရီပတ်လုံး Background Thread အနေဖြင့် မောင်းမည့် Bot"""
    print("🤖 Starting Headless Selenium Scraper Thread...")
    
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080") # Headless တွင် Element များ ပိုမိုရှာဖွေရလွယ်ကူစေရန် Window Size သတ်မှတ်ခြင်း
    
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)
    last_period = ""
    
    try:
        driver.get("https://www.cklottery.club/#/home/AllLotteryGames/WinGo?id=1")
        time.sleep(6)
        handle_popups(driver)
        
        # ⏳ 30 Seconds ပွဲစဉ်သို့ ပြောင်းလဲခြင်း စနစ် (ပြန်လည်ထည့်သွင်းပေးထားပါသည်)
        print("⏳ Navigating to 30 Seconds Game Mode...")
        try:
            thirty_sec_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(text(), '30s')]")))
            driver.execute_script("arguments[0].click();", thirty_sec_btn)
        except:
            try:
                tabs = driver.find_elements(By.CLASS_NAME, "GameList__C-item")
                for tab in tabs:
                    if "30s" in tab.text:
                        driver.execute_script("arguments[0].click();", tab)
                        break
            except Exception as tab_err:
                print(f"⚠️ Tab selection fallback error: {tab_err}")
                
        time.sleep(4) # Tab ပြောင်းပြီးနောက် page ငြိမ်အောင် ခဏစောင့်ခြင်း
        
        while True:
            try:
                handle_popups(driver)
                
                # Cloud ပေါ်တွင် Explicit Wait စနစ်ဖြင့် Element ကို သေချာစွာ ရှာဖွေခြင်း
                period_el = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "TimeLeft__C-id")))
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

@app.on_event("startup")
def startup_event():
    threading.Thread(target=run_scraper_bot, daemon=True).start()