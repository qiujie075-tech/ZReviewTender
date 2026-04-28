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
    raise Exception("缺少 GROQ_API_KEY，请去 https://console.groq.com 免费注册获取")

def generate_token():
    headers = {"alg": "ES256", "kid": KEY_ID, "typ": "JWT"}
    payload = {
        "iss": ISSUER_ID,
        "exp": int(datetime.utcnow().timestamp()) + 20 * 60,
        "aud": "appstoreconnect-v1"
    }
    return jwt.encode(payload, PRIVATE_KEY, algorithm='ES256', headers=headers)

def get_reviews():
    url = f"https://api.appstoreconnect.apple.com/v1/apps/{APP_ID}/customerReviews?limit=50"
    headers = {"Authorization": f"Bearer {generate_token()}"}
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
        return ' '.join(reply.split())[:350] if reply else "Thank you for your feedback!"
    except Exception as e:
        print(f"AI 失败: {e}")
        return "Thank you for your feedback!"

def post_reply(review_id, reply_text):
    url = f"https://api.appstoreconnect.apple.com/v1/customerReviews/{review_id}/response"
    headers = {
        "Authorization": f"Bearer {generate_token()}",
        "Content-Type": "application/json"
    }
    payload = {
        "data": {
            "type": "customerReviewResponses",
            "attributes": {
                "responseBody": reply_text
            },
            "relationships": {
                "review": {
                    "data": {
                        "id": review_id,
                        "type": "customerReviews"
                    }
                }
            }
        }
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        print(f"发送回复响应: {resp.status_code}")
        if resp.status_code in (200, 201):
            print(f"✅ 回复成功 {review_id}")
            return True
        else:
            print(f"❌ 回复失败 {review_id}: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        print(f"❌ 回复异常 {review_id}: {e}")
        return False

def main():
    print("=== Apple AI 自动回复（无scope版）===")
    reviews = get_reviews()
    print(f"获取到 {len(reviews)} 条评论")
    unreplied = []
    for rev in reviews:
        if "relationships" in rev and "reply" in rev["relationships"]:
            continue
        text = rev.get("attributes", {}).get("body", "")
        if text:
            unreplied.append((rev["id"], text))
    print(f"未回复评论: {len(unreplied)} 条")
    success = 0
    for rid, text in unreplied:
        print(f"\n处理 {rid}: {text[:80]}...")
        reply = generate_ai_reply(text)
        print(f"AI 回复: {reply[:100]}...")
        if post_reply(rid, reply):
            success += 1
        time.sleep(2)
    if WEBHOOK_URL:
        data = {"msgtype": "text", "text": {"content": f"🍎 苹果 AI 回复完成：成功 {success}/{len(unreplied)}"}}
        try:
            requests.post(WEBHOOK_URL, json=data, timeout=10)
        except:
            pass
    print("执行完成")

if __name__ == "__main__":
    main()
