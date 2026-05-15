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

print("=== 谷歌商店自动回复（Groq AI增强版）===")

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL, GROQ_API_KEY]):
    raise Exception("缺少必要的环境变量，请确保 GROQ_API_KEY 已配置")

# 读取缓存
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
    """使用 Groq AI 生成针对性回复"""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""你是 PitPat 应用的官方客服。请根据以下用户评价生成一个友好、真诚的回复。

用户评分：{rating} 星
用户评价："{text}"

回复要求：
1. 使用与评价相同的语言（中文、英文、法文等）
2. 针对用户提出的每个具体问题逐一回应
3. 如果用户提到隐私权限问题，需要说明我们非常重视隐私，可以关闭不必要的权限
4. 如果用户提到功能问题，可以说明正在改进或提供帮助
5. 保持诚恳、专业，不要使用"我们已收到反馈"这种套话
6. 回复长度控制在 150 字以内

你的回复："""
    
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 250,
        "temperature": 0.7
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=20)
        if resp.status_code == 200:
            reply = resp.json()["choices"][0]["message"]["content"].strip()
            return reply
        else:
            print(f"AI 调用失败: {resp.status_code}")
            return None
    except Exception as e:
        print(f"AI 异常: {e}")
        return None

def get_reply(text, rating):
    """优先使用 AI，失败时降级为模板"""
    ai_reply = ai_generate_reply(text, rating)
    if ai_reply:
        return ai_reply
    # 降级模板
    return "感谢您的反馈！我们会认真处理您提到的问题。"

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
            result.append({"id": review_id, "text": text, "rating": star_rating})
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

if len(to_reply) == 0:
    send_report(0, 0, len(all_reviews))
    print("没有新评论需要回复")
    exit(0)

new_ids = []
for review in to_reply:
    rid = review["id"]
    text = review["text"]
    rating = review["rating"]
    print(f"\n处理 {rid}: 评分 {rating}星 - {text[:80]}...")
    reply = get_reply(text, rating)
    print(f"  回复: {reply}")
    if post_reply(rid, reply):
        new_ids.append(rid)
    time.sleep(2)

if new_ids:
    with open(CACHE_FILE, "a") as f:
        for rid in new_ids:
            f.write(rid + "\n")
    print(f"✅ 已更新缓存，新增 {len(new_ids)} 条记录")

send_report(len(new_ids), len(to_reply), len(all_reviews) - len(to_reply))
print("执行完成")
