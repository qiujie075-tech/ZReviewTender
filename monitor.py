import os
import json
import time
import requests
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
PACKAGE_NAME = os.environ.get('PACKAGE_NAME')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

print("=== 谷歌商店自动回复（基于官方最后回复时间）===")

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL]):
    raise Exception("缺少必要的环境变量")

creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

def detect_language(text):
    if any('\u4e00' <= ch <= '\u9fff' for ch in text):
        return 'zh'
    if any(ch in "éèêëàâäôöûüç" for ch in text.lower()):
        return 'fr'
    if any(ch in "äöüß" for ch in text.lower()):
        return 'de'
    return 'en'

def get_reply(text):
    lang = detect_language(text)
    replies = {
        'zh': "感谢您的反馈！我们会持续改进产品。",
        'fr': "Merci pour votre retour ! Nous allons continuer à nous améliorer.",
        'de': "Vielen Dank für Ihr Feedback! Wir werden uns weiter verbessern.",
        'en': "Thank you for your feedback! We will continue to improve."
    }
    return replies.get(lang, replies['en'])

def get_unreplied_reviews():
    try:
        response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=100).execute()
        reviews = response.get("reviews", [])
        print(f"总评论数: {len(reviews)}")
        unreplied = []
        for review in reviews:
            # 方法1：检查是否有回复（官方字段）
            replies = review.get("replies")
            if replies and isinstance(replies, list) and len(replies) > 0:
                print(f"跳过 {review.get('reviewId')}: 已有回复")
                continue
            # 方法2：检查最后回复时间（最权威）
            last_reply_time = review.get("lastModified", {}).get("seconds")
            if last_reply_time:
                # 如果最后修改时间不是评论文本的修改时间，而是回复的时间，则说明已回复
                # 但我们简单起见，只要存在 replies 列表就不处理
                pass
            # 提取评论文本
            comments = review.get("comments", [])
            if not comments:
                continue
            user_comment = comments[0].get("userComment", {})
            text = user_comment.get("text", "")
            if not text:
                continue
            unreplied.append({
                "id": review["reviewId"],
                "text": text
            })
        return unreplied
    except Exception as e:
        print(f"获取失败: {e}")
        return []

def post_reply(review_id, reply_text):
    try:
        service.reviews().reply(
            packageName=PACKAGE_NAME,
            reviewId=review_id,
            body={"replyText": reply_text}
        ).execute()
        print(f"  ✅ 成功: {review_id}")
        return True
    except Exception as e:
        print(f"  ❌ 失败: {review_id} - {e}")
        return False

def send_report(success, total):
    data = {"msgtype": "text", "text": {"content": f"谷歌回复完成：成功 {success}/{total}"}}
    try:
        requests.post(WEBHOOK_URL, json=data, timeout=10)
    except:
        pass

print("获取未回复评论...")
unreplied = get_unreplied_reviews()
print(f"未回复: {len(unreplied)} 条")

success = 0
for review in unreplied:
    rid = review["id"]
    text = review["text"]
    print(f"\n处理 {rid}: {text[:80]}...")
    reply = get_reply(text)
    print(f"回复: {reply}")
    if post_reply(rid, reply):
        success += 1
    time.sleep(2)

send_report(success, len(unreplied))
print("完成")
