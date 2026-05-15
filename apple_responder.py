import os
import json
import time
import jwt
import requests
from datetime import datetime, timedelta

PRIVATE_KEY = os.environ.get('APPLE_PRIVATE_KEY')
KEY_ID = os.environ.get('APPLE_KEY_ID')
ISSUER_ID = os.environ.get('APPLE_ISSUER_ID')
APP_ID = "1598065258"  # 你的 Apple ID
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

print("=== Apple App Store 自动回复（修复版）===")

if not all([PRIVATE_KEY, KEY_ID, ISSUER_ID, WEBHOOK_URL, GROQ_API_KEY]):
    raise Exception("缺少必要的环境变量")

# 缓存已回复的评论 ID
CACHE_FILE = "apple_replied_ids.txt"
replied_ids = set()
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f:
        replied_ids = set(line.strip() for line in f if line.strip())
    print(f"已加载 {len(replied_ids)} 条历史回复记录")

def generate_token():
    """生成 JWT token - 不包含 scope 字段（关键修复）"""
    headers = {"alg": "ES256", "kid": KEY_ID, "typ": "JWT"}
    payload = {
        "iss": ISSUER_ID,
        "exp": int(datetime.utcnow().timestamp()) + 20 * 60,
        "aud": "appstoreconnect-v1"
        # 重要：不要添加 scope 字段，否则 POST 请求会返回 405
    }
    return jwt.encode(payload, PRIVATE_KEY, algorithm='ES256', headers=headers)

def get_reviews():
    """获取评论列表"""
    url = f"https://api.appstoreconnect.apple.com/v1/apps/{APP_ID}/customerReviews?limit=50&sort=-createdDate"
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

def detect_language(text):
    if any('\u4e00' <= ch <= '\u9fff' for ch in text):
        return 'zh'
    if any(ch in "éèêëàâäôöûüç" for ch in text.lower()):
        return 'fr'
    if any(ch in "äöüß" for ch in text.lower()):
        return 'de'
    return 'en'

def generate_ai_reply(text, rating, lang):
    """使用 Groq AI 生成回复"""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    
    lang_names = {'zh': '中文', 'en': 'English', 'fr': 'French', 'de': 'German'}
    target_lang = lang_names.get(lang, 'English')
    
    prompt = f"""Reply to this app review. MUST use {target_lang}. MAX 250 characters. Be helpful.

Rating: {rating}/5
Review: {text}

Reply (250 chars max, {target_lang} only):"""
    
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 150,
        "temperature": 0.7
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=20)
        if resp.status_code == 200:
            reply = resp.json()["choices"][0]["message"]["content"].strip()
            if len(reply) > 300:
                reply = reply[:297] + "..."
            return reply
        return None
    except Exception as e:
        print(f"AI 异常: {e}")
        return None

def get_reply(text, rating):
    lang = detect_language(text)
    print(f"检测到语言: {lang}")
    ai_reply = generate_ai_reply(text, rating, lang)
    if ai_reply:
        return ai_reply
    
    fallbacks = {
        'zh': "感谢您的反馈！我们会认真处理您提到的问题。",
        'en': "Thank you for your feedback! We will address your concerns.",
        'fr': "Merci pour votre retour ! Nous allons traiter vos préoccupations.",
        'de': "Danke für Ihr Feedback! Wir werden uns um Ihre Anliegen kümmern."
    }
    return fallbacks.get(lang, fallbacks['en'])

def post_reply(review_id, reply_text):
    """发送回复 - 使用正确的 API 端点"""
    url = "https://api.appstoreconnect.apple.com/v1/customerReviewResponses"
    headers = {
        "Authorization": f"Bearer {generate_token()}",
        "Content-Type": "application/json"
    }
    # 正确的 payload 结构：必须包含 data 包装
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
            print(f"  ✅ 回复成功: {review_id}")
            return True
        else:
            print(f"  ❌ 回复失败 {review_id}: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        print(f"  ❌ 回复异常 {review_id}: {e}")
        return False

def send_report(success, total, skipped):
    if WEBHOOK_URL:
        data = {"msgtype": "text", "text": {"content": f"🍎 Apple 回复完成：成功 {success}/{total}，跳过 {skipped} 条"}}
        try:
            requests.post(WEBHOOK_URL, json=data, timeout=10)
        except:
            pass

def main():
    print("获取评论...")
    reviews = get_reviews()
    print(f"获取到 {len(reviews)} 条评论")
    
    unreplied = []
    for rev in reviews:
        rid = rev.get("id")
        if not rid or rid in replied_ids:
            continue
        # 检查是否已有回复
        if "relationships" in rev and "reply" in rev["relationships"]:
            print(f"跳过 {rid}: 已有回复")
            replied_ids.add(rid)
            continue
        text = rev.get("attributes", {}).get("body", "")
        rating = rev.get("attributes", {}).get("rating", 3)
        if text:
            unreplied.append({"id": rid, "text": text, "rating": rating})
    
    print(f"未回复评论: {len(unreplied)} 条")
    
    success = 0
    new_ids = []
    for review in unreplied:
        rid = review["id"]
        text = review["text"]
        rating = review["rating"]
        print(f"\n处理 {rid}: 评分 {rating}星 - {text[:60]}...")
        reply = get_reply(text, rating)
        print(f"  回复 ({len(reply)}字): {reply}")
        if post_reply(rid, reply):
            success += 1
            new_ids.append(rid)
        time.sleep(2)
    
    if new_ids:
        with open(CACHE_FILE, "a") as f:
            for rid in new_ids:
                f.write(rid + "\n")
        print(f"✅ 已更新缓存，新增 {len(new_ids)} 条记录")
    
    send_report(success, len(unreplied), len(reviews) - len(unreplied))
    print("执行完成")

if __name__ == "__main__":
    main()
