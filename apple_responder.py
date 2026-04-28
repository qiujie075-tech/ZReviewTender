import os
import json
import time
import jwt
import requests
from datetime import datetime, timedelta

PRIVATE_KEY = os.environ.get('APPLE_PRIVATE_KEY')
KEY_ID = os.environ.get('APPLE_KEY_ID')
ISSUER_ID = os.environ.get('APPLE_ISSUER_ID')
APP_ID = "1598065258"
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

if not GROQ_API_KEY:
    raise Exception("缺少 GROQ_API_KEY")

def generate_token(scope):
    headers = {"alg": "ES256", "kid": KEY_ID, "typ": "JWT"}
    payload = {
        "iss": ISSUER_ID,
        "exp": int(datetime.utcnow().timestamp()) + 20 * 60,
        "aud": "appstoreconnect-v1",
        "scope": scope
    }
    return jwt.encode(payload, PRIVATE_KEY, algorithm='ES256', headers=headers)

def get_reviews():
    url = f"https://api.appstoreconnect.apple.com/v1/apps/{APP_ID}/customerReviews?limit=50&sort=-createdDate"
    token = generate_token([f"GET /v1/apps/{APP_ID}/customerReviews"])
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"获取评论失败: {resp.status_code} {resp.text}")
            return []
        return resp.json().get("data", [])
    except Exception as e:
        print(f"获取评论异常: {e}")
        return []

def generate_ai_reply(text):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": "Reply in the same language as the user. Keep under 300 characters."},
            {"role": "user", "content": f"Reply to this review: {text}"}
        ],
        "max_tokens": 200
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=20)
        if resp.status_code != 200:
            print(f"Groq 错误: {resp.status_code} - {resp.text}")
            return "Thank you for your feedback!"
        reply = resp.json()["choices"][0]["message"]["content"].strip()
        if not reply:
            return "Thank you for your feedback!"
        return ' '.join(reply.split())[:350]
    except Exception as e:
        print(f"AI 失败: {e}")
        return "Thank you for your feedback!"

def post_reply(review_id, reply_text):
    url = f"https://api.appstoreconnect.apple.com/v1/customerReviews/{review_id}"
    token = generate_token([f"PATCH /v1/customerReviews/{review_id}"])
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "data": {
            "type": "customerReviews",
            "id": review_id,
            "relationships": {
                "response": {
                    "data": {
                        "type": "customerReviewResponses",
                        "attributes": {
                            "responseBody": reply_text
                        }
                    }
                }
            }
        }
    }
    try:
        resp = requests.patch(url, headers=headers, json=payload, timeout=15)
        print(f"回复响应: {resp.status_code}")
        if resp.status_code in (200, 201):
            print(f"✅ 成功 {review_id}")
            return True
        else:
            print(f"❌ 失败 {review_id}: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        print(f"❌ 异常 {review_id}: {e}")
        return False

def main():
    print("=== Apple AI 自动回复 ===")
    reviews = get_reviews()
    print(f"获取到 {len(reviews)} 条评论")
    unreplied = []
    for rev in reviews:
        if "relationships" in rev and "reply" in rev["relationships"]:
            continue
        text = rev.get("attributes", {}).get("body", "")
        if text:
            unreplied.append((rev["id"], text))
    print(f"未回复: {len(unreplied)} 条")
    success = 0
    for rid, text in unreplied:
        print(f"\n处理 {rid}: {text[:80]}...")
        reply = generate_ai_reply(text)
        print(f"AI 回复: {reply[:100]}...")
        if post_reply(rid, reply):
            success += 1
        time.sleep(2)
    if WEBHOOK_URL:
        data = {"msgtype": "text", "text": {"content": f"🍎 完成：成功 {success}/{len(unreplied)}"}}
        try:
            requests.post(WEBHOOK_URL, json=data, timeout=10)
        except:
            pass
    print("执行完成")

if __name__ == "__main__":
    main()
