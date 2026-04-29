import os
import json
import requests
from datetime import datetime, timedelta
from collections import Counter
import re

# ========== 环境变量 ==========
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
PACKAGE_NAME = os.environ.get('PACKAGE_NAME')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')  # 用于问题归因分析

print("=== 每周双平台回复报告 ===")

if not all([WEBHOOK_URL, SERVICE_ACCOUNT_JSON, PACKAGE_NAME, GROQ_API_KEY]):
    raise Exception("缺少必要的环境变量")

# Google 认证
creds_info = json.loads(SERVICE_ACCOUNT_JSON)
from google.oauth2 import service_account
from googleapiclient.discovery import build
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

def detect_sentiment(text):
    """简单情感判断，用于归因"""
    positive_words = ['good', 'great', 'awesome', 'love', 'perfect', 'best', 'nice', 'happy', 'helpful', 'easy', 'like']
    negative_words = ['bad', 'terrible', 'awful', 'hate', 'worst', 'useless', 'broken', 'crash', 'bug', 'slow', 'confusing', 'frustrating']
    text_lower = text.lower()
    pos = sum(1 for w in positive_words if w in text_lower)
    neg = sum(1 for w in negative_words if w in text_lower)
    if pos > neg:
        return 'positive'
    elif neg > pos:
        return 'negative'
    return 'neutral'

def get_google_reviews():
    """获取谷歌最近7天评论"""
    try:
        response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=100).execute()
        reviews = response.get("reviews", [])
        cutoff = datetime.now() - timedelta(days=7)
        result = []
        for review in reviews:
            comments = review.get("comments", [])
            if not comments:
                continue
            user_comment = comments[0].get("userComment", {})
            timestamp_seconds = user_comment.get("lastModified", {}).get("seconds", 0)
            if timestamp_seconds:
                comment_time = datetime.fromtimestamp(timestamp_seconds)
                if comment_time >= cutoff:
                    text = user_comment.get("text", "")
                    star_rating = user_comment.get("starRating", 0)
                    if text:
                        result.append({
                            "text": text,
                            "rating": star_rating,
                            "sentiment": detect_sentiment(text)
                        })
        return result
    except Exception as e:
        print(f"获取谷歌评论失败: {e}")
        return []

def get_apple_reviews():
    """获取苹果最近7天评论（通过 RSS 源）"""
    import feedparser
    APP_ID = "1598065258"
    COUNTRY = "cn"
    url = f"https://itunes.apple.com/{COUNTRY}/rss/customerreviews/id={APP_ID}/sortby=mostrecent/xml?limit=50"
    try:
        feed = feedparser.parse(url)
        cutoff = datetime.now() - timedelta(days=7)
        result = []
        for entry in feed.entries:
            updated = entry.get("updated")
            if updated:
                from dateutil import parser
                updated_time = parser.parse(updated)
                if updated_time >= cutoff:
                    title = entry.get("title", "").replace("User Review: ", "")
                    content = entry.get("summary", "")
                    rating = 3  # RSS 不提供评分，默认3
                    full_text = f"{title}. {content}"
                    result.append({
                        "text": full_text,
                        "rating": rating,
                        "sentiment": detect_sentiment(full_text)
                    })
        return result
    except Exception as e:
        print(f"获取苹果评论失败: {e}")
        return []

def analyze_issues(reviews):
    """分析常见问题关键词（简单实现）"""
    issue_keywords = {
        'bug/crash': ['bug', 'crash', 'freeze', 'not working', 'error', 'broken', 'glitch'],
        'UI/UX': ['confusing', 'hard to use', 'navigation', 'design', 'layout', 'interface', 'cluttered'],
        'feature request': ['add', 'want', 'need', 'missing', 'feature', 'option', 'support'],
        'performance': ['slow', 'lag', 'delay', 'loading', 'speed', 'performance'],
        'login/account': ['login', 'sign in', 'account', 'password', 'register'],
        'data sync': ['sync', 'lost', 'save', 'data', 'backup', 'progress'],
        'ads': ['ad', 'advertisement', 'popup', 'interrupt', 'annoying'],
        'device compatibility': ['tablet', 'phone', 'device', 'android', 'ios', 'compatible']
    }
    issue_counts = {k: 0 for k in issue_keywords}
    for review in reviews:
        text_lower = review['text'].lower()
        for issue, keywords in issue_keywords.items():
            for kw in keywords:
                if kw in text_lower:
                    issue_counts[issue] += 1
                    break
    return issue_counts

def generate_ai_summary(google_reviews, apple_reviews):
    """使用 AI 生成总结摘要"""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    total = len(google_reviews) + len(apple_reviews)
    google_avg = sum(r['rating'] for r in google_reviews) / len(google_reviews) if google_reviews else 0
    apple_avg = sum(r['rating'] for r in apple_reviews) / len(apple_reviews) if apple_reviews else 0
    
    # 收集用户原话样本
    sample_comments = []
    for r in (google_reviews + apple_reviews)[:5]:
        if r['text']:
            sample_comments.append(f"- {r['text'][:100]}...")
    samples_text = "\n".join(sample_comments) if sample_comments else "无"
    
    prompt = f"""Analyze this week's app reviews and write a short executive summary (2-3 sentences in Chinese).

Stats:
- Total reviews: {total}
- Google Play avg rating: {google_avg:.1f} stars ({len(google_reviews)} reviews)
- App Store avg rating: {apple_avg:.1f} stars ({len(apple_reviews)} reviews)

Sample user comments:
{samples_text}

Write a warm, professional summary highlighting key trends and what users are saying. Keep it concise."""
    
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 200,
        "temperature": 0.7
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=20)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except:
        pass
    return f"本周共收到 {total} 条评论，谷歌平均评分 {google_avg:.1f} 星，苹果平均评分 {apple_avg:.1f} 星。"

def send_report_to_dingtalk(report):
    """发送 Markdown 格式报告到钉钉"""
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": "📊 双平台周报",
            "text": report
        }
    }
    try:
        resp = requests.post(WEBHOOK_URL, json=data, timeout=10)
        if resp.status_code == 200:
            print("✅ 报告推送成功")
        else:
            print(f"❌ 推送失败: {resp.status_code}")
    except Exception as e:
        print(f"❌ 推送异常: {e}")

def main():
    print("正在获取谷歌评论...")
    google_reviews = get_google_reviews()
    print(f"谷歌本周评论: {len(google_reviews)} 条")
    
    print("正在获取苹果评论...")
    apple_reviews = get_apple_reviews()
    print(f"苹果本周评论: {len(apple_reviews)} 条")
    
    # 统计评分分布
    google_ratings = Counter([r['rating'] for r in google_reviews])
    apple_ratings = Counter([r['rating'] for r in apple_reviews])
    google_sentiment = Counter([r['sentiment'] for r in google_reviews])
    apple_sentiment = Counter([r['sentiment'] for r in apple_reviews])
    
    # 问题归因分析（仅谷歌，因为苹果评论缺少结构化数据）
    issue_analysis = analyze_issues(google_reviews)
    
    # AI 总结
    summary = generate_ai_summary(google_reviews, apple_reviews)
    
    # 构建报告
    report = f"""## 📊 双平台周报 ({datetime.now().strftime('%Y-%m-%d')})

---

### 📈 数据概览

| 平台 | 评论数 | 平均评分 | 👍 正面 | 👎 负面 | 😐 中性 |
|------|--------|----------|---------|---------|---------|
| **Google Play** | {len(google_reviews)} | {sum(r['rating'] for r in google_reviews)/len(google_reviews) if google_reviews else 0:.1f} ⭐ | {google_sentiment.get('positive', 0)} | {google_sentiment.get('negative', 0)} | {google_sentiment.get('neutral', 0)} |
| **App Store** | {len(apple_reviews)} | {sum(r['rating'] for r in apple_reviews)/len(apple_reviews) if apple_reviews else 0:.1f} ⭐ | {apple_sentiment.get('positive', 0)} | {apple_sentiment.get('negative', 0)} | {apple_sentiment.get('neutral', 0)} |

---

### 🎯 问题归因（Google Play）

"""
    
    if any(issue_analysis.values()):
        for issue, count in sorted(issue_analysis.items(), key=lambda x: x[1], reverse=True):
            if count > 0:
                bar = "█" * min(count, 10)
                report += f"\n- **{issue}**: {count} 条 {bar}"
    else:
        report += "\n暂无明确问题归类\n"
    
    report += f"""

### 🤖 AI 总结

{summary}

---

### 💬 用户原话摘录

"""
    for r in (google_reviews + apple_reviews)[:3]:
        if r['text']:
            report += f"> {r['text'][:120]}...\n\n"
    
    report += f"\n---\n*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
    
    send_report_to_dingtalk(report)
    print("报告生成完成")

if __name__ == "__main__":
    main()
