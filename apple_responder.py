import os
import json
import time
import jwt
import requests
from datetime import datetime, timedelta

PRIVATE_KEY = os.environ.get('APPLE_PRIVATE_KEY')
KEY_ID = os.environ.get('APPLE_KEY_ID')
ISSUER_ID = os.environ.get('APPLE_ISSUER_ID')
BUNDLE_ID = os.environ.get('APPLE_BUNDLE_ID')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
HF_TOKEN = os.environ.get('HF_TOKEN')

if not all([PRIVATE_KEY, KEY_ID, ISSUER_ID, BUNDLE_ID, WEBHOOK_URL, HF_TOKEN]):
    raise Exception("缺少必要的环境变量，请检查 GitHub Secrets")

def generate_token():
    headers = {"alg": "ES256", "kid": KEY_ID, "typ": "JWT"}
    payload = {
        "iss": ISSUER_ID,
        "exp": int(datetime.utcnow().timestamp()) + 20 * 60,
        "aud": "appstoreconnect-v1"
    }
    return jwt.encode(payload, PRIVATE_KEY, algorithm='ES256', headers=headers)

def get_reviews():
    # 增加 sort 参数，添加 User-Agent
    url = f"https://api.appstoreconnect.apple.com/v1/customerReviews?filter[appBundleId]={BUNDLE_ID}&limit=50&sort=-createdDate"
    headers = {
        "Authorization": f"Bearer {generate_token()}",
        "User-Agent": "AutoReplyBot/1.0"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"苹果 API 响应状态: {resp.status_code}")
        if resp.status_code != 200:
            print(f"错误响应体: {resp.text}")
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as e:
        print(f"获取苹果评论失败: {e}")
        return []

def generate_reply(text):
    url = "https://router.huggingface.co/v1/chat/completions"
    headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}
    system_prompt = "Reply in the same language as the user. Keep short (max 300 characters)."
    data = {
        "model": "moonshotai/Kimi-K2-Instruct-0905",
        "messages": [
            {"role": "system", "content": system_prompt},
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
            raise ValueError("Empty")
        reply = ' '.join(reply.split())
        if len(reply) > 350:
            reply = reply[:350] + "..."
        return reply
    except Exception as e:
        print(f"AI 调用失败: {e}")
        return "Thank you for your feedback! We will continue to improve."

def post_reply(review_id, reply):
    url = f"https://api.appstoreconnect.apple.com/v1/customerReviews/{review_id}/reply"
    headers = {
        "Authorization": f"Bearer {generate_token()}",
        "Content-Type": "application/json",
        "User-Agent": "AutoReplyBot/1.0"
    }
    data = {"data": {"attributes": {"body": reply}}}
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        if resp.status_code in (200, 201):
            print(f"✅ 回复成功: {review_id}")
            return True
        else:
            print(f"❌ 回复失败 {review_id}: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        print(f"❌ 回复失败 {review_id}: {e}")
        return False

def send_report(success, total):
    if WEBHOOK_URL:
        data = {"msgtype": "text", "text": {"content": f"Apple 自动回复完成：成功 {success}/{total}"}}
        try:
            requests.post(WEBHOOK_URL, json=data, timeout=10)
        except Exception as e:
            print(f"通知失败: {e}")

def main():
    print("=== Apple App Store 自动回复启动 ===")
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
        reply = generate_reply(text)
        if post_reply(rid, reply):
            success += 1
        time.sleep(2)
    send_report(success, len(unreplied))
    print("执行完成")

if __name__ == "__main__":
    main()
