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

print("=== 开始执行评论监控 ===")
print(f"PACKAGE_NAME: {PACKAGE_NAME}")
print(f"WEBHOOK_URL: {WEBHOOK_URL[:50] if WEBHOOK_URL else 'None'}...")

if not SERVICE_ACCOUNT_JSON:
    raise Exception("❌ 缺少环境变量 SERVICE_ACCOUNT_JSON")

if not WEBHOOK_URL:
    raise Exception("❌ 缺少环境变量 WEBHOOK_URL")

# 解析 JSON 密钥
try:
    creds_info = json.loads(SERVICE_ACCOUNT_JSON)
    print("✅ 解析 JSON 密钥成功")
except json.JSONDecodeError as e:
    raise Exception(f"❌ SERVICE_ACCOUNT_JSON 不是有效的 JSON: {e}")

# 认证 Google
try:
    credentials = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/androidpublisher"]
    )
    service = build("androidpublisher", "v3", credentials=credentials)
    print("✅ Google 认证成功")
except Exception as e:
    raise Exception(f"❌ Google 认证失败: {e}")

def get_recent_reviews(hours=24):
    """获取最近 X 小时内未回复的评论"""
    try:
        response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=50).execute()
        reviews = response.get("reviews", [])
        print(f"✅ 获取到 {len(reviews)} 条评论")
        
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)
        unreplied = []
        
        for review in reviews:
            # 检查是否已有回复
            if "replies" in review and review["replies"]:
                continue
            
            # 获取评论内容
            comments = review.get("comments", [])
            if not comments:
                continue
            user_comment = comments[0].get("userComment", {})
            
            # 获取时间戳（可能是字符串或整数）
            timestamp_data = user_comment.get("lastModified", {})
            if isinstance(timestamp_data, dict):
                timestamp_seconds = timestamp_data.get("seconds")
            else:
                # 兼容其他格式
                timestamp_seconds = timestamp_data
            
            if timestamp_seconds is None:
                continue
            
            # 确保转换为整数
            try:
                timestamp_seconds = int(timestamp_seconds)
            except (TypeError, ValueError):
                print(f"⚠️ 时间戳格式异常: {timestamp_seconds}")
                continue
            
            comment_time = datetime.fromtimestamp(timestamp_seconds, tz=timezone.utc)
            if comment_time >= cutoff:
                unreplied.append(review)
        
        return unreplied
    except Exception as e:
        raise Exception(f"获取 Google Play 评论失败: {e}")

def send_to_dingtalk(reviews):
    """发送评论到钉钉群"""
    if not reviews:
        print("没有未回复的新评论")
        return
    
    content_lines = []
    for review in reviews[:10]:
        review_id = review.get("reviewId")
        comments = review.get("comments", [])
        if not comments:
            continue
        user_comment = comments[0].get("userComment", {})
        text = user_comment.get("text", "")
        star_rating = user_comment.get("starRating", 0)
        # 处理可能的字符串星级
        try:
            star_rating = int(star_rating)
        except (TypeError, ValueError):
            star_rating = 0
        content_lines.append(f"⭐ {star_rating} 星\n💬 {text}\n🔗 [跳转](https://play.google.com/store/apps/details?id={PACKAGE_NAME}&reviewId={review_id})")
    
    if not content_lines:
        return
    
    content = "\n\n---\n\n".join(content_lines)
    
    # 钉钉消息格式
    data = {
        "msgtype": "text",
        "text": {
            "content": f"📱 新评论提醒（最近24小时未回复）:\n\n{content}"
        }
    }
    
    try:
        resp = requests.post(WEBHOOK_URL, json=data, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("errcode") == 0:
            print("✅ 钉钉推送成功")
        else:
            print(f"⚠️ 钉钉推送返回错误: {result}")
    except Exception as e:
        raise Exception(f"钉钉推送失败: {e}")

def main():
    print("开始获取最近24小时的未回复评论...")
    reviews = get_recent_reviews(hours=24)
    print(f"找到 {len(reviews)} 条未回复的新评论")
    send_to_dingtalk(reviews)
    print("=== 执行完毕 ===")

if __name__ == "__main__":
    main()
