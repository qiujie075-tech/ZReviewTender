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

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL, HF_TOKEN]):
    raise Exception("缺少必要的环境变量")

creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

def generate_reply(text):
    url = "https://router.huggingface.co/v1/chat/completions"
    headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}
    data = {
        "model": "moonshotai/Kimi-K2-Instruct-0905",
        "messages": [
            {"role": "system", "content": "你是专业的客服助手，请用中文友好、简洁地回复用户评论。"},
            {"role": "user", "content": f"请回复这条评论：{text}"}
        ],
        "temperature": 0.7,
        "max_tokens": 150
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"AI 调用失败: {e}")
        return "感谢您的反馈，我们会持续改进！"

def post_reply(review_id, reply):
    service.reviews().reply(
        packageName=PACKAGE_NAME,
        reviewId=review_id,
        body={"replyText": reply}
    ).execute()
    print(f"✅ 已回复 {review_id}")

def send_report(success, total):
    data = {"msgtype": "text", "text": {"content": f"自动回复完成：成功 {success}/{total}"}}
    try:
        requests.post(WEBHOOK_URL, json=data, timeout=10)
    except Exception as e:
        print(f"通知发送失败: {e}")

response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=20).execute()
reviews = response.get("reviews", [])
unreplied = [r for r in reviews if "replies" not in r or not r["replies"]]
print(f"找到 {len(unreplied)} 条未回复评论")

success = 0
for review in unreplied:
    rid = review["reviewId"]
    comment = review.get("comments", [{}])[0].get("userComment", {}).get("text", "")
    if not comment:
        continue
    print(f"处理评论 {rid}: {comment[:50]}...")
    reply = generate_reply(comment)
    try:
        post_reply(rid, reply)
        success += 1
    except Exception as e:
        print(f"回复失败 {rid}: {e}")
    time.sleep(2)

send_report(success, len(unreplied))
print("执行完成")
