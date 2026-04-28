import os
import json
import requests
import time
from datetime import datetime, timezone, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from langdetect import detect

SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
PACKAGE_NAME = os.environ.get('PACKAGE_NAME')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
HF_TOKEN = os.environ.get('HF_TOKEN')
CACHE_FILE = "replied_ids.txt"

print("=== 自动回复启动（安全防重复版）===")
print(f"PACKAGE_NAME = {PACKAGE_NAME}")

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL, HF_TOKEN]):
    raise Exception("缺少必要的环境变量")

# 读取缓存（仅用于记录，不作为主要判断依据）
replied_ids_cache = set()
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f:
        replied_ids_cache = set(line.strip() for line in f if line.strip())
    print(f"已加载 {len(replied_ids_cache)} 条缓存记录")

# Google 认证
creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

def detect_language(text):
    try:
        lang = detect(text)
        return 'zh' if lang.startswith('zh') else lang
    except:
        return 'en'

def generate_reply(comment_text):
    lang = detect_language(comment_text)
    lang_names = {
        'zh': 'Chinese', 'en': 'English', 'fr': 'French', 'de': 'German',
        'es': 'Spanish', 'ja': 'Japanese', 'ko': 'Korean', 'it': 'Italian',
        'pt': 'Portuguese', 'ru': 'Russian'
    }
    target_lang = lang_names.get(lang, 'English')
    url = "https://router.huggingface.co/v1/chat/completions"
    headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}
    user_prompt = f"The user's review is in {target_lang}. You must write your reply in {target_lang} only. Keep it short (under 300 characters), friendly and helpful. Do not use any other language. Reply to this review: {comment_text}"
    data = {
        "model": "moonshotai/Kimi-K2-Instruct-0905",
        "messages": [
            {"role": "system", "content": "You are a professional customer service assistant. Always follow the language instruction."},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 150
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"].strip()
        reply = ' '.join(reply.split())
        if len(reply) > 350:
            reply = reply[:350] + "..."
        if not reply:
            raise ValueError("Empty")
        # 后检验语言（可选）
        reply_lang = detect_language(reply)
        if reply_lang != lang and lang != 'en':
            print(f"  语言不匹配，使用模板")
            raise ValueError("Lang mismatch")
        return reply
    except Exception as e:
        print(f"  AI 降级: {e}")
        fallbacks = {
            'zh': "感谢您的反馈，我们会持续改进！",
            'en': "Thank you for your feedback! We will continue to improve.",
            'fr': "Merci pour votre retour ! Nous allons continuer à nous améliorer.",
            'de': "Vielen Dank für Ihr Feedback! Wir werden uns weiter verbessern.",
            'es': "¡Gracias por tu comentario! Seguiremos mejorando.",
            'ja': "ご意見ありがとうございます。今後とも改善してまいります。",
            'ko': "의견 주셔서 감사합니다. 계속해서 개선하겠습니다."
        }
        return fallbacks.get(lang, fallbacks['en'])

def post_reply(review_id, reply):
    try:
        service.reviews().reply(
            packageName=PACKAGE_NAME,
            reviewId=review_id,
            body={"replyText": reply}
        ).execute()
        print(f"  ✅ 回复成功: {review_id}")
        return True
    except Exception as e:
        print(f"  ❌ 回复失败: {review_id} - {e}")
        return False

def send_report(success, total, skipped):
    content = f"自动回复完成：成功 {success}/{total}\n已跳过（已有回复或超时）: {skipped}"
    data = {"msgtype": "text", "text": {"content": content}}
    try:
        requests.post(WEBHOOK_URL, json=data, timeout=10)
        print("通知推送成功")
    except Exception as e:
        print(f"通知失败: {e}")

# 获取评论
print("正在获取评论...")
try:
    response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=100).execute()
    reviews = response.get("reviews", [])
    print(f"API 返回评论总数: {len(reviews)}")
except Exception as e:
    print(f"获取评论失败: {e}")
    raise

# 时间过滤：只处理最近48小时内的评论
now = datetime.now(timezone.utc)
cutoff_time = now - timedelta(hours=48)

unreplied = []
skipped_count = 0
new_ids = []

for review in reviews:
    review_id = review.get("reviewId")
    if not review_id:
        continue

    # 1. 检查官方 API 回复状态（最权威）
    replies = review.get("replies")
    has_reply = False
    if replies:
        if isinstance(replies, list):
            for r in replies:
                if r.get("text"):
                    has_reply = True
                    break
        elif isinstance(replies, dict) and replies.get("text"):
            has_reply = True

    # 2. 获取评论时间
    comments = review.get("comments", [])
    if not comments:
        continue
    user_comment = comments[0].get("userComment", {})
    timestamp_seconds = user_comment.get("lastModified", {}).get("seconds", 0)
    if timestamp_seconds:
        comment_time = datetime.fromtimestamp(timestamp_seconds, tz=timezone.utc)
        is_recent = comment_time >= cutoff_time
    else:
        is_recent = False

    comment_text = user_comment.get("text", "")

    if has_reply:
        print(f"跳过 {review_id}: 已有回复")
        skipped_count += 1
        # 同步更新缓存
        new_ids.append(review_id)
        continue

    if not is_recent:
        print(f"跳过 {review_id}: 超过48小时")
        skipped_count += 1
        continue

    if not comment_text:
        print(f"跳过 {review_id}: 无文本")
        skipped_count += 1
        continue

    # 真正未回复的评论
    unreplied.append(review)
    print(f"待回复: {review_id} - {comment_text[:50]}...")

print(f"找到 {len(unreplied)} 条符合条件的未回复评论")

success = 0
for review in unreplied:
    rid = review["reviewId"]
    comment = review.get("comments", [{}])[0].get("userComment", {}).get("text", "")
    print(f"\n处理评论 {rid}: {comment[:80]}...")
    reply = generate_reply(comment)
    print(f"  生成的回复: {reply[:100]}...")
    if post_reply(rid, reply):
        success += 1
        new_ids.append(rid)
    time.sleep(2)

# 更新缓存文件（记录所有已处理的ID，包括跳过的）
if new_ids:
    with open(CACHE_FILE, "a") as f:
        for rid in set(new_ids):
            f.write(rid + "\n")
    print(f"已更新缓存，新增 {len(set(new_ids))} 条记录")

send_report(success, len(unreplied), skipped_count)
print("执行完成")
