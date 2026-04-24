import os
import sys
import json
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timezone, timedelta

def main():
    # 读取环境变量
    service_account_json = os.environ.get('SERVICE_ACCOUNT_JSON')
    package_name = os.environ.get('PACKAGE_NAME')
    webhook_url = os.environ.get('WEBHOOK_URL')
    
    print("=== 开始执行评论监控 ===")
    print(f"PACKAGE_NAME: {package_name}")
    print(f"WEBHOOK_URL: {webhook_url[:50]}..." if webhook_url else "WEBHOOK_URL: None")
    
    if not service_account_json:
        raise Exception("❌ 环境变量 SERVICE_ACCOUNT_JSON 未设置")
    if not package_name:
        raise Exception("❌ 环境变量 PACKAGE_NAME 未设置")
    if not webhook_url:
        raise Exception("❌ 环境变量 WEBHOOK_URL 未设置")
    
    # 解析 JSON 密钥
    try:
        creds_info = json.loads(service_account_json)
        print("✅ 解析 JSON 密钥成功")
    except Exception as e:
        raise Exception(f"❌ 解析 SERVICE_ACCOUNT_JSON 失败: {e}")
    
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
    
    # 获取评论
    try:
        response = service.reviews().list(packageName=package_name, maxResults=50).execute()
        reviews = response.get("reviews", [])
        print(f"✅ 获取到 {len(reviews)} 条评论")
    except Exception as e:
        raise Exception(f"❌ 获取评论失败: {e}")
    
    # 筛选未回复且24小时内的评论
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    unreplied = []
    for review in reviews:
        if "replies" in review and review["replies"]:
            continue
        comments = review.get("comments", [])
        if not comments:
            continue
        user_comment = comments[0].get("userComment", {})
        timestamp = user_comment.get("lastModified", {}).get("seconds", 0)
        if timestamp:
            comment_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            if comment_time >= cutoff:
                unreplied.append(review)
    print(f"✅ 筛选出 {len(unreplied)} 条未回复且24小时内的评论")
    
    # 推送飞书
    if not unreplied:
        print("没有新评论需要推送")
        return
    
    content_lines = []
    for review in unreplied[:10]:
        review_id = review.get("reviewId")
        comments = review.get("comments", [])
        if not comments:
            continue
        user_comment = comments[0].get("userComment", {})
        text = user_comment.get("text", "")
        star_rating = user_comment.get("starRating", 0)
        content_lines.append(f"⭐ {star_rating} 星\n💬 {text}\n🔗 [查看详情](https://play.google.com/store/apps/details?id={package_name}&reviewId={review_id})")
    
    content = "\n\n---\n\n".join(content_lines)
    payload = {
        "msg_type": "text",
        "content": {"text": f"📱 新评论提醒（最近24小时未回复）:\n\n{content}"}
    }
    
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        print("✅ 飞书推送成功")
    except Exception as e:
        raise Exception(f"❌ 飞书推送失败: {e}")

if __name__ == "__main__":
    try:
        main()
        print("=== 执行完毕 ===")
        sys.exit(0)
    except Exception as e:
        print(f"=== 执行失败: {e} ===")
        sys.exit(1)
