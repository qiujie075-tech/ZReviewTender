import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
PACKAGE_NAME = os.environ.get('PACKAGE_NAME')

if not SERVICE_ACCOUNT_JSON:
    raise Exception("缺少 SERVICE_ACCOUNT_JSON")

creds_info = json.loads(SERVICE_ACCOUNT_JSON)
credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/androidpublisher"]
)
service = build("androidpublisher", "v3", credentials=credentials)

# 获取前5条评论，打印 replies 字段
response = service.reviews().list(packageName=PACKAGE_NAME, maxResults=5).execute()
reviews = response.get("reviews", [])
for i, review in enumerate(reviews):
    print(f"\n--- 评论 {i+1} ---")
    print(f"reviewId: {review.get('reviewId')}")
    print(f"replies 原始数据: {json.dumps(review.get('replies'), indent=2)}")
