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

print("=== 谷歌商店自动回复（Git 缓存版）===")

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL, GROQ_API_KEY]):
    raise Exception("缺少必要的环境变量")

# 读取缓存（直接从仓库中的文件）
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
    # 德语特有字符（注意：äöü也出现在法语中，但ß是德语独有）
    if 'ß' in text_lower or any(ch in "äöü" for ch in text_lower):
        # 进一步排除法语：如果同时有大量 éè 等，仍判德语，因为德语也有少量外来词
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
    
    prompt = f"""你是 PitPat 客服。用户评价是 {target_lang}。你必须用 {target_lang} 回复，严禁使用其他任何语言。

评分：{rating}/5
评价："{text}"

回复要求：
1. 只使用 {target_lang}
2. 针对用户的具体问题回应
3. 长度 200-300 字符
4. 诚恳、简洁

请用 {target_lang} 回复："""
    
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 200,
        "temperature": 0.7
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=25)
        if resp.status_code == 200:
            reply = resp.json()["choices"][0]["message"]["content"].strip()
            # 后处理：如果目标语言是德语但回复中含有法语字符，强制修正
            if lang == 'de' and any(ch in "éèêëàâô" for ch in reply):
                print("  ⚠️ AI 回复混入法语，使用德语模板")
                return "Vielen Dank für Ihr Feedback! Wir werden uns um Ihre Anliegen kümmern."
            if len(reply) > 350:
                reply = reply[:347] + "..."
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
        return ai_reply
    
    fallbacks = {
        'zh': "感谢您的反馈！我们会认真处理您提到的问题，并持续优化产品体验。",
        'en': "Thank you for your feedback! We will address your concerns and continue to improve.",
        'fr': "Merci pour votre retour ! Nous allons traiter vos préoccupations et continuer à nous améliorer.",
        'de': "Vielen Dank für Ihr Feedback! Wir werden uns um Ihre Anliegen kümmern und uns weiter verbessern."
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
    if len(reply_text) > 350:
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
    print(f"  回复 ({len(reply)}字): {reply}")
    if post_reply(rid, reply):
        new_ids.append(rid)
    time.sleep(2)

if new_ids:
    # 追加到缓存文件
    with open(CACHE_FILE, "a") as f:
        for rid in new_ids:
            f.write(rid + "\n")
    print(f"✅ 已更新缓存，新增 {len(new_ids)} 条记录")

send_report(len(new_ids), len(to_reply), len(all_reviews) - len(to_reply))
print("执行完成")
