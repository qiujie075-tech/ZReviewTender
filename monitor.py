import os
import json
import time
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
PACKAGE_NAME = os.environ.get('PACKAGE_NAME')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
CACHE_FILE = "replied_ids.txt"

print("=== 谷歌商店自动回复（基于本地记录文件）===")

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL]):
    raise Exception("缺少必要的环境变量")

# ========== 读取已回复记录 ==========
replied_ids = set()
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f:
        replied_ids = set(line.strip() for line in f if line.strip())
    print(f"已加载 {len(replied_ids)} 条历史回复记录")

# ========== Google 认证 ==========
creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

# ========== 语言检测与回复模板 ==========
def detect_language(text):
    if any('\u4e00' <= ch <= '\u9fff' for ch in text):
        return 'zh'
    if any(ch in "éèêëàâäôöûüç" for ch in text.lower()):
        return 'fr'
    if any(ch in "äöüß" for ch in text.lower()):
        return 'de'
    return 'en'

def get_reply(text):
    lang = detect_language(text)
    replies = {
        'zh': "感谢您的反馈！我们会持续改进产品。",
        'fr': "Merci pour votre retour ! Nous allons continuer à nous améliorer.",
        'de': "Vielen Dank für Ihr Feedback! Wir werden uns weiter verbessern.",
        'en': "Thank you for your feedback! We will continue to improve."
    }
    return replies.get(lang, replies['en'])

# ========== 获取所有评论（不过滤官方 replies） ==========
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
            # 获取评论文本
            comments = review.get("comments", [])
            if not comments:
                continue
            user_comment = comments[0].get("userComment", {})
            text = user_comment.get("text", "")
            if not text:
                continue
            result.append({
                "id": review_id,
                "text": text
            })
        return result
    except Exception as e:
        print(f"获取评论失败: {e}")
        return []

# ========== 发布回复 ==========
def post_reply(review_id, reply_text):
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

# ========== 发送通知 ==========
def send_report(success, total, skipped):
    if WEBHOOK_URL:
        data = {"msgtype": "text", "text": {"content": f"谷歌回复完成：成功 {success}/{total}，跳过 {skipped} 条已回复"}}
        try:
            requests.post(WEBHOOK_URL, json=data, timeout=10)
        except:
            pass

# ========== 主程序 ==========
print("获取所有评论...")
all_reviews = get_all_reviews()
print(f"共获取 {len(all_reviews)} 条评论")

# 筛选未回复的（基于本地缓存，不依赖官方 replies）
to_reply = []
for review in all_reviews:
    if review["id"] in replied_ids:
        continue
    to_reply.append(review)
print(f"需要回复: {len(to_reply)} 条")

success = 0
new_ids = []
for review in to_reply:
    rid = review["id"]
    text = review["text"]
    print(f"\n处理 {rid}: {text[:80]}...")
    reply = get_reply(text)
    print(f"  回复: {reply}")
    if post_reply(rid, reply):
        success += 1
        new_ids.append(rid)
    time.sleep(2)

# 更新缓存文件
if new_ids:
    with open(CACHE_FILE, "a") as f:
        for rid in new_ids:
            f.write(rid + "\n")
    replied_ids.update(new_ids)
    print(f"已更新缓存，新增 {len(new_ids)} 条记录")

send_report(success, len(to_reply), len(all_reviews) - len(to_reply))
print("执行完成")
