import os
import json
import requests
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
from langdetect import detect

SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
PACKAGE_NAME = os.environ.get('PACKAGE_NAME')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
HF_TOKEN = os.environ.get('HF_TOKEN')
CACHE_FILE = "replied_ids.txt"

print("=== 自动回复启动（防重复+语言修正）===")

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL, HF_TOKEN]):
    raise Exception("缺少必要的环境变量")

# 读取已回复 ID 缓存
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
    try:
        lang = detect(text)
        return 'zh' if lang.startswith('zh') else lang
    except:
        return 'en'

def generate_reply(comment_text):
    # 检测评论语言（作为后备方案）
    lang = detect_language(comment_text)
    lang_names = {
        'zh': 'Chinese', 'en': 'English', 'fr': 'French', 'de': 'German',
        'es': 'Spanish', 'ja': 'Japanese', 'ko': 'Korean', 'it': 'Italian',
        'pt': 'Portuguese', 'ru': 'Russian'
    }
    target_lang = lang_names.get(lang, 'English')

    url = "https://router.huggingface.co/v1/chat/completions"
    headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}
    # 更严格的 prompt，要求根据语言输出
    system_prompt = (
        f"You are a customer service assistant. The user's review is in {target_lang}. "
        f"Your reply MUST be written entirely in {target_lang}. Keep it short, friendly, and helpful (under 300 characters). "
        f"Do NOT use any other language. Example: if review is in French, reply in French; if in English, reply in English."
    )
    data = {
        "model": "moonshotai/Kimi-K2-Instruct-0905",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Please reply to this review: {comment_text}"}
        ],
        "temperature": 0.7,
        "max_tokens": 150
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"].strip()
        reply = ' '.join(reply.split())  # 清理空白
        if len(reply) > 350:
            reply = reply[:350] + "..."
        if not reply:
            raise ValueError("Empty reply")
        return reply
    except Exception as e:
        print(f"  AI 调用失败: {e}")
        # 降级为固定模板回复（使用正确语言）
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

def send_report(success, total, replied_ids_count):
    if WEBHOOK_URL:
        content = f"自动回复完成：成功 {success}/{total}\n累计已处理评论数：{replied_ids_count}"
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

# 筛选未回复 + 不在缓存中的评论
unreplied = []
for review in reviews:
    review_id = review.get("reviewId")
    if not review_id or review_id in replied_ids:
        continue
    # 检查 API 返回的 replies 字段（加强判断）
    replies = review.get("replies")
    has_reply = False
    if replies and isinstance(replies, list) and len(replies) > 0:
        # 如果存在至少一个回复文本，则认为已回复
        if any(r.get("text") for r in replies):
            has_reply = True
    if not has_reply:
        comment_text = review.get("comments", [{}])[0].get("userComment", {}).get("text", "")
        if comment_text:
            unreplied.append(review)
            print(f"待回复: {review_id} - {comment_text[:50]}...")
        else:
            # 无文本评论跳过
            replied_ids.add(review_id)  # 也加入缓存避免后续处理
    else:
        # 已有回复，加入缓存防止重复
        replied_ids.add(review_id)

print(f"找到 {len(unreplied)} 条未回复的新评论")

success = 0
new_replied_ids = []
for review in unreplied:
    rid = review["reviewId"]
    comment = review.get("comments", [{}])[0].get("userComment", {}).get("text", "")
    print(f"\n处理评论 {rid}: {comment[:80]}...")
    reply = generate_reply(comment)
    print(f"  生成的回复: {reply[:100]}...")
    if post_reply(rid, reply):
        success += 1
        new_replied_ids.append(rid)
    time.sleep(2)

# 更新缓存文件
if new_replied_ids:
    with open(CACHE_FILE, "a") as f:
        for rid in new_replied_ids:
            f.write(rid + "\n")
    replied_ids.update(new_replied_ids)
    print(f"已更新缓存，新增 {len(new_replied_ids)} 条记录")

send_report(success, len(unreplied), len(replied_ids))
print("执行完成")
