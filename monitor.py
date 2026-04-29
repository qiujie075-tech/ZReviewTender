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

print("=== 谷歌商店自动回复（AI优化版）===")

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL, GROQ_API_KEY]):
    raise Exception("缺少必要的环境变量，请检查 Secrets")

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
    """使用 Groq 免费 AI 生成个性化回复"""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""You are a customer service assistant. Reply to this Google Play review.
Rating: {rating} stars
Review: "{text}"

Requirements:
- Reply in the SAME language as the review
- Be friendly, concise (under 200 characters)
- If rating is low (1-2), apologize and offer help
- If rating is high (4-5), thank the user
- If rating is 3, acknowledge feedback and promise improvement
- Do not mention AI, just reply as a human

Your reply:"""
    
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 200,
        "temperature": 0.7
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=20)
        if resp.status_code != 200:
            print(f"  AI 调用失败: {resp.status_code}")
            return None
        reply = resp.json()["choices"][0]["message"]["content"].strip()
        return reply[:350] if reply else None
    except Exception as e:
        print(f"  AI 异常: {e}")
        return None

def get_reply(text, rating):
    """先尝试 AI，失败则用固定模板"""
    ai_reply = ai_generate_reply(text, rating)
    if ai_reply:
        return ai_reply
    
    # 降级固定模板
    if rating >= 4:
        return "Thank you for your support! We'll continue to improve."
    elif rating == 3:
        return "Thanks for your feedback! We'll work on making it better."
    else:
        return "Sorry for the inconvenience. We're working on fixing the issues. Please contact us for help."

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
