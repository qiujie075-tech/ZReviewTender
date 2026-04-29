import os
import json
import requests
import feedparser
from datetime import datetime, timedelta
from collections import Counter
from dateutil import parser
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ========== 环境变量 ==========
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
PACKAGE_NAME = os.environ.get('PACKAGE_NAME')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

print("=== 每周双平台回复报告 ===")
print(f"WEBHOOK_URL 存在: {bool(WEBHOOK_URL)}")
print(f"PACKAGE_NAME: {PACKAGE_NAME}")

if not all([WEBHOOK_URL, SERVICE_ACCOUNT_JSON, PACKAGE_NAME]):
    raise Exception("缺少必要的环境变量")

# ========== Google 认证 ==========
creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

def detect_sentiment(text):
    positive_words = ['good', 'great', 'awesome', 'love', 'perfect', 'best', 'nice', 'happy', 'helpful', 'easy', 'like', 'excellent', 'amazing']
    negative_words = ['bad', 'terrible', 'awful', 'hate', 'worst', 'useless', 'broken', 'crash', 'bug', 'slow', 'confusing', 'frustrating', 'disappointed']
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
    print("正在获取谷歌评论...")
    try:
        response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=100).execute()
        reviews = response.get("reviews", [])
        print(f"谷歌 API 返回评论总数: {len(reviews)}")
        
        cutoff = datetime.now() - timedelta(days=7)
        result = []
        for review in reviews:
            comments = review.get("comments", [])
            if not comments:
                continue
            user_comment = comments[0].get("userComment", {})
            timestamp_seconds = user_comment.get("lastModified", {}).get("seconds", 0)
            text = user_comment.get("text", "")
            star_rating = user_comment.get("starRating", 0)
            
            if not text:
                continue
            
            # 时间过滤
            if timestamp_seconds:
                comment_time = datetime.fromtimestamp(int(timestamp_seconds))
                if comment_time >= cutoff:
                    result.append({
                        "text": text,
                        "rating": star_rating,
                        "sentiment": detect_sentiment(text)
                    })
                    print(f"  ✓ 收录: {text[:50]}... (评分: {star_rating})")
            else:
                # 没有时间戳也收录（兼容旧数据）
                result.append({
                    "text": text,
                    "rating": star_rating,
                    "sentiment": detect_sentiment(text)
                })
                print(f"  ✓ 收录(无时间戳): {text[:50]}...")
        
        print(f"谷歌本周评论: {len(result)} 条")
        return result
    except Exception as e:
        print(f"❌ 获取谷歌评论失败: {e}")
        return []

def get_apple_reviews():
    """获取苹果最近7天评论"""
    print("正在获取苹果评论...")
    APP_ID = "1598065258"
    COUNTRY = "cn"
    url = f"https://itunes.apple.com/{COUNTRY}/rss/customerreviews/id={APP_ID}/sortby=mostrecent/xml?limit=50"
    print(f"苹果 RSS URL: {url}")
    
    try:
        feed = feedparser.parse(url)
        print(f"苹果 RSS 解析成功，共 {len(feed.entries)} 条条目")
        
        cutoff = datetime.now() - timedelta(days=7)
        result = []
        
        for entry in feed.entries:
            updated = entry.get("updated")
            if updated:
                try:
                    updated_time = parser.parse(updated)
                    if updated_time >= cutoff:
                        title = entry.get("title", "").replace("User Review: ", "")
                        content = entry.get("summary", "")
                        full_text = f"{title} {content}".strip()
                        if full_text:
                            result.append({
                                "text": full_text,
                                "rating": 3,  # RSS 不提供评分，默认3
                                "sentiment": detect_sentiment(full_text)
                            })
                            print(f"  ✓ 收录: {full_text[:50]}...")
                except Exception as e:
                    print(f"  时间解析失败: {e}")
                    continue
        
        print(f"苹果本周评论: {len(result)} 条")
        return result
    except Exception as e:
        print(f"❌ 获取苹果评论失败: {e}")
        return []

def analyze_issues(reviews):
    issue_keywords = {
        'bug/crash': ['bug', 'crash', 'freeze', 'not working', 'error', 'broken', 'glitch'],
        'UI/UX': ['confusing', 'hard to use', 'navigation', 'design', 'layout', 'interface', 'cluttered'],
        'feature request': ['add', 'want', 'need', 'missing', 'feature', 'option', 'support'],
        'performance': ['slow', 'lag', 'delay', 'loading', 'speed', 'performance'],
        'login/account': ['login', 'sign in', 'account', 'password', 'register'],
        'data sync': ['sync', 'lost', 'save', 'data', 'backup', 'progress'],
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
    if not GROQ_API_KEY:
        return "无 AI 摘要（缺少 API Key）"
    
    total = len(google_reviews) + len(apple_reviews)
    google_avg = sum(r['rating'] for r in google_reviews) / len(google_reviews) if google_reviews else 0
    apple_avg = sum(r['rating'] for r in apple_reviews) / len(apple_reviews) if apple_reviews else 0
    
    sample_comments = []
    for r in (google_reviews + apple_reviews)[:3]:
        if r['text']:
            sample_comments.append(f"- {r['text'][:100]}...")
    samples_text = "\n".join(sample_comments) if sample_comments else "无"
    
    prompt = f"""分析本周应用评论，写一段简短的中文总结（2-3句话）：

数据：
- 总评论数: {total}
- Google Play 平均评分: {google_avg:.1f} 星 ({len(google_reviews)} 条)
- App Store 平均评分: {apple_avg:.1f} 星 ({len(apple_reviews)} 条)

用户评论示例：
{samples_text}

请写一段专业、简洁的总结，指出主要趋势或问题。"""
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
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
    except Exception as e:
        print(f"AI 总结失败: {e}")
    
    return f"本周共收到 {total} 条评论，谷歌平均评分 {google_avg:.1f} 星，苹果平均评分 {apple_avg:.1f} 星。"

def send_report_to_dingtalk(report):
    if not WEBHOOK_URL:
        print("❌ 无 Webhook URL")
        return
    data = {"msgtype": "markdown", "markdown": {"title": "📊 双平台周报", "text": report}}
    try:
        resp = requests.post(WEBHOOK_URL, json=data, timeout=10)
        print(f"钉钉响应: {resp.status_code} - {resp.text}")
        if resp.status_code == 200:
            print("✅ 报告推送成功")
        else:
            print(f"❌ 推送失败: {resp.text}")
    except Exception as e:
        print(f"❌ 推送异常: {e}")

def main():
    print("\n" + "="*50)
    
    # 获取谷歌评论
    google_reviews = get_google_reviews()
    print(f"谷歌本周评论: {len(google_reviews)} 条")
    
    # 获取苹果评论
    apple_reviews = get_apple_reviews()
    print(f"苹果本周评论: {len(apple_reviews)} 条")
    
    if len(google_reviews) == 0 and len(apple_reviews) == 0:
        print("⚠️ 没有获取到任何评论数据，推送提示消息")
        no_data_msg = "本周没有收到任何评论数据。\n\n请检查：\n1. 谷歌服务账号权限\n2. 苹果 RSS 源是否可访问\n3. 应用是否有新评论"
        send_report_to_dingtalk({"msgtype": "text", "text": {"content": no_data_msg}})
        return
    
    # 统计
    google_ratings = Counter([r['rating'] for r in google_reviews])
    apple_ratings = Counter([r['rating'] for r in apple_reviews])
    google_sentiment = Counter([r['sentiment'] for r in google_reviews])
    apple_sentiment = Counter([r['sentiment'] for r in apple_reviews])
    issue_analysis = analyze_issues(google_reviews)
    summary = generate_ai_summary(google_reviews, apple_reviews)
    
    # 构建报告
    google_avg = sum(r['rating'] for r in google_reviews) / len(google_reviews) if google_reviews else 0
    apple_avg = sum(r['rating'] for r in apple_reviews) / len(apple_reviews) if apple_reviews else 0
    
    report = f"""## 📊 双平台周报 ({datetime.now().strftime('%Y-%m-%d')})

---

### 📈 数据概览

| 平台 | 评论数 | 平均评分 | 👍 正面 | 👎 负面 | 😐 中性 |
|------|--------|----------|---------|---------|---------|
| **Google Play** | {len(google_reviews)} | {google_avg:.1f} ⭐ | {google_sentiment.get('positive', 0)} | {google_sentiment.get('negative', 0)} | {google_sentiment.get('neutral', 0)} |
| **App Store** | {len(apple_reviews)} | {apple_avg:.1f} ⭐ | {apple_sentiment.get('positive', 0)} | {apple_sentiment.get('negative', 0)} | {apple_sentiment.get('neutral', 0)} |

---

### 🎯 问题归因（Google Play）

"""
    if any(issue_analysis.values()):
        for issue, count in sorted(issue_analysis.items(), key=lambda x: x[1], reverse=True):
            if count > 0:
                bar = "█" * min(count, 10)
                report += f"\n- **{issue}**: {count} 条 {bar}"
    else:
        report += "\n暂无明确问题归类（评论较少或无关键词匹配）\n"

    report += f"""

### 🤖 AI 总结

{summary}

---

*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"""

    send_report_to_dingtalk(report)
    print("报告生成完成")

if __name__ == "__main__":
    main()
