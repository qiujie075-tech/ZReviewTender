import os
import json
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timezone, timedelta

# ========== 从环境变量读取配置 ==========
SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
PACKAGE_NAME = os.environ.get('PACKAGE_NAME', 'com.linzi.sport')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

if not SERVICE_ACCOUNT_JSON:
    raise Exception("❌ 缺少环境变量 SERVICE_ACCOUNT_JSON")

if not WEBHOOK_URL:
    raise Exception("❌ 缺少环境变量 WEBHOOK_URL")

# 解析 JSON 密钥（可能是字符串或文件内容）
try:
    creds_info = json.loads(SERVICE_ACCOUNT_JSON)
except json.JSONDecodeError:
    raise Exception("❌ SERVICE_ACCOUNT_JSON 不是有效的 JSON 字符串")

# 认证 Google
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

def get_recent_reviews(hours=24):
    """获取最近 X 小时内的评论"""
    try:
        response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=50).execute()
        reviews = response.get("reviews", [])
        # 过滤出未回复且发布时间在最近 hours 小时内的评论
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)
        unreplied = []
        for review in reviews:
            # 检查是否有回复
            if "replies" in review and review["replies"]:
                continue
            # 获取评论发布时间
            comments = review.get("comments", [])
            if not comments:
                continue
            user_comment = comments[0].get("userComment", {})
            timestamp_millis = user_comment.get("lastModified", {}).get("seconds", 0)
            if timestamp_millis:
                comment_time = datetime.fromtimestamp(timestamp_millis, tz=timezone.utc)
                if comment_time >= cutoff:
                    unreplied.append(review)
        return unreplied
    except Exception as e:
        raise Exception(f"获取 Google Play 评论失败: {e}")

def send_to_feishu(reviews):
    """发送评论到飞书群"""
    if not reviews:
        print("没有未回复的新评论")
        return
    content_lines = []
    for review in reviews[:10]:  # 最多推送10条
        review_id = review.get("reviewId")
        comments = review.get("comments", [])
        if not comments:
            continue
        user_comment = comments[0].get("userComment", {})
        text = user_comment.get("text", "")
        star_rating = user_comment.get("starRating", 0)
        content_lines.append(f"⭐ {star_rating} 星\n💬 {text}\n🔗 [查看详情](https://play.google.com/store/apps/details?id={PACKAGE_NAME}&reviewId={review_id})")
    
    if not content_lines:
        return
    
    content = "\n\n---\n\n".join(content_lines)
    data = {
        "msg_type": "text",
        "content": {"text": f"📱 新评论提醒（最近24小时未回复）:\n\n{content}"}
    }
    try:
        resp = requests.post(WEBHOOK_URL, json=data, timeout=10)
        resp.raise_for_status()
        print("✅ 飞书推送成功")
    except Exception as e:
        raise Exception(f"飞书推送失败: {e}")

def main():
    print("开始获取最近24小时的未回复评论...")
    reviews = get_recent_reviews(hours=24)
    print(f"找到 {len(reviews)} 条未回复的新评论")
    send_to_feishu(reviews)
    print("执行完毕")

if __name__ == "__main__":
    main()
