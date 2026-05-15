import os
import json
import time
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
PACKAGE_NAME = os.environ.get('PACKAGE_NAME')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
CACHE_FILE = "replied_ids.txt"

print("=== 谷歌商店自动回复（Groq AI增强版 - 强制长度限制）===")

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL, GROQ_API_KEY]):
    raise Exception("缺少必要的环境变量")

# 读取缓存
replied_ids = set()
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f:
        replied_ids = set(line.strip() for line in f if line.strip())
    print(f"已加载 {len(replied_ids)} 条历史回复记录")

# Google 认证
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
    if any('\u3040' <= ch <= '\u30ff' for ch in text):
        return 'ja'
    if any('\uac00' <= ch <= '\ud7af' for ch in text):
        return 'ko'
    return 'en'

def ai_generate_reply(text, rating, lang):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    lang_names = {
        'zh': '中文', 'en': 'English', 'fr': 'French',
        'de': 'German', 'ja': 'Japanese', 'ko': 'Korean'
    }
    target_lang = lang_names.get(lang, 'English')
    
    # 重要：在 prompt 中明确要求短回复
    prompt = f"""你是 PitPat 应用的官方客服。用户评价如下。你必须用 {target_lang} 回复，绝对不能使用其他语言。

用户评分：{rating} 星
用户评价："{text}"

回复要求：
1. 【最重要】你必须用 {target_lang} 回复，一个字都不能用其他语言
2. 回复必须简短，**不超过 280 个字符**
3. 针对用户的核心问题直接回应
4. 如果用户提到隐私问题，说明可以在设置中关闭权限
5. 保持诚恳、专业
6. 不要使用套话如"我们已收到反馈"

请用 {target_lang} 简短回复（280字符以内）："""
    
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 200,  # 限制 token 数，约为 150-200 字符
        "temperature": 0.7
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=25)
        if resp.status_code == 200:
            reply = resp.json()["choices"][0]["message"]["content"].strip()
            # 强制截断到 350 字符（Google Play 限制）
            if len(reply) > 350:
                reply = reply[:347] + "..."
            return reply
        else:
            print(f"AI 调用失败: {resp.status_code}")
            return None
    except Exception as e:
        print(f"AI 异常: {e}")
        return None

def get_reply(text, rating):
    lang = detect_language(text)
    print(f"检测到语言: {lang}")
    
    ai_reply = ai_generate_reply(text, rating, lang)
    if ai_reply and len(ai_reply) <= 350:
        return ai_reply
    
    # 降级模板（确保长度符合要求）
    fallbacks = {
        'zh': "感谢您的反馈！我们会认真处理您提到的问题。",
        'en': "Thank you for your feedback! We will address your concerns.",
        'fr': "Merci pour votre retour ! Nous allons traiter vos préoccupations.",
        'de': "Danke für Ihr Feedback! Wir werden uns darum kümmern.",
        'ja': "ご意見ありがとうございます。真剣に検討いたします。",
        'ko': "의견 주셔서 감사합니다. 진지하게 처리하겠습니다."
    }
    return fallbacks.get(lang, fallbacks['en'])

def get_all_reviews():
    try:
        response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=100).execute()
        reviews = response.get("reviews", [])
        print(f"API 返回评论总数: {len(reviews)}")
        result = []
        for review in reviews:
            review_id = review.get("reviewId")
            if not review_id:
                continue
            comments = review.get("comments", [])
            if not comments:
                continue
            user_comment = comments[0].get("userComment", {})
            text = user_comment.get("text", "")
            star_rating = user_comment.get("starRating", 3)
            if not text:
                continue
            result.append({"id": review_id, "text": text, "rating": star_rating})
        return result
    except Exception as e:
        print(f"获取评论失败: {e}")
        return []

def post_reply(review_id, reply_text):
    # 额外检查长度
    if len(reply_text) > 350:
        print(f"  ⚠️ 回复过长 ({len(reply_text)} 字符)，强制截断")
        reply_text = reply_text[:347] + "..."
    try:
        service.reviews().reply(
            packageName=PACKAGE_NAME,
            reviewId=review_id,
            body={"replyText": reply_text}
        ).execute()
        print(f"  ✅ 回复成功: {review_id}")
        return True
    except Exception as e:
        print(f"  ❌ 回复失败: {review_id} - {e}")
        return False

def send_report(success, total, skipped):
    if WEBHOOK_URL:
        data = {"msgtype": "text", "text": {"content": f"谷歌回复完成：成功 {success}/{total}，跳过 {skipped} 条"}}
        try:
            requests.post(WEBHOOK_URL, json=data, timeout=10)
        except:
            pass

print("获取所有评论...")
all_reviews = get_all_reviews()
print(f"共获取 {len(all_reviews)} 条评论")

to_reply = []
for review in all_reviews:
    if review["id"] in replied_ids:
        continue
    to_reply.append(review)

print(f"需要回复: {len(to_reply)} 条")

if len(to_reply) == 0:
    send_report(0, 0, len(all_reviews))
    print("没有新评论需要回复")
    exit(0)

new_ids = []
for review in to_reply:
    rid = review["id"]
    text = review["text"]
    rating = review["rating"]
    print(f"\n处理 {rid}: 评分 {rating}星 - {text[:80]}...")
    reply = get_reply(text, rating)
    print(f"  回复长度: {len(reply)} 字符")
    print(f"  回复: {reply}")
    if post_reply(rid, reply):
        new_ids.append(rid)
    time.sleep(2)

if new_ids:
    with open(CACHE_FILE, "a") as f:
        for rid in new_ids:
            f.write(rid + "\n")
    print(f"✅ 已更新缓存，新增 {len(new_ids)} 条记录")

send_report(len(new_ids), len(to_reply), len(all_reviews) - len(to_reply))
print("执行完成")
