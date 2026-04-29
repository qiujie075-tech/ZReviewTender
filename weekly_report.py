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

print("=== 每周双平台回复报告（归类版）===")

# ========== 问题分类关键词库 ==========
ISSUE_CATEGORIES = {
    "稳定性/崩溃": {
        "keywords": ["crash", "崩溃", "闪退", "卡死", "freeze", "闪一下", "打不开", "闪屏", "报错", "error", "bug", "死机"],
        "emoji": "💥"
    },
    "性能/卡顿": {
        "keywords": ["慢", "卡", "lag", "slow", "延迟", "卡顿", "响应慢", "loading", "卡死", "不流畅"],
        "emoji": "🐌"
    },
    "界面/易用性": {
        "keywords": ["界面", "ui", "设计", "难看", "混乱", "confusing", "难用", "找不", "导航", "navigation", "布局", "layout", "复杂", "homepage"],
        "emoji": "🎨"
    },
    "功能缺失/建议": {
        "keywords": ["建议", "希望", "需要", "缺少", "增加", "想要", "feature", "add", "want", "need", "request", "期待", "如果", "能不能"],
        "emoji": "💡"
    },
    "翻译/语言": {
        "keywords": ["法语", "法语版", "français", "语言", "language", "中文", "翻译", "traduction", "英文", "多语言"],
        "emoji": "🌐"
    },
    "登录/账号": {
        "keywords": ["登录", "登陆", "账号", "密码", "注册", "login", "sign in", "account", "忘记密码"],
        "emoji": "🔐"
    },
    "数据/同步": {
        "keywords": ["数据", "同步", "sync", "丢失", "记录", "保存", "丢失了", "没了", "运动记录", "history"],
        "emoji": "💾"
    },
    "广告": {
        "keywords": ["广告", "ad", "推广", "广", "烦人", "popup", "弹窗"],
        "emoji": "📢"
    },
    "设备兼容性": {
        "keywords": ["手机", "机型", "设备", "tablet", "平板", "适配", "device", "兼容", "android", "ios"],
        "emoji": "📱"
    },
    "连接/蓝牙": {
        "keywords": ["蓝牙", "蓝牙连接", "连接不上", "断连", "配对", "bluetooth", "connect", "disconnect", "无法连接"],
        "emoji": "🔗"
    }
}

def classify_review(text):
    """对单条评论进行分类，返回类别名称和置信度"""
    text_lower = text.lower()
    scores = {}
    for category, info in ISSUE_CATEGORIES.items():
        score = 0
        for kw in info["keywords"]:
            if kw.lower() in text_lower:
                score += 1
        if score > 0:
            scores[category] = score
    if scores:
        # 返回得分最高的类别
        best = max(scores, key=scores.get)
        return best, scores[best]
    return "其他", 0

def detect_sentiment(text):
    positive_words = ['good', 'great', 'awesome', 'love', 'perfect', 'best', 'nice', 'happy', 'helpful', 'easy', 'like', 'excellent', 'amazing', 'works well', 'stable', '不错', '很好', '喜欢']
    negative_words = ['bad', 'terrible', 'awful', 'hate', 'worst', 'useless', 'broken', 'crash', 'bug', 'slow', 'confusing', 'frustrating', 'disappointed', 'waste', '差', '烂', '垃圾', '垃圾', '不好', '失望']
    text_lower = text.lower()
    pos = sum(1 for w in positive_words if w in text_lower)
    neg = sum(1 for w in negative_words if w in text_lower)
    if pos > neg:
        return 'positive'
    elif neg > pos:
        return 'negative'
    return 'neutral'

# Google 认证
creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

def get_google_reviews():
    print("正在获取谷歌评论...")
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
            text = user_comment.get("text", "")
            star_rating = user_comment.get("starRating", 0)
            if not text:
                continue
            if timestamp_seconds:
                comment_time = datetime.fromtimestamp(int(timestamp_seconds))
                if comment_time >= cutoff:
                    category, _ = classify_review(text)
                    result.append({
                        "text": text,
                        "rating": star_rating,
                        "sentiment": detect_sentiment(text),
                        "category": category
                    })
            else:
                category, _ = classify_review(text)
                result.append({
                    "text": text,
                    "rating": star_rating,
                    "sentiment": detect_sentiment(text),
                    "category": category
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
                            category, _ = classify_review(full_text)
                            result.append({
                                "text": full_text,
                                "rating": 3,
                                "sentiment": detect_sentiment(full_text),
                                "category": category
                            })
                except:
                    continue
        return result
    except Exception as e:
        print(f"获取苹果评论失败: {e}")
        return []

def generate_ai_summary(google_reviews, apple_reviews, category_stats):
    if not GROQ_API_KEY:
        return "无 AI 摘要"
    
    total = len(google_reviews) + len(apple_reviews)
    google_avg = sum(r['rating'] for r in google_reviews) / len(google_reviews) if google_reviews else 0
    apple_avg = sum(r['rating'] for r in apple_reviews) / len(apple_reviews) if apple_reviews else 0
    
    # 提取主要问题类别
    top_issues = sorted(category_stats.items(), key=lambda x: x[1], reverse=True)[:3]
    issues_text = ", ".join([f"{cat}({cnt}条)" for cat, cnt in top_issues]) if top_issues else "无明显问题"
    
    prompt = f"""根据以下数据写一段简短的中文总结（3-4句话）：

总评论数: {total}
Google Play平均评分: {google_avg:.1f}星
App Store平均评分: {apple_avg:.1f}星
主要问题类别: {issues_text}

请总结本周用户反馈的核心问题和改进方向。"""
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 250,
        "temperature": 0.7
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=20)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except:
        pass
    return f"本周共 {total} 条评论，谷歌评分 {google_avg:.1f} 星，主要问题：{issues_text}。"

def send_report_to_dingtalk(report):
    if not WEBHOOK_URL:
        return
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
    
    # 统计
    google_ratings = Counter([r['rating'] for r in google_reviews])
    apple_ratings = Counter([r['rating'] for r in apple_reviews])
    google_sentiment = Counter([r['sentiment'] for r in google_reviews])
    apple_sentiment = Counter([r['sentiment'] for r in apple_reviews])
    
    # 问题分类统计（重点）
    category_stats = Counter([r['category'] for r in google_reviews + apple_reviews])
    
    google_avg = sum(r['rating'] for r in google_reviews) / len(google_reviews) if google_reviews else 0
    apple_avg = sum(r['rating'] for r in apple_reviews) / len(apple_reviews) if apple_reviews else 0
    total = len(google_reviews) + len(apple_reviews)
    
    trend = "📉 下降" if google_avg < 2.5 else "📈 良好" if google_avg >= 4 else "📊 平稳"
    summary = generate_ai_summary(google_reviews, apple_reviews, category_stats)
    
    # 获取分类对应的 emoji
    category_emoji = {cat: ISSUE_CATEGORIES.get(cat, {}).get("emoji", "📌") for cat in category_stats.keys()}
    category_emoji["其他"] = "📌"
    
    # 构建报告
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
    
    # 问题归类（按数量排序）
    report += f"\n### 🎯 用户问题归类\n\n"
    if category_stats:
        sorted_categories = sorted(category_stats.items(), key=lambda x: x[1], reverse=True)
        for i, (cat, cnt) in enumerate(sorted_categories, 1):
            emoji = category_emoji.get(cat, "📌")
            # 计算百分比
            percent = round(cnt / total * 100) if total > 0 else 0
            bar = "█" * min(percent // 5, 10)
            report += f"{i}. **{emoji} {cat}**: {cnt} 条 ({percent}%) {bar}\n"
    else:
        report += "暂无明确问题分类\n"
    
    # 用户原话精选（按分类展示）
    report += f"\n### 💬 典型反馈\n\n"
    
    # 按问题类别收集典型评论
    shown_categories = set()
    for review in google_reviews + apple_reviews:
        cat = review['category']
        if cat in shown_categories:
            continue
        if review['rating'] <= 2 and review['category'] == cat:
            report += f"**{cat}** 😞: _{review['text'][:100]}..._\n\n"
            shown_categories.add(cat)
        if len(shown_categories) >= 5:
            break
    
    report += f"""
### 🤖 AI 分析总结

{summary}

---
*报告生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    send_report_to_dingtalk(report)
    print("报告生成完成")

if __name__ == "__main__":
    main()
