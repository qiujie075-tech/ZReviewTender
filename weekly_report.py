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

print("=== 每周双平台回复报告（超详细归类版）===")

# ========== 超详细问题分类关键词库 ==========
ISSUE_CATEGORIES = {
    # 技术问题
    "崩溃/闪退": {
        "keywords": ["crash", "crashes", "crashed", "闪退", "崩溃", "闪一下", "自动关闭", "退出", "force close", "报错", "error", "fatal", "exception"],
        "emoji": "💥",
        "priority": "P0"
    },
    "卡顿/性能": {
        "keywords": ["卡", "卡顿", "lag", "慢", "slow", "响应慢", "延迟", "delay", "不流畅", "掉帧", "卡死", "loading慢", "加载慢"],
        "emoji": "🐌",
        "priority": "P1"
    },
    "白屏/黑屏": {
        "keywords": ["白屏", "白画面", "黑屏", "黑画面", "空白", "blank screen", "black screen", "white screen", "无法显示"],
        "emoji": "⬜",
        "priority": "P0"
    },
    "网络连接": {
        "keywords": ["网络", "network", "断网", "连不上", "无法连接", "connection", "offline", "在线", "wifi", "4g", "5g", "信号"],
        "emoji": "🌐",
        "priority": "P1"
    },
    "蓝牙连接": {
        "keywords": ["蓝牙", "bluetooth", "连接不上", "配对", "断连", "断开", "连不上设备", "找不到设备", "bt"],
        "emoji": "📶",
        "priority": "P0"
    },
    "数据同步/丢失": {
        "keywords": ["数据", "同步", "sync", "丢失", "记录没了", "保存不上", "运动记录", "历史", "history", "storage", "本地", "云端", "云同步", "备份"],
        "emoji": "💾",
        "priority": "P1"
    },
    "登录/账号": {
        "keywords": ["登录", "登陆", "账号", "账户", "密码", "注册", "login", "sign in", "sign up", "logout", "忘记密码", "手机号", "邮箱", "验证码"],
        "emoji": "🔐",
        "priority": "P1"
    },
    "升级/更新问题": {
        "keywords": ["更新", "升级", "update", "新版本", "新版", "更后", "升级后", "版本号", "version"],
        "emoji": "🔄",
        "priority": "P2"
    },
    
    # 用户体验
    "界面混乱/导航难": {
        "keywords": ["界面", "ui", "设计", "布局", "layout", "混乱", "混乱", "找不", "导航", "navigation", "菜单", "menu", "入口", "返回", "首页", "主页"],
        "emoji": "🎨",
        "priority": "P2"
    },
    "功能缺失/建议": {
        "keywords": ["建议", "希望", "需要", "缺少", "增加", "想要", "添加", "feature", "add", "want", "need", "request", "期待", "如果", "能不能", "建议增加", "希望能"],
        "emoji": "💡",
        "priority": "P3"
    },
    "使用困难/复杂": {
        "keywords": ["难用", "复杂", "complicated", "confusing", "搞不懂", "不明白", "不会用", "看不懂", "不好用", "体验差"],
        "emoji": "😕",
        "priority": "P2"
    },
    "帮助/教程缺失": {
        "keywords": ["教程", "帮助", "指导", "说明", "guide", "tutorial", "help", "怎么用", "新手", "入门", "引导"],
        "emoji": "📖",
        "priority": "P3"
    },
    
    # 功能相关
    "跑步/运动功能": {
        "keywords": ["跑步", "跑", "运动", "走路", "步行", "walk", "run", "running", "跑步机", "treadmill", "配速", "距离", "卡路里", "calorie"],
        "emoji": "🏃",
        "priority": "P2"
    },
    "课程/训练计划": {
        "keywords": ["课程", "训练", "计划", "教练", "指导", "教程", " workout", "training", "course", "plan", "挑战", "challenge"],
        "emoji": "📋",
        "priority": "P3"
    },
    "数据统计/报表": {
        "keywords": ["统计", "报表", "图表", "分析", "数据", "周报", "月报", "历史记录", "曲线", "趋势"],
        "emoji": "📊",
        "priority": "P3"
    },
    "音乐/娱乐": {
        "keywords": ["音乐", "歌曲", "播放", "听着", "背景音乐", "music", "audio", "podcast", "有声"],
        "emoji": "🎵",
        "priority": "P3"
    },
    "社交/分享": {
        "keywords": ["分享", "好友", "朋友", "排名", "排行", "邀请", "share", "friend", "social", "leaderboard", "社区"],
        "emoji": "👥",
        "priority": "P3"
    },
    "成就/勋章": {
        "keywords": ["勋章", "成就", "奖章", "badge", "achievement", "奖励", "打卡", "签到"],
        "emoji": "🏅",
        "priority": "P3"
    },
    
    # 语言/本地化
    "语言/翻译问题": {
        "keywords": ["法语", "法语版", "français", "语言", "language", "翻译", "traduction", "英文", "中文", "多语言", "看不懂文字", "外文"],
        "emoji": "🌐",
        "priority": "P2"
    },
    "地区/内容适配": {
        "keywords": ["中国", "国内", "海外", "国际", "当地", "本地", "region", "content", "适配"],
        "emoji": "🌍",
        "priority": "P3"
    },
    
    # 商业相关
    "广告/干扰": {
        "keywords": ["广告", "ad", "ads", "advertisement", "推广", "烦人", "弹窗", "popup", "关闭广告"],
        "emoji": "📢",
        "priority": "P2"
    },
    "付费/订阅": {
        "keywords": ["收费", "付费", "价格", "贵", "会员", "订阅", "subscription", "premium", "pro", "vip", "花钱", "退款", "refund"],
        "emoji": "💰",
        "priority": "P1"
    },
    "隐私/权限": {
        "keywords": ["隐私", "权限", "定位", "相机", "通讯录", "privacy", "permission", "location", "camera", "contact", "敏感"],
        "emoji": "🔒",
        "priority": "P1"
    },
    
    # 硬件兼容性
    "设备兼容性": {
        "keywords": ["手机", "机型", "设备", "tablet", "平板", "适配", "device", "compatible", "兼容", "android", "ios", "小米", "华为", "oppo", "vivo", "三星", "pixel"],
        "emoji": "📱",
        "priority": "P2"
    },
    "电池/耗电": {
        "keywords": ["耗电", "费电", "电池", "battery", "用电", "发热", "发烫"],
        "emoji": "🔋",
        "priority": "P2"
    },
    "存储/空间": {
        "keywords": ["存储", "空间", "内存", "storage", "size", "占用", "清理", "缓存"],
        "emoji": "💿",
        "priority": "P3"
    }
}

def classify_review(text):
    """对单条评论进行多分类，返回所有匹配的类别"""
    text_lower = text.lower()
    matches = []
    for category, info in ISSUE_CATEGORIES.items():
        for kw in info["keywords"]:
            if kw.lower() in text_lower:
                priority = info.get("priority", "P3")
                matches.append((category, info["emoji"], priority))
                break  # 每个类别只算一次
    if not matches:
        return [("其他", "📌", "P3")]
    return matches

def detect_sentiment(text):
    positive_words = ['good', 'great', 'awesome', 'love', 'perfect', 'best', 'nice', 'happy', 'helpful', 'easy', 'like', 'excellent', 'amazing', 'works well', 'stable', '不错', '很好', '喜欢', '推荐', '满意']
    negative_words = ['bad', 'terrible', 'awful', 'hate', 'worst', 'useless', 'broken', 'crash', 'bug', 'slow', 'confusing', 'frustrating', 'disappointed', 'waste', '差', '烂', '垃圾', '不好', '失望', '恼火', '烦']
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
                    categories = classify_review(text)
                    result.append({
                        "text": text,
                        "rating": star_rating,
                        "sentiment": detect_sentiment(text),
                        "categories": categories
                    })
            else:
                categories = classify_review(text)
                result.append({
                    "text": text,
                    "rating": star_rating,
                    "sentiment": detect_sentiment(text),
                    "categories": categories
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
                            categories = classify_review(full_text)
                            result.append({
                                "text": full_text,
                                "rating": 3,
                                "sentiment": detect_sentiment(full_text),
                                "categories": categories
                            })
                except:
                    continue
        return result
    except Exception as e:
        print(f"获取苹果评论失败: {e}")
        return []

def generate_ai_summary(google_reviews, apple_reviews, category_stats, priority_stats):
    if not GROQ_API_KEY:
        return "无 AI 摘要"
    
    total = len(google_reviews) + len(apple_reviews)
    google_avg = sum(r['rating'] for r in google_reviews) / len(google_reviews) if google_reviews else 0
    apple_avg = sum(r['rating'] for r in apple_reviews) / len(apple_reviews) if apple_reviews else 0
    
    top_issues = sorted(category_stats.items(), key=lambda x: x[1], reverse=True)[:5]
    issues_text = ", ".join([f"{cat}({cnt}条)" for cat, cnt in top_issues])
    
    # 紧急问题
    urgent = priority_stats.get("P0", 0)
    high = priority_stats.get("P1", 0)
    
    prompt = f"""根据以下数据写一段简短的中文总结（3-4句话）：

总评论数: {total}
Google Play平均评分: {google_avg:.1f}星
App Store平均评分: {apple_avg:.1f}星
主要问题: {issues_text}
P0级问题数: {urgent}
P1级问题数: {high}

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
        msg = {"msgtype": "text", "text": {"content": "本周没有收到任何评论数据。"}}
        send_report_to_dingtalk(msg)
        return
    
    # 统计
    all_reviews = google_reviews + apple_reviews
    total = len(all_reviews)
    
    google_ratings = Counter([r['rating'] for r in google_reviews])
    apple_ratings = Counter([r['rating'] for r in apple_reviews])
    google_sentiment = Counter([r['sentiment'] for r in google_reviews])
    apple_sentiment = Counter([r['sentiment'] for r in apple_reviews])
    
    # 问题分类统计（每条评论可能有多个分类）
    category_counter = Counter()
    priority_counter = Counter()
    category_to_reviews = {}  # 存储每个分类下的评论示例
    
    for review in all_reviews:
        for cat, emoji, priority in review['categories']:
            category_counter[cat] += 1
            priority_counter[priority] += 1
            if cat not in category_to_reviews:
                category_to_reviews[cat] = []
            if len(category_to_reviews[cat]) < 3:  # 每个分类最多保存3条示例
                category_to_reviews[cat].append({
                    "text": review['text'][:100],
                    "rating": review['rating']
                })
    
    google_avg = sum(r['rating'] for r in google_reviews) / len(google_reviews) if google_reviews else 0
    apple_avg = sum(r['rating'] for r in apple_reviews) / len(apple_reviews) if apple_reviews else 0
    
    trend = "📉 下降" if google_avg < 2.5 else "📈 优秀" if google_avg >= 4 else "📊 平稳"
    summary = generate_ai_summary(google_reviews, apple_reviews, category_counter, priority_counter)
    
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
    
    # 问题优先级汇总
    if priority_counter:
        report += f"\n### ⚡ 问题优先级\n\n"
        for priority in ["P0", "P1", "P2", "P3"]:
            cnt = priority_counter.get(priority, 0)
            if priority == "P0":
                report += f"- **🔴 {priority} (紧急/阻断)**: {cnt} 次\n"
            elif priority == "P1":
                report += f"- **🟠 {priority} (高优先级)**: {cnt} 次\n"
            elif priority == "P2":
                report += f"- **🟡 {priority} (中优先级)**: {cnt} 次\n"
            else:
                report += f"- **⚪ {priority} (低优先级)**: {cnt} 次\n"
    
    # 问题归类（按数量排序）
    report += f"\n### 🎯 用户问题详细归类\n\n"
    if category_counter:
        sorted_categories = sorted(category_counter.items(), key=lambda x: x[1], reverse=True)
        for i, (cat, cnt) in enumerate(sorted_categories, 1):
            percent = round(cnt / total * 100) if total > 0 else 0
            bar_length = min(percent // 2, 20)  # 最大20个▉
            bar = "▉" * bar_length
            # 获取示例评论
            examples = category_to_reviews.get(cat, [])
            example_text = ""
            if examples:
                ex = examples[0]['text']
                example_text = f"\n   > 例: \"{ex}...\""
            report += f"{i}. **{cat}**: {cnt} 次 ({percent}%) {bar}{example_text}\n"
    else:
        report += "暂无明确问题分类\n"
    
    # AI 分析总结
    report += f"\n### 🤖 AI 分析总结\n\n{summary}\n"
    
    # 改进建议（根据问题分类自动生成）
    report += f"\n### 💡 改进建议\n\n"
    top_cats = sorted(category_counter.items(), key=lambda x: x[1], reverse=True)[:3]
    suggestions = []
    for cat, cnt in top_cats:
        if "崩溃" in cat or "闪退" in cat:
            suggestions.append("• 优先修复崩溃/Bug问题，提升应用稳定性")
        elif "卡顿" in cat or "性能" in cat:
            suggestions.append("• 优化应用性能，减少卡顿和加载时间")
        elif "界面" in cat or "混乱" in cat:
            suggestions.append("• 简化首页布局，优化用户导航路径")
        elif "功能缺失" in cat:
            suggestions.append("• 评估并考虑添加用户高频建议的新功能")
        elif "蓝牙" in cat:
            suggestions.append("• 优化蓝牙连接稳定性，加强设备兼容性")
        elif "数据" in cat:
            suggestions.append("• 完善数据同步机制，防止运动记录丢失")
        elif "翻译" in cat:
            suggestions.append("• 完善多语言翻译，优化本地化体验")
        elif "广告" in cat:
            suggestions.append("• 优化广告展示策略，减少对用户干扰")
        else:
            suggestions.append(f"• 关注并解决 {cat} 相关问题")
    if suggestions:
        for s in suggestions[:5]:
            report += f"{s}\n"
    else:
        report += "• 持续收集用户反馈，优化产品体验\n"
    
    report += f"""
---
*报告生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    send_report_to_dingtalk(report)
    print("报告生成完成")

if __name__ == "__main__":
    main()
