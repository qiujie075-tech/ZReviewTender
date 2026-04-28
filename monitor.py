import os
import json
import requests
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build

SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
PACKAGE_NAME = os.environ.get('PACKAGE_NAME')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
HF_TOKEN = os.environ.get('HF_TOKEN')
PROCESSED_CACHE = "processed_ids.txt"

print("=== 自动回复启动（最终稳定版）===")

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL, HF_TOKEN]):
    raise Exception("缺少必要的环境变量")

# 读取已处理 ID 缓存
processed_ids = set()
if os.path.exists(PROCESSED_CACHE):
    with open(PROCESSED_CACHE, "r") as f:
        processed_ids = set(line.strip() for line in f if line.strip())
    print(f"已加载 {len(processed_ids)} 条已处理记录")

def generate_reply(text):
    """调用 Hugging Face API 生成回复，确保非空"""
    url = "https://router.huggingface.co/v1/chat/completions"
    headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}
    system = "Reply in the same language as the user. Keep short (max 300 characters)."
    data = {
        "model": "moonshotai/Kimi-K2-Instruct-0905",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Reply to this review: {text}"}
        ],
        "max_tokens": 150,
        "temperature": 0.7
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"].strip()
        if not reply:
            raise ValueError("Empty reply")
        reply = ' '.join(reply.split())
        if len(reply) > 350:
            reply = reply[:350] + "..."
        return reply
    except Exception as e:
        print(f"  AI 调用失败: {e}")
        return "Thank you for your feedback! We will continue to improve."

# Google 认证
creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

print("正在获取评论...")
response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=50).execute()
reviews = response.get("reviews", [])
print(f"API 返回评论总数: {len(reviews)}")

to_reply = []
for review in reviews:
    rid = review.get("reviewId")
    if not rid or rid in processed_ids:
        continue

    # 【核心判断】是否已有官方回复
    replies = review.get("replies")
    has_reply = False
    if replies:
        if isinstance(replies, list):
            for r in replies:
                if r.get("text"):
                    has_reply = True
                    break
        elif isinstance(replies, dict) and replies.get("text"):
            has_reply = True

    if has_reply:
        print(f"跳过 {rid}，已有回复")
        processed_ids.add(rid)
        continue

    comments = review.get("comments", [])
    if not comments:
        continue
    text = comments[0].get("userComment", {}).get("text", "").strip()
    if not text:
        continue

    to_reply.append((rid, text))
    print(f"待回复: {rid} - {text[:50]}...")

print(f"共 {len(to_reply)} 条待回复评论")

success = 0
for rid, text in to_reply:
    print(f"\n处理 {rid}: {text[:80]}...")
    reply = generate_reply(text)
    print(f"  回复内容: {reply[:100]}...")
    try:
        service.reviews().reply(
            packageName=PACKAGE_NAME,
            reviewId=rid,
            body={"replyText": reply}
        ).execute()
        print(f"  ✅ 成功")
        success += 1
    except Exception as e:
        print(f"  ❌ 失败: {e}")
    # 无论成功或失败，都加入缓存，避免重复尝试
    processed_ids.add(rid)
    time.sleep(2)

# 持久化缓存
with open(PROCESSED_CACHE, "w") as f:
    for rid in processed_ids:
        f.write(rid + "\n")
print(f"已更新缓存，共 {len(processed_ids)} 条记录")

# 发送通知
try:
    data = {"msgtype": "text", "text": {"content": f"自动回复完成。成功: {success}/{len(to_reply)}"}}
    requests.post(WEBHOOK_URL, json=data, timeout=10)
    print("通知推送成功")
except Exception as e:
    print(f"通知失败: {e}")

print("执行完成")
