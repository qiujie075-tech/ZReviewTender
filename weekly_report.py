import os
import json
import requests
import feedparser
from datetime import datetime, timedelta
from collections import Counter
from dateutil import parser
from google.oauth2 import service_account
from googleapiclient.discovery import build
import time
import hmac
import hashlib
import base64
import urllib.parse

# ========== 环境变量 ==========
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
PACKAGE_NAME = os.environ.get('PACKAGE_NAME')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
DINGTALK_SECRET = os.environ.get('DINGTALK_SECRET')

print("=== 每周双平台回复报告（详细版）===")

if not all([WEBHOOK_URL, SERVICE_ACCOUNT_JSON, PACKAGE_NAME]):
    raise Exception("缺少必要的环境变量")

# Google 认证
creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

def detect_sentiment(text):
    positive_words = ['good', 'great', 'awesome', 'love', 'perfect', 'best', 'nice', 'happy', 'helpful', 'easy', 'like', 'excellent', 'amazing', 'works well', 'stable']
    negative_words = ['bad', 'terrible', 'awful', 'hate', 'worst', 'useless', 'broken', 'crash', 'bug', 'slow', 'confusing', 'frustrating', 'disappointed', 'waste', 'stupid']
    text_lower = text.lower()
    pos = sum(1 for w in positive_words if w in text_lower)
    neg = sum(1 for w in negative_words if w in text_lower)
    if pos > neg:
        return 'positive'
    elif neg > pos:
        return 'negative'
    return 'neutral'

def extract_key_phrases(text):
    """提取关键问题短语"""
    phrases = []
    keywords = {
        'crash': ['crash', 'crashes', 'crashed', 'freeze', 'frozen'],
        'bug': ['bug', 'bugs', 'glitch', 'error'],
        'slow': ['slow', 'lag', 'delay', 'loading'],
        'confusing': ['confusing', 'hard to use', 'unclear', 'complicated', 'chaotic'],
        'translation': ['french', 'français', 'english', 'language', 'traduction', 'version'],
        'feature': ['feature', 'option', 'function', 'ability', 'missing'],
        'ads': ['ad', 'ads', 'advertisement', 'popup'],
        'sync': ['sync', 'save', 'lost', 'data'],
        'login': ['login', 'sign in', 'account', 'register'],
        'ui': ['interface', 'design', 'layout', 'navigation', 'menu']
    }
    for category, kws in keywords.items():
        for kw in kws:
            if kw in text.lower():
                phrases.append(category)
                break
    return list(set(phrases))

def get_google_reviews():
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
            if timestamp_seconds:
                comment_time = datetime.fromtimestamp(int(timestamp_seconds))
                if comment_time >= cutoff:
                    result.append({
                        "text": text,
                        "rating": star_rating,
                        "sentiment": detect_sentiment(text),
                        "phrases": extract_key_phrases(text)
                    })
            else:
                result.append({
                    "text": text,
                    "rating": star_rating,
                    "sentiment": detect_sentiment(text),
                    "phrases": extract_key_phrases(text)
                })
        return result
    except Exception as e:
        print(f"获取谷歌评论失败: {e}")
        return []

def get_apple_reviews():
    print("正在获取苹果评论...")
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
                try:
                    updated_time = parser.parse(updated)
                    if updated_time >= cutoff:
                        title = entry.get("title", "").replace("User Review: ", "")
                        content = entry.get("summary", "")
                        full_text = f"{title} {content}".strip()
                        if full_text:
                            result.append({
                                "text": full_text,
                                "rating": 3,
                                "sentiment": detect_sentiment(full_text),
                                "phrases": extract_key_phrases(full_text)
                            })
                except:
                    continue
        return result
    except Exception as e:
        print(f"获取苹果评论失败: {e}")
        return []

def generate_detailed_summary(google_reviews, apple_reviews):
    if not GROQ_API_KEY:
        return "无 AI 摘要"
    
    total = len(google_reviews) + len(apple_reviews)
    google_avg = sum(r['rating'] for r in google_reviews) / len(google_reviews) if google_reviews else 0
    apple_avg = sum(r['rating'] for r in apple_reviews) / len(apple_reviews) if apple_reviews else 0
    
    # 收集典型评论
    high_rating_comments = [r['text'][:150] for r in google_reviews if r['rating'] >= 4][:2]
    low_rating_comments = [r['text'][:150] for r in google_reviews if r['rating'] <= 2][:3]
    
    prompt = f"""分析本周应用评论，写一段详细的中文总结（4-5句话，包含具体建议）：

数据：
- 总评论数: {total}
- Google Play 平均评分: {google_avg:.1f} 星 ({len(google_reviews)} 条)
- App Store 平均评分: {apple_avg:.1f} 星 ({len(apple_reviews)} 条)

高评分评论示例：
{chr(10).join(['- ' + c for c in high_rating_comments]) if high_rating_comments else '无'}

低评分评论示例：
{chr(10).join(['- ' + c for c in low_rating_comments]) if low_rating_comments else '无'}

请总结：
1. 用户主要满意/不满意什么
2. 最 urgent 需要修复的问题
3. 产品改进建议"""
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
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
        return
    # 签名处理
    if DINGTALK_SECRET:
        timestamp = str(round(time.time() * 1000))
        sign = base64.b64encode(hmac.new(DINGTALK_SECRET.encode('utf-8'), f"{timestamp}\n{DINGTALK_SECRET}".encode('utf-8'), hashlib.sha256).digest()).decode('utf-8')
        webhook_url = f"{WEBHOOK_URL}&timestamp={timestamp}&sign={urllib.parse.quote(sign)}"
    else:
        webhook_url = WEBHOOK_URL
    data = {"msgtype": "markdown", "markdown": {"title": "📊 双平台周报", "text": report}}
    try:
        requests.post(webhook_url, json=data, timeout=10)
    except:
        pass

def main():
    print("="*50)
    google_reviews = get_google_reviews()
    apple_reviews = get_apple_reviews()
    
    if len(google_reviews) == 0 and len(apple_reviews) == 0:
        send_report_to_dingtalk({"msgtype": "text", "text": {"content": "本周没有收到任何评论数据。"}})
        return
    
    # 详细统计
    google_ratings = Counter([r['rating'] for r in google_reviews])
    apple_ratings = Counter([r['rating'] for r in apple_reviews])
    google_sentiment = Counter([r['sentiment'] for r in google_reviews])
    apple_sentiment = Counter([r['sentiment'] for r in apple_reviews])
    
    # 问题短语统计
    all_phrases = []
    for r in google_reviews + apple_reviews:
        all_phrases.extend(r['phrases'])
    phrase_counts = Counter(all_phrases)
    
    # 评分分布详情
    rating_dist = []
    for i in range(1, 6):
        google_cnt = google_ratings.get(i, 0)
        apple_cnt = apple_ratings.get(i, 0)
        if google_cnt > 0 or apple_cnt > 0:
            rating_dist.append(f"{i}⭐: G={google_cnt}, A={apple_cnt}")
    
    google_avg = sum(r['rating'] for r in google_reviews) / len(google_reviews) if google_reviews else 0
    apple_avg = sum(r['rating'] for r in apple_reviews) / len(apple_reviews) if apple_reviews else 0
    total = len(google_reviews) + len(apple_reviews)
    
    # 趋势判断
    trend = "📉 下降" if google_avg < 2.5 else "📈 良好" if google_avg >= 4 else "📊 平稳"
    
    summary = generate_detailed_summary(google_reviews, apple_reviews)
    
    # 构建详细报告
    report = f"""## 📊 双平台周报 ({datetime.now().strftime('%Y-%m-%d')})

> {trend} | 本周共 **{total}** 条评论

### 📈 数据概览

| 平台 | 评论数 | 平均评分 | 👍 正面 | 👎 负面 | 😐 中性 |
|------|--------|----------|---------|---------|---------|
| **Google Play** | {len(google_reviews)} | {google_avg:.1f} ⭐ | {google_sentiment.get('positive', 0)} | {google_sentiment.get('negative', 0)} | {google_sentiment.get('neutral', 0)} |
| **App Store** | {len(apple_reviews)} | {apple_avg:.1f} ⭐ | {apple_sentiment.get('positive', 0)} | {apple_sentiment.get('negative', 0)} | {apple_sentiment.get('neutral', 0)} |

### 📊 评分分布

| 星级 | Google Play | App Store |
|------|-------------|-----------|
"""
    for i in range(1, 6):
        report += f"| {i} ⭐ | {google_ratings.get(i, 0)} | {apple_ratings.get(i, 0)} |\n"
    
    report += f"""
### 🎯 本周热点问题

"""
    if phrase_counts:
        for phrase, count in phrase_counts.most_common(5):
            report += f"- **{phrase}**: 提及 {count} 次\n"
    else:
        report += "无明确问题关键词\n"
    
    report += f"""
### 💬 用户原话精选

"""
    # 低分评论
    low_reviews = [r for r in google_reviews if r['rating'] <= 2][:2]
    for r in low_reviews:
        report += f"> 😞 {r['text'][:120]}...\n\n"
    
    # 高分评论
    high_reviews = [r for r in google_reviews if r['rating'] >= 4][:1]
    for r in high_reviews:
        report += f"> 😊 {r['text'][:120]}...\n\n"
    
    report += f"""
### 🤖 AI 深度分析

{summary}

---
*报告生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    send_report_to_dingtalk(report)
    print("报告生成完成")

if __name__ == "__main__":
    main()
