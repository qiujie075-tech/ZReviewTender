import os
import json
import time
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ========== 读取环境变量 ==========
SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
PACKAGE_NAME = os.environ.get('PACKAGE_NAME')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
HF_TOKEN = os.environ.get('HF_TOKEN')  # 保留但暂时不用，改用固定模板

print("=== 谷歌商店固定模板自动回复（安全版）===")

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL]):
    raise Exception("缺少必要的环境变量")

# ========== Google 认证 ==========
creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

# ========== 根据语言返回固定回复模板 ==========
def get_reply_by_language(text):
    """根据评论内容简单判断语言，返回对应语言的固定回复"""
    # 检测中文字符
    if any('\u4e00' <= ch <= '\u9fff' for ch in text):
        return "感谢您的反馈！我们会持续改进产品。"
    # 检测法文字符
    if any(ch in "éèêëàâäôöûüç" for ch in text):
        return "Merci pour votre retour ! Nous allons continuer à nous améliorer."
    # 检测德文字符
    if any(ch in "äöüß" for ch in text.lower()):
        return "Vielen Dank für Ihr Feedback! Wir werden uns weiter verbessern."
    # 默认英文
    return "Thank you for your feedback! We will continue to improve."

# ========== 获取未回复评论 ==========
def get_unreplied_reviews():
    try:
        response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=50).execute()
        reviews = response.get("reviews", [])
        print(f"API 返回评论总数: {len(reviews)}")
        
        unreplied = []
        for review in reviews:
            # 检查是否有回复
            replies = review.get("replies")
            has_reply = False
            if replies and isinstance(replies, list) and len(replies) > 0:
                # 检查是否有文本内容
                for r in replies:
                    if r.get("text"):
                        has_reply = True
                        break
            elif replies and isinstance(replies, dict) and replies.get("text"):
                has_reply = True
            
            if has_reply:
                continue
            
            # 获取评论文本
            comments = review.get("comments", [])
            if not comments:
                continue
            user_comment = comments[0].get("userComment", {})
            text = user_comment.get("text", "")
            if not text:
                continue
            
            unreplied.append({
                "id": review["reviewId"],
                "text": text
            })
        
        return unreplied
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
def send_report(success, total):
    if WEBHOOK_URL:
        data = {"msgtype": "text", "text": {"content": f"谷歌回复完成：成功 {success}/{total}"}}
        try:
            requests.post(WEBHOOK_URL, json=data, timeout=10)
        except:
            pass

# ========== 主程序 ==========
print("开始获取未回复评论...")
unreplied = get_unreplied_reviews()
print(f"找到 {len(unreplied)} 条未回复评论")

success = 0
for review in unreplied:
    rid = review["id"]
    text = review["text"]
    print(f"\n处理 {rid}: {text[:80]}...")
    reply = get_reply_by_language(text)
    print(f"  回复内容: {reply}")
    if post_reply(rid, reply):
        success += 1
    time.sleep(2)

send_report(success, len(unreplied))
print("执行完成")
