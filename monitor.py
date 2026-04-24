import os
import json
import requests
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
from langdetect import detect  # 新增语言检测库

SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
PACKAGE_NAME = os.environ.get('PACKAGE_NAME')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
HF_TOKEN = os.environ.get('HF_TOKEN')

if not all([SERVICE_ACCOUNT_JSON, PACKAGE_NAME, WEBHOOK_URL, HF_TOKEN]):
    raise Exception("缺少必要的环境变量")

creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

def detect_language(text):
    """检测文本语言，返回语言代码（如 'zh-cn', 'en', 'ja' 等）"""
    try:
        lang = detect(text)
        # 将 'zh-cn', 'zh-tw' 统一为 'zh'
        if lang.startswith('zh'):
            return 'zh'
        return lang
    except:
        return 'en'  # 默认英语

def generate_reply(text):
    """根据评论语言生成同语言回复"""
    lang = detect_language(text)
    # 根据语言设置 system prompt
    lang_prompts = {
        'zh': "你是专业的客服助手，请用中文友好、简洁地回复用户评论。",
        'en': "You are a professional customer service assistant. Please reply to user reviews in English, friendly and concise.",
        'ja': "あなたは専門のカスタマーサポートアシスタントです。ユーザーのレビューに対して、親切で簡潔な日本語で返信してください。",
        'ko': "당신은 전문 고객 서비스 어시스턴트입니다. 사용자 리뷰에 친절하고 간결한 한국어로 답변하세요.",
        'es': "Eres un asistente de servicio al cliente profesional. Responde a las reseñas de los usuarios en español, de manera amable y concisa.",
        'fr': "Vous êtes un assistant de service client professionnel. Répondez aux avis des utilisateurs en français, de manière amicale et concise.",
        'de': "Sie sind ein professioneller Kundendienstassistent. Antworten Sie auf Benutzerbewertungen auf Deutsch, freundlich und prägnant.",
        'it': "Sei un assistente di servizio clienti professionale. Rispondi alle recensioni degli utenti in italiano, in modo amichevole e conciso.",
        'pt': "Você é um assistente de atendimento ao cliente profissional. Responda às avaliações dos usuários em português, de forma amigável e concisa.",
        'ru': "Вы профессиональный помощник службы поддержки. Отвечайте на отзывы пользователей на русском языке, дружелюбно и лаконично.",
        'ar': "أنت مساعد خدمة عملاء محترف. قم بالرد على تقييمات المستخدمين باللغة العربية، بطريقة ودية ومختصرة."
    }
    system_prompt = lang_prompts.get(lang, lang_prompts['en'])  # 默认英语

    url = "https://router.huggingface.co/v1/chat/completions"
    headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}
    data = {
        "model": "moonshotai/Kimi-K2-Instruct-0905",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Please reply to this review: {text}"}
        ],
        "temperature": 0.7,
        "max_tokens": 150
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"].strip()
        print(f"检测到语言: {lang}, 回复已生成")
        return reply
    except Exception as e:
        print(f"AI 调用失败: {e}")
        # 降级为默认多语言回复
        return "Thank you for your feedback! We will continue to improve." if lang == 'en' else "感谢您的反馈，我们会持续改进！"

def post_reply(review_id, reply):
    service.reviews().reply(
        packageName=PACKAGE_NAME,
        reviewId=review_id,
        body={"replyText": reply}
    ).execute()
    print(f"✅ 已回复 {review_id}")

def send_report(success, total):
    data = {"msgtype": "text", "text": {"content": f"自动回复完成：成功 {success}/{total}"}}
    try:
        requests.post(WEBHOOK_URL, json=data, timeout=10)
    except Exception as e:
        print(f"通知发送失败: {e}")

response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=20).execute()
reviews = response.get("reviews", [])
unreplied = [r for r in reviews if "replies" not in r or not r["replies"]]
print(f"找到 {len(unreplied)} 条未回复评论")

success = 0
for review in unreplied:
    rid = review["reviewId"]
    comment = review.get("comments", [{}])[0].get("userComment", {}).get("text", "")
    if not comment:
        continue
    print(f"处理评论 {rid}: {comment[:50]}...")
    reply = generate_reply(comment)
    try:
        post_reply(rid, reply)
        success += 1
    except Exception as e:
        print(f"回复失败 {rid}: {e}")
    time.sleep(2)

send_report(success, len(unreplied))
print("执行完成")
