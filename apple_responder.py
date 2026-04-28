import os
import json
import time
import jwt
import requests
from datetime import datetime, timedelta

# ========== 环境变量 ==========
PRIVATE_KEY = os.environ.get('APPLE_PRIVATE_KEY')
KEY_ID = os.environ.get('APPLE_KEY_ID')
ISSUER_ID = os.environ.get('APPLE_ISSUER_ID')
APP_ID = "1598065258"  # 你的 Apple ID，固定
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')  # 新增：Groq API Key（免费）

if not GROQ_API_KEY:
    raise Exception("缺少 GROQ_API_KEY，请去 https://console.groq.com 免费注册获取")

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
    """获取评论列表"""
    url = f"https://api.appstoreconnect.apple.com/v1/apps/{APP_ID}/customerReviews?limit=50"
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
    """使用 Groq 免费 API 生成 AI 回复"""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "llama3-8b-8192",  # 完全免费，速度快
        "messages": [
            {"role": "system", "content": "You are a customer service assistant. Reply in the SAME language as the user. Keep under 300 characters. Be friendly and helpful."},
            {"role": "user", "content": f"Reply to this review: {text}"}
        ],
        "temperature": 0.7,
        "max_tokens": 200
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=20)
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"].strip()
        if not reply:
            return "Thank you for your feedback!"
        reply = ' '.join(reply.split())
        if len(reply) > 350:
            reply = reply[:350] + "..."
        return reply
    except Exception as e:
        print(f"Groq AI 调用失败: {e}")
        # 降级为模板回复
        if any('\u4e00' <= ch <= '\u9fff' for ch in text):
            return "感谢您的反馈，我们会持续改进！"
        return "Thank you for your feedback! We will continue to improve."

def post_reply(review_id, reply_text):
    """发送 AI 生成的回复（苹果官方正确 endpoint）"""
    url = "https://api.appstoreconnect.apple.com/v1/customerReviewResponses"
    token = generate_token(["POST /v1/customerReviewResponses"])
    headers = {
        "Authorization": f"Bearer {token}",
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
    print("=== Apple App Store AI 自动回复（Groq免费版）===")
    
    # 获取评论
    reviews = get_reviews()
    print(f"获取到 {len(reviews)} 条评论")
    
    # 筛选未回复的
    unreplied = []
    for rev in reviews:
        if "relationships" in rev and "reply" in rev["relationships"]:
            continue
        text = rev.get("attributes", {}).get("body", "")
        if text:
            unreplied.append((rev["id"], text))
    
    print(f"未回复评论: {len(unreplied)} 条")
    
    # 逐条生成 AI 回复并发布
    success = 0
    for rid, text in unreplied:
        print(f"\n处理 {rid}: {text[:80]}...")
        reply = generate_ai_reply(text)
        print(f"AI 回复: {reply[:100]}...")
        if post_reply(rid, reply):
            success += 1
        time.sleep(2)
    
    # 发送报告到飞书/钉钉
    if WEBHOOK_URL:
        data = {"msgtype": "text", "text": {"content": f"🍎 苹果 AI 回复完成：成功 {success}/{len(unreplied)}"}}
        try:
            requests.post(WEBHOOK_URL, json=data, timeout=10)
            print("通知推送成功")
        except Exception as e:
            print(f"通知失败: {e}")
    
    print("执行完成")

if __name__ == "__main__":
    main()
