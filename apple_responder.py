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
APP_ID = "1598065258"  # 你的 App Apple ID
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
HF_TOKEN = os.environ.get('HF_TOKEN')

# ========== 辅助函数：生成带 scope 的 Token ==========
def generate_token(allowed_scope):
    """
    allowed_scope: 一个字符串列表，例如 ["GET /v1/apps/1234567890/customerReviews"]
    """
    if not allowed_scope:
        allowed_scope = []
    
    headers = {"alg": "ES256", "kid": KEY_ID, "typ": "JWT"}
    payload = {
        "iss": ISSUER_ID,
        "exp": int(datetime.utcnow().timestamp()) + 20 * 60,  # 20分钟有效
        "aud": "appstoreconnect-v1",
        "scope": allowed_scope  # 关键：限定此 token 的权限范围
    }
    token = jwt.encode(payload, PRIVATE_KEY, algorithm='ES256', headers=headers)
    return token

# ========== 1. 获取评论 ==========
def get_reviews():
    """使用正确 endpoint 获取评论列表"""
    url = f"https://api.appstoreconnect.apple.com/v1/apps/{APP_ID}/customerReviews?limit=50&sort=-createdDate"
    # 生成一个只允许 GET 操作的 token
    token = generate_token([f"GET /v1/apps/{APP_ID}/customerReviews"])
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"苹果 API 响应状态 (获取评论): {resp.status_code}")
        if resp.status_code != 200:
            print(f"错误响应体: {resp.text}")
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])
    except Exception as e:
        print(f"获取苹果评论失败: {e}")
        return []

# ========== 2. AI 生成回复 ==========
def generate_reply(text):
    """调用 Hugging Face API 生成回复 (保持不变)"""
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

# ========== 3. 发送回复 ==========
def post_reply(review_id, reply):
    """使用 customerReviewResponses 资源发送回复"""
    url = "https://api.appstoreconnect.apple.com/v1/customerReviewResponses"
    # 生成一个只允许 POST 此特定资源的 token
    token = generate_token(["POST /v1/customerReviewResponses"])
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "data": {
            "attributes": {
                "responseBody": reply
            },
            "relationships": {
                "review": {
                    "data": {
                        "id": review_id,
                        "type": "customerReviews"
                    }
                }
            },
            "type": "customerReviewResponses"
        }
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201):
            print(f"✅ 回复成功: {review_id}")
            return True
        else:
            print(f"❌ 回复失败 {review_id}: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        print(f"❌ 回复失败 {review_id}: {e}")
        return False

# ========== 4. 发送通知 ==========
def send_report(success, total):
    if WEBHOOK_URL:
        data = {"msgtype": "text", "text": {"content": f"Apple 自动回复完成：成功 {success}/{total}"}}
        try:
            requests.post(WEBHOOK_URL, json=data, timeout=10)
        except Exception as e:
            print(f"通知失败: {e}")

# ========== 主逻辑 ==========
def main():
    print("=== Apple App Store 自动回复启动 (修复版) ===")
    
    # 1. 获取评论
    reviews = get_reviews()
    print(f"获取到 {len(reviews)} 条评论")
    
    # 2. 筛选未回复的评论
    unreplied = []
    for rev in reviews:
        # 检查是否有 reply relationship
        if "relationships" in rev and "reply" in rev["relationships"]:
            continue
        text = rev.get("attributes", {}).get("body", "")
        if text:
            unreplied.append((rev["id"], text))
    
    print(f"未回复评论: {len(unreplied)} 条")
    
    # 3. 逐条回复
    success = 0
    for rid, text in unreplied:
        print(f"\n处理 {rid}: {text[:80]}...")
        reply = generate_reply(text)
        if post_reply(rid, reply):
            success += 1
        time.sleep(2)  # 避免请求过快
    
    # 4. 发送报告
    send_report(success, len(unreplied))
    print("执行完成")

if __name__ == "__main__":
    main()
