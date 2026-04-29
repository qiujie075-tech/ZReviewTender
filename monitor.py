import os
import json
import time
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
PACKAGE_NAME = os.environ.get('PACKAGE_NAME')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
CACHE_FILE = "replied_ids.txt"

print("=== 谷歌商店自动回复（自然语气版）===")

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL, GROQ_API_KEY]):
    raise Exception("缺少必要的环境变量")

# 读取已回复记录
replied_ids = set()
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f:
        replied_ids = set(line.strip() for line in f if line.strip())
    print(f"已加载 {len(replied_ids)} 条历史回复记录")

# Google 认证
creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

def ai_generate_reply(text, rating):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # 更自然、更口语化的 Prompt
    prompt = f"""You are a friendly customer support agent for a fitness app called PitPat. Reply to this user review.

Rating: {rating} stars
Review: "{text}"

Rules:
1. Reply in the SAME language as the review (Chinese, English, French, German, etc.)
2. Keep it short and conversational — like a real person, not a robot
3. Be warm, empathetic, and helpful
4. Never say "we'll improve" without acknowledging their specific issue
5. Examples of good replies:
   - "Hey, sorry about that! Which part of the homepage is confusing? We'd love to fix it."
   - "Thanks for the kind words! Glad you're enjoying the app 😊"
   - "Ugh, that bug sounds annoying. We're on it — fix coming soon!"
6. Do NOT use: "Thank you for your feedback", "we will continue to improve", "please contact us"
7. Use emojis occasionally if it fits the tone

Write your reply (max 180 chars):"""
    
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 180,
        "temperature": 0.8
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=20)
        if resp.status_code != 200:
            print(f"  AI 调用失败: {resp.status_code}")
            return None
        reply = resp.json()["choices"][0]["message"]["content"].strip()
        return reply[:300] if reply else None
    except Exception as e:
        print(f"  AI 异常: {e}")
        return None

def get_reply(text, rating):
    ai_reply = ai_generate_reply(text, rating)
    if ai_reply:
        return ai_reply
    
    # 降级模板（作为备用）
    if rating >= 4:
        return "Thanks! 😊 Glad you're enjoying it!"
    elif rating == 3:
        return "Thanks for the feedback! We'll work on making it better."
    else:
        return "Sorry about that! We're looking into it."

def get_all_reviews():
    try:
        response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=100).execute()
        reviews = response.get("reviews", [])
        print(f"API 返回评论总数: {len(reviews)}")
        
        result = []
        for review in reviews:
            review_id = review.get("reviewId")
            if not review_id:
                continue
            comments = review.get("comments", [])
            if not comments:
                continue
            user_comment = comments[0].get("userComment", {})
            text = user_comment.get("text", "")
            star_rating = user_comment.get("starRating", 3)
            if not text:
                continue
            result.append({
                "id": review_id,
                "text": text,
                "rating": star_rating
            })
        return result
    except Exception as e:
        print(f"获取评论失败: {e}")
        return []

def post_reply(review_id, reply_text):
    try:
        service.reviews().reply(
            packageName=PACKAGE_NAME,
            reviewId=review_id,
            body={"replyText": reply_text}
        ).execute()
        print(f"  ✅ 回复成功: {review_id}")
        return True
    except Exception as e:
        print(f"  ❌ 回复失败: {review_id} - {e}")
        return False

def send_report(success, total, skipped):
    if WEBHOOK_URL:
        data = {"msgtype": "text", "text": {"content": f"谷歌回复完成：成功 {success}/{total}，跳过 {skipped} 条"}}
        try:
            requests.post(WEBHOOK_URL, json=data, timeout=10)
        except:
            pass

print("获取所有评论...")
all_reviews = get_all_reviews()
print(f"共获取 {len(all_reviews)} 条评论")

to_reply = []
for review in all_reviews:
    if review["id"] in replied_ids:
        continue
    to_reply.append(review)
print(f"需要回复: {len(to_reply)} 条")

success = 0
new_ids = []
for review in to_reply:
    rid = review["id"]
    text = review["text"]
    rating = review["rating"]
    print(f"\n处理 {rid}: 评分 {rating}星 - {text[:80]}...")
    reply = get_reply(text, rating)
    print(f"  回复: {reply}")
    if post_reply(rid, reply):
        success += 1
        new_ids.append(rid)
    time.sleep(2)

if new_ids:
    with open(CACHE_FILE, "a") as f:
        for rid in new_ids:
            f.write(rid + "\n")
    print(f"已更新缓存，新增 {len(new_ids)} 条记录")

send_report(success, len(to_reply), len(all_reviews) - len(to_reply))
print("执行完成")
