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

print("=== 自动回复启动（修复版）===")

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL, HF_TOKEN]):
    raise Exception("缺少必要的环境变量")

creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

def generate_reply(comment_text):
    """让 AI 自动识别语言并回复，不依赖外部检测库"""
    url = "https://router.huggingface.co/v1/chat/completions"
    headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}
    # 让模型自己判断语言并回复
    system_prompt = (
        "You are a customer service assistant. Reply to the user's review in the SAME language as the review. "
        "If the review is in French, reply in French; if in English, reply in English; if in Chinese, reply in Chinese, etc. "
        "Be friendly, concise, and helpful."
    )
    data = {
        "model": "moonshotai/Kimi-K2-Instruct-0905",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Please reply to this review: {comment_text}"}
        ],
        "temperature": 0.7,
        "max_tokens": 150
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"].strip()
        print(f"  ✅ AI 回复生成成功")
        return reply
    except Exception as e:
        print(f"  ❌ AI 调用失败: {e}")
        return "Thank you for your feedback!"  # 保底英文

def post_reply(review_id, reply):
    try:
        service.reviews().reply(
            packageName=PACKAGE_NAME,
            reviewId=review_id,
            body={"replyText": reply}
        ).execute()
        print(f"  ✅ 回复成功: {review_id}")
        return True
    except Exception as e:
        print(f"  ❌ 回复失败: {review_id} - {e}")
        return False

def send_report(success, total):
    data = {"msgtype": "text", "text": {"content": f"自动回复完成：成功 {success}/{total}"}}
    try:
        requests.post(WEBHOOK_URL, json=data, timeout=10)
    except Exception as e:
        print(f"通知失败: {e}")

# 获取更多评论（尝试 100 条）
print("正在获取评论...")
try:
    response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=100).execute()
    reviews = response.get("reviews", [])
    print(f"API 返回评论总数: {len(reviews)}")
except Exception as e:
    print(f"获取评论失败: {e}")
    raise

# 严格判断未回复：replies 字段不存在，或者存在但为空列表/空字典
unreplied = []
processed_ids = set()  # 防止重复处理同一条

for idx, review in enumerate(reviews):
    review_id = review.get("reviewId")
    if not review_id or review_id in processed_ids:
        continue

    # 判断是否有回复：检查 replies 字段
    replies = review.get("replies")
    has_reply = False
    if replies:
        # 如果 replies 是一个列表且长度 > 0
        if isinstance(replies, list) and len(replies) > 0:
            has_reply = True
        # 如果 replies 是一个字典且非空
        elif isinstance(replies, dict) and replies:
            has_reply = True

    print(f"评论 {idx+1}: ID={review_id}, 已有回复={has_reply}")

    if not has_reply:
        comments = review.get("comments", [])
        if comments:
            user_comment = comments[0].get("userComment", {})
            text = user_comment.get("text", "")
            if text:
                unreplied.append(review)
                processed_ids.add(review_id)
                print(f"  -> 待回复，内容: {text[:60]}...")

print(f"找到 {len(unreplied)} 条未回复评论")

success = 0
for review in unreplied:
    rid = review["reviewId"]
    comments = review.get("comments", [{}])
    user_comment = comments[0].get("userComment", {})
    comment_text = user_comment.get("text", "")
    print(f"\n处理评论 {rid}: {comment_text[:80]}...")
    reply = generate_reply(comment_text)
    if post_reply(rid, reply):
        success += 1
    time.sleep(2)  # 避免频率限制

send_report(success, len(unreplied))
print("执行完成")
