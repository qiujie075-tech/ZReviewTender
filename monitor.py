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

def generate_reply(text):
    url = "https://router.huggingface.co/v1/chat/completions"
    headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}
    data = {
        "model": "moonshotai/Kimi-K2-Instruct-0905",
        "messages": [
            {"role": "system", "content": "Reply in the same language as the user. Keep short."},
            {"role": "user", "content": f"Reply to this review: {text}"}
        ],
        "max_tokens": 150
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        return resp.json()["choices"][0]["message"]["content"].strip()
    except:
        return "Thank you for your feedback!"

# 认证
creds = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(creds, scopes=["https://www.googleapis.com/auth/androidpublisher"])
service = build("androidpublisher", "v3", credentials=credentials)

# 获取评论
response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=50).execute()
reviews = response.get("reviews", [])

for review in reviews:
    rid = review["reviewId"]
    # 【关键】检查是否已有回复
    if "replies" in review and review["replies"]:
        print(f"跳过 {rid}，已有回复")
        continue
    
    text = review.get("comments", [{}])[0].get("userComment", {}).get("text", "")
    if not text:
        continue
    
    print(f"回复 {rid}: {text[:50]}...")
    reply = generate_reply(text)
    try:
        service.reviews().reply(packageName=PACKAGE_NAME, reviewId=rid, body={"replyText": reply}).execute()
        print(" 成功")
        time.sleep(2)
    except Exception as e:
        print(f" 失败: {e}")

# 发送通知
try:
    requests.post(WEBHOOK_URL, json={"msgtype": "text", "text": {"content": "自动回复执行完成"}})
except:
    pass
