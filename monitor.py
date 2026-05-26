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

print("=== 谷歌商店自动回复（长度优化+针对性回复版）===")

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL, GROQ_API_KEY]):
    raise Exception("缺少必要的环境变量")

# 读取缓存（不做任何改动）
replied_ids = set()
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f:
        replied_ids = set(line.strip() for line in f if line.strip())
    print(f"已加载 {len(replied_ids)} 条历史回复记录")
else:
    print("首次运行，创建新缓存文件")

# Google 认证
creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

def detect_language(text):
    """优先检测德语（äöüß），再检测法语（éèê等），然后中文等"""
    text_lower = text.lower()
    if 'ß' in text_lower or any(ch in "äöü" for ch in text_lower):
        return 'de'
    if any(ch in "éèêëàâäôöûüç" for ch in text_lower):
        return 'fr'
    if any('\u4e00' <= ch <= '\u9fff' for ch in text):
        return 'zh'
    return 'en'

def ai_generate_reply(text, rating, lang):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    lang_names = {'zh': '中文', 'en': 'English', 'fr': 'French', 'de': 'German'}
    target_lang = lang_names.get(lang, 'English')
    
    # 极简 prompt，强调长度和针对性
    prompt = f"""You are PitPat support. User review in {target_lang}. Reply in {target_lang} only. MAX 280 characters. Address the specific complaint directly.

Rating: {rating}/5
Review: "{text}"

Reply (short, specific, {target_lang}):"""
    
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 160,          # 控制长度约 220-280 字符
        "temperature": 0.7
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=25)
        if resp.status_code == 200:
            reply = resp.json()["choices"][0]["message"]["content"].strip()
            # 强制截断到 340 字符（留一点余量）
            if len(reply) > 340:
                reply = reply[:337] + "..."
            # 二次检查：如果目标是德语但回复混入法语，强制替换
            if lang == 'de' and any(ch in "éèêëàâô" for ch in reply):
                return "Vielen Dank für Ihr Feedback! Wir werden uns um Ihre Anliegen kümmern."
            return reply
        return None
    except Exception as e:
        print(f"AI 异常: {e}")
        return None

def get_reply(text, rating):
    lang = detect_language(text)
    print(f"检测到语言: {lang}")
    
    ai_reply = ai_generate_reply(text, rating, lang)
    if ai_reply:
        # 再次确保不超过 350
        if len(ai_reply) > 350:
            ai_reply = ai_reply[:347] + "..."
        return ai_reply
    
    # 降级模板（简短）
    fallbacks = {
        'zh': "感谢反馈！我们会针对性优化您提到的问题。",
        'en': "Thanks for your feedback! We'll address the issues you raised.",
        'fr': "Merci pour votre retour ! Nous traiterons vos préoccupations.",
        'de': "Danke für Ihr Feedback! Wir werden uns um Ihre Anliegen kümmern."
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
    # 最终长度安全锁
    if len(reply_text) > 350:
        reply_text = reply_text[:347] + "..."
        print(f"  ⚠️ 强制截断到 350 字符")
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
    print(f"  回复 ({len(reply)}字): {reply}")
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
