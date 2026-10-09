
import os
import json
import time
import requests

from google.oauth2 import service_account
from googleapiclient.discovery import build


# ==========================================
# CONFIG
# ==========================================

SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")
PACKAGE_NAME = os.getenv("PACKAGE_NAME")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

MIN_RATING = 4
MAX_RATING = 5

REQUEST_INTERVAL = 4
MAX_AI_RETRIES = 5


print("=== Google Play Auto Reply ===")
print("Only 4-5 star reviews will be replied to.")
print("Existing developer replies will NEVER be modified.")
print(f"AI model: {GROQ_MODEL}")


# ==========================================
# ENVIRONMENT CHECK
# ==========================================

required_envs = {
    "SERVICE_ACCOUNT_JSON": SERVICE_ACCOUNT_JSON,
    "PACKAGE_NAME": PACKAGE_NAME,
    "GROQ_API_KEY": GROQ_API_KEY,
}

missing = [
    key for key, value in required_envs.items()
    if not value
]

if missing:
    raise RuntimeError(
        "Missing environment variables: "
        + ", ".join(missing)
    )


# ==========================================
# GOOGLE AUTH
# ==========================================

credentials = service_account.Credentials.from_service_account_info(
    json.loads(SERVICE_ACCOUNT_JSON),
    scopes=[
        "https://www.googleapis.com/auth/androidpublisher"
    ],
)

service = build(
    "androidpublisher",
    "v3",
    credentials=credentials,
    cache_discovery=False,
)


# ==========================================
# FETCH REVIEWS
# ==========================================

def get_reviews():

    all_reviews = []
    token = None

    try:
        while True:

            params = {
                "packageName": PACKAGE_NAME,
                "maxResults": 100,
            }

            if token:
                params["token"] = token

            result = (
                service.reviews()
                .list(**params)
                .execute()
            )

            reviews = result.get("reviews", [])
            all_reviews.extend(reviews)

            token = (
                result.get("tokenPagination", {})
                .get("nextPageToken")
            )

            if not token:
                break

        print(
            f"Google Play API returned "
            f"{len(all_reviews)} reviews."
        )

        return all_reviews

    except Exception as e:
        print(f"Failed to fetch reviews: {e}")
        raise


# ==========================================
# PARSE REVIEW
# ==========================================

def parse_review(review):

    review_id = review.get("reviewId")

    user_comment = None
    developer_comment = None

    for item in review.get("comments", []):

        if "userComment" in item:
            user_comment = item["userComment"]

        if "developerComment" in item:
            developer_comment = item["developerComment"]

    if not user_comment:
        return None

    text = str(
        user_comment.get("text") or ""
    ).strip()

    try:
        rating = int(
            user_comment.get("starRating", 0)
        )
    except (ValueError, TypeError):
        rating = 0

    has_reply = developer_comment is not None

    if not review_id or not text:
        return None

    return {
        "id": review_id,
        "text": text,
        "rating": rating,
        "has_reply": has_reply,
    }


# ==========================================
# AI RESPONSE EXTRACTION
# ==========================================

def extract_ai_reply(result):

    choices = result.get("choices", [])

    if not choices:
        return None

    choice = choices[0]
    message = choice.get("message") or {}

    content = message.get("content")

    if isinstance(content, str):
        return content.strip() or None

    if isinstance(content, list):

        parts = []

        for item in content:

            if isinstance(item, str):
                parts.append(item)

            elif isinstance(item, dict):

                value = item.get("text")

                if isinstance(value, str):
                    parts.append(value)

                elif isinstance(value, dict):
                    text = value.get("value")

                    if isinstance(text, str):
                        parts.append(text)

        reply = "\n".join(parts).strip()
        return reply or None

    return None


# ==========================================
# CLEAN REPLY
# ==========================================

def clean_reply(reply):

    if not reply:
        return None

    reply = (
        reply.strip()
        .strip('"')
        .strip("'")
        .strip()
    )

    for prefix in [
        "Final answer:",
        "Final reply:",
        "Response:",
        "Reply:",
    ]:

        if reply.lower().startswith(
            prefix.lower()
        ):
            reply = reply[len(prefix):].strip()

    if not reply:
        return None

    if len(reply) > 320:
        reply = reply[:317].rstrip() + "..."

    return reply


# ==========================================
# RETRY WAIT
# ==========================================

def get_retry_wait(response, attempt):

    retry_after = response.headers.get(
        "retry-after"
    )

    if retry_after:
        try:
            return max(
                2,
                float(retry_after) + 2
            )
        except (ValueError, TypeError):
            pass

    return min(
        60,
        10 * (2 ** (attempt - 1))
    )


# ==========================================
# GENERATE AI REPLY
# ==========================================

def generate_reply(review_text, rating):

    prompt = f"""
You are the official customer support representative for PitPat.

Write ONE natural public reply to this Google Play review.

Rating: {rating}/5

Review:
"{review_text}"

Rules:

1. Reply in the SAME LANGUAGE as the review.

2. Read the review carefully.

3. Mention the SPECIFIC feature, experience, or
   positive detail the user described.

4. Never give a generic response such as:
   "Thanks for your feedback."
   "We appreciate your support."

5. If the user praises a feature, mention that
   exact feature naturally.

6. If the review contains both praise and a
   suggestion, acknowledge both.

7. Do not invent features, fixes, policies,
   refunds, compensation, or promises.

8. Do not ask users to change their ratings.

9. Do not mention AI or automation.

10. Be friendly, professional, and natural.

11. Avoid repetitive wording.

12. Maximum 320 characters.

Return ONLY the final public reply.
"""

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0.5,
        "max_completion_tokens": 350,
        "reasoning_effort": "low",
        "include_reasoning": False,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(
        1,
        MAX_AI_RETRIES + 1
    ):

        print(
            f"AI request attempt "
            f"{attempt}/{MAX_AI_RETRIES}"
        )

        try:
            response = requests.post(
                GROQ_URL,
                headers=headers,
                json=payload,
                timeout=60,
            )

        except requests.RequestException as e:

            print(f"AI network error: {e}")

            if attempt < MAX_AI_RETRIES:
                time.sleep(
                    min(60, 10 * attempt)
                )
                continue

            return None

        print(
            f"AI HTTP status: "
            f"{response.status_code}"
        )

        if response.status_code == 200:

            try:
                result = response.json()
                reply = extract_ai_reply(result)
                return clean_reply(reply)

            except (ValueError, TypeError) as e:
                print(f"AI parse error: {e}")
                return None

        if response.status_code == 429:

            print("Groq rate limit reached.")

            if attempt < MAX_AI_RETRIES:

                wait = get_retry_wait(
                    response,
                    attempt
                )

                print(
                    f"Waiting {wait:.1f}s "
                    "before retry..."
                )

                time.sleep(wait)
                continue

            return None

        if response.status_code in (
            500, 502, 503, 504
        ):

            if attempt < MAX_AI_RETRIES:
                time.sleep(
                    min(60, 10 * attempt)
                )
                continue

            return None

        print(
            f"AI request failed: "
            f"{response.text[:500]}"
        )

        return None

    return None


# ==========================================
# RECHECK BEFORE POSTING
# ==========================================

def check_reply_status(review_id):

    try:
        result = (
            service.reviews()
            .get(
                packageName=PACKAGE_NAME,
                reviewId=review_id,
            )
            .execute()
        )

        for item in result.get("comments", []):

            if "developerComment" in item:
                return True

        return False

    except Exception as e:

        print(
            f"Cannot verify review "
            f"{review_id}: {e}"
        )

        return None


# ==========================================
# POST REPLY
# ==========================================

def post_reply(review_id, reply):

    try:
        (
            service.reviews()
            .reply(
                packageName=PACKAGE_NAME,
                reviewId=review_id,
                body={
                    "replyText": reply
                },
            )
            .execute()
        )

        print(
            f"Reply successful: {review_id}"
        )

        return True

    except Exception as e:

        print(
            f"Reply failed: "
            f"{review_id}: {e}"
        )

        return False


# ==========================================
# WEBHOOK
# ==========================================

def send_report(success, skipped, failed):

    if not WEBHOOK_URL:
        return

    content = (
        "Google Play Auto Reply completed\n"
        f"New replies: {success}\n"
        f"Skipped: {skipped}\n"
        f"Failed: {failed}"
    )

    try:
        requests.post(
            WEBHOOK_URL,
            json={
                "msgtype": "text",
                "text": {
                    "content": content
                },
            },
            timeout=10,
        )

    except requests.RequestException as e:
        print(f"Webhook error: {e}")


# ==========================================
# MAIN
# ==========================================

def main():

    reviews = get_reviews()

    success = 0
    skipped = 0
    failed = 0

    for raw_review in reviews:

        review = parse_review(raw_review)

        if not review:
            continue

        review_id = review["id"]
        rating = review["rating"]

        print(
            "\n------------------------------"
        )

        print(
            f"Review ID: {review_id}"
        )

        print(f"Rating: {rating}")

        # ----------------------------------
        # ONLY 4-5 STAR REVIEWS
        # ----------------------------------

        if rating < MIN_RATING or rating > MAX_RATING:

            print(
                "SKIP: Rating is below 4 stars. "
                "No reply will be posted."
            )

            skipped += 1
            continue

        # ----------------------------------
        # EXISTING REPLY
        # ----------------------------------

        if review["has_reply"]:

            print(
                "SKIP: Developer reply already exists. "
                "It will NOT be modified."
            )

            skipped += 1
            continue

        # ----------------------------------
        # GENERATE TARGETED REPLY
        # ----------------------------------

        print(
            "Positive review without reply. "
            "Generating AI response..."
        )

        reply = generate_reply(
            review["text"],
            rating,
        )

        if not reply:

            print(
                "AI generation failed. "
                "No reply posted."
            )

            failed += 1
            time.sleep(REQUEST_INTERVAL)
            continue

        print(
            f"Generated reply "
            f"({len(reply)} chars): {reply}"
        )

        # ----------------------------------
        # FINAL SAFETY CHECK
        # ----------------------------------

        current_status = check_reply_status(
            review_id
        )

        if current_status is True:

            print(
                "SKIP: Existing reply detected "
                "before posting."
            )

            skipped += 1
            continue

        if current_status is None:

            print(
                "SAFE SKIP: Cannot verify "
                "existing reply status."
            )

            failed += 1
            continue

        # ----------------------------------
        # POST
        # ----------------------------------

        if post_reply(review_id, reply):
            success += 1
        else:
            failed += 1

        time.sleep(REQUEST_INTERVAL)

    print(
        "\n=============================="
    )

    print(
        f"Completed: {success} new replies, "
        f"{skipped} skipped, "
        f"{failed} failed."
    )

    send_report(success, skipped, failed)


if __name__ == "__main__":
    main()
