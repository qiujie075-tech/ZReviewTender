import os
import json
import time
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build


# ==================================================
# Environment variables
# ==================================================

SERVICE_ACCOUNT_JSON = os.environ.get("SERVICE_ACCOUNT_JSON")
PACKAGE_NAME = os.environ.get("PACKAGE_NAME")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

print("=== Google Play Auto Reply ===")
print("Rule: Only reply to reviews without an existing developer reply.")


required_envs = {
    "SERVICE_ACCOUNT_JSON": SERVICE_ACCOUNT_JSON,
    "PACKAGE_NAME": PACKAGE_NAME,
    "GROQ_API_KEY": GROQ_API_KEY,
}

missing = [
    name
    for name, value in required_envs.items()
    if not value
]

if missing:
    raise Exception(
        f"Missing environment variables: {', '.join(missing)}"
    )


# ==================================================
# Google Play authentication
# ==================================================

creds_info = json.loads(SERVICE_ACCOUNT_JSON)

credentials = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=[
        "https://www.googleapis.com/auth/androidpublisher"
    ]
)

service = build(
    "androidpublisher",
    "v3",
    credentials=credentials,
    cache_discovery=False
)


# ==================================================
# Extract AI reply
# ==================================================

def extract_ai_reply(result):
    """
    Extract the visible final answer from Groq/OpenAI-compatible
    chat completion responses.

    Returns None if no usable reply can be found.
    """

    try:
        choices = result.get("choices", [])

        if not choices:
            print("AI response has no choices.")
            return None

        choice = choices[0]
        message = choice.get("message", {})

        # Normal Chat Completions response
        content = message.get("content")

        if isinstance(content, str) and content.strip():
            return content.strip()

        # Some compatible responses may return structured content
        if isinstance(content, list):

            text_parts = []

            for item in content:

                if isinstance(item, str):
                    if item.strip():
                        text_parts.append(item.strip())

                elif isinstance(item, dict):

                    text_value = item.get("text")

                    if isinstance(text_value, str) and text_value.strip():
                        text_parts.append(text_value.strip())

                    elif isinstance(text_value, dict):
                        value = text_value.get("value")

                        if isinstance(value, str) and value.strip():
                            text_parts.append(value.strip())

                    item_content = item.get("content")

                    if isinstance(item_content, str) and item_content.strip():
                        text_parts.append(item_content.strip())

            if text_parts:
                return "\n".join(text_parts).strip()

        # Compatibility fallback
        choice_text = choice.get("text")

        if isinstance(choice_text, str) and choice_text.strip():
            return choice_text.strip()

        return None

    except Exception as e:
        print(f"Failed to parse AI response: {e}")
        return None


# ==================================================
# AI targeted reply
# ==================================================

def ai_generate_reply(review_text, rating):

    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    system_prompt = """
You are the official customer support representative for PitPat.

Your job is to respond to Google Play reviews.

Every response must be specific to what the user actually wrote.
Never use a generic customer-service response when the review
contains specific details.

Return only the final public reply.
Do not include analysis, reasoning, labels, quotation marks,
or explanations.
"""

    user_prompt = f"""
Write a response to this Google Play review.

Star rating: {rating}/5

Review:
{review_text}

Rules:

1. Reply in the SAME LANGUAGE as the original review.

2. Clearly respond to the actual content of the review.

3. Do NOT use generic replies such as:
   "Thanks for your feedback."
   "We'll address the issues you raised."
   "Thank you for your feedback. We will address your concerns."

4. For a positive review:
   - thank the user naturally;
   - mention the specific feature or experience they praised;
   - do not talk about problems if they reported none.

5. For a negative review:
   - acknowledge the specific complaint;
   - apologize naturally when appropriate;
   - mention the exact area they had trouble with.

6. If the review mentions things such as:
   - audio cues
   - voice coaching
   - treadmill connection
   - device pairing
   - workout tracking
   - achievements
   - milestones
   - PitPat Band
   - health data
   - Apple Health
   - subscriptions
   - payment
   - ads
   - account/login
   - reports
   - AI workouts

   respond to that specific topic.

7. Do not invent troubleshooting instructions.

8. Do not invent compensation, refunds or policies.

9. Do not promise that something has already been fixed.

10. Do not ask the user to change their rating.

11. Do not mention AI, automation, Groq or automated replies.

12. Keep the response friendly, natural and professional.

13. Avoid repetitive wording.

14. Keep the final reply concise.

15. Maximum 320 characters.

Return ONLY the final public reply.
"""

    data = {
        "model": "openai/gpt-oss-20b",
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        "temperature": 0.4,
        "max_completion_tokens": 500
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=data,
            timeout=60
        )

        print(
            f"AI HTTP status: {response.status_code}"
        )

        if response.status_code != 200:

            print(
                f"AI request failed: "
                f"HTTP {response.status_code}"
            )

            print(
                f"AI error body: "
                f"{response.text[:1000]}"
            )

            return None

        try:
            result = response.json()

        except Exception as e:

            print(
                f"AI response is not valid JSON: {e}"
            )

            print(
                f"Raw response: "
                f"{response.text[:1000]}"
            )

            return None

        reply = extract_ai_reply(result)

        if not reply:

            print("AI returned no usable final reply.")

            # Print diagnostic information,
            # but never print API keys.
            try:
                safe_debug = json.dumps(
                    result,
                    ensure_ascii=False
                )

                print(
                    "AI response structure: "
                    + safe_debug[:3000]
                )

            except Exception:
                print(
                    "Unable to print AI response structure."
                )

            return None

        reply = (
            reply
            .strip()
            .strip('"')
            .strip("'")
            .strip()
        )

        # Remove accidental prefixes
        prefixes = [
            "Final answer:",
            "Final reply:",
            "Response:",
            "Reply:"
        ]

        for prefix in prefixes:
            if reply.lower().startswith(prefix.lower()):
                reply = reply[len(prefix):].strip()

        if not reply:
            print("AI reply became empty after cleanup.")
            return None

        if len(reply) > 320:
            reply = reply[:317].rstrip() + "..."

        return reply

    except requests.exceptions.Timeout:

        print("AI request timed out.")
        return None

    except Exception as e:

        print(f"AI error: {e}")
        return None


# ==================================================
# Get Google Play reviews
# ==================================================

def get_all_reviews():

    results = []

    try:

        response = (
            service
            .reviews()
            .list(
                packageName=PACKAGE_NAME,
                maxResults=100
            )
            .execute()
        )

        reviews = response.get(
            "reviews",
            []
        )

        print(
            f"Google Play API returned "
            f"{len(reviews)} reviews."
        )

        for review in reviews:

            review_id = review.get(
                "reviewId"
            )

            if not review_id:
                continue

            comments = review.get(
                "comments",
                []
            )

            user_comment = None
            developer_comment = None

            for comment in comments:

                if "userComment" in comment:
                    user_comment = (
                        comment["userComment"]
                    )

                if "developerComment" in comment:
                    developer_comment = (
                        comment["developerComment"]
                    )

            if not user_comment:
                continue

            review_text = (
                user_comment
                .get("text", "")
                .strip()
            )

            star_rating = (
                user_comment
                .get("starRating", 0)
            )

            if not review_text:
                continue

            has_developer_reply = bool(
                developer_comment
                and developer_comment
                .get("text", "")
                .strip()
            )

            results.append({
                "id": review_id,
                "text": review_text,
                "rating": star_rating,
                "has_developer_reply":
                    has_developer_reply
            })

        print(
            f"Valid reviews received: "
            f"{len(results)}"
        )

        return results

    except Exception as e:

        print(
            f"Failed to get Google Play reviews: {e}"
        )

        return []


# ==================================================
# Re-check current reply status
# ==================================================

def has_reply_now(review_id):

    try:

        response = (
            service
            .reviews()
            .list(
                packageName=PACKAGE_NAME,
                maxResults=100
            )
            .execute()
        )

        reviews = response.get(
            "reviews",
            []
        )

        for review in reviews:

            if review.get("reviewId") != review_id:
                continue

            comments = review.get(
                "comments",
                []
            )

            for comment in comments:

                developer_comment = (
                    comment.get(
                        "developerComment"
                    )
                )

                if (
                    developer_comment
                    and developer_comment
                    .get("text", "")
                    .strip()
                ):
                    return True

            return False

        # Review disappeared from the current API response.
        # Fail safely instead of risking an overwrite.
        return None

    except Exception as e:

        print(
            f"Unable to re-check reply status "
            f"for {review_id}: {e}"
        )

        return None


# ==================================================
# Post Google Play reply
# ==================================================

def post_reply(review_id, reply_text):

    if not reply_text:
        return False

    if len(reply_text) > 320:
        reply_text = (
            reply_text[:317]
            .rstrip()
            + "..."
        )

    try:

        (
            service
            .reviews()
            .reply(
                packageName=PACKAGE_NAME,
                reviewId=review_id,
                body={
                    "replyText": reply_text
                }
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
            f"{review_id} - {e}"
        )

        return False


# ==================================================
# Webhook report
# ==================================================

def send_report(
    success,
    skipped,
    failed
):

    if not WEBHOOK_URL:
        return

    content = (
        "Google Play Auto Reply completed\n"
        f"New replies: {success}\n"
        f"Existing replies skipped: {skipped}\n"
        f"Failed / waiting for retry: {failed}"
    )

    data = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }

    try:

        requests.post(
            WEBHOOK_URL,
            json=data,
            timeout=10
        )

    except Exception as e:

        print(
            f"Webhook error: {e}"
        )


# ==================================================
# MAIN
# ==================================================

print("Getting Google Play reviews...")

reviews = get_all_reviews()

print(
    f"Reviews checked: {len(reviews)}"
)

success_count = 0
skipped_count = 0
failed_count = 0


for review in reviews:

    review_id = review["id"]
    review_text = review["text"]
    rating = review["rating"]

    print(
        "\n------------------------------"
    )

    print(
        f"Review ID: {review_id}"
    )

    print(
        f"Rating: {rating}"
    )

    print(
        f"Review: {review_text[:250]}"
    )

    # ==================================================
    # RULE 1
    # Existing developer reply -> NEVER MODIFY
    # ==================================================

    if review["has_developer_reply"]:

        print(
            "SKIP: Developer reply already exists. "
            "It will NOT be modified."
        )

        skipped_count += 1

        continue

    # ==================================================
    # RULE 2
    # No reply -> generate targeted response
    # ==================================================

    print(
        "No existing reply. "
        "Generating targeted response..."
    )

    reply = ai_generate_reply(
        review_text,
        rating
    )

    # Never use generic fallback
    if not reply:

        print(
            "AI generation failed. "
            "No reply posted."
        )

        failed_count += 1

        continue

    print(
        f"Generated reply "
        f"({len(reply)} chars): "
        f"{reply}"
    )

    # ==================================================
    # RULE 3
    # Re-check before posting
    #
    # If someone manually replied while the AI response
    # was being generated, NEVER overwrite that reply.
    # ==================================================

    current_reply_status = (
        has_reply_now(review_id)
    )

    if current_reply_status is True:

        print(
            "SKIP: A developer reply appeared "
            "before posting. "
            "It will NOT be overwritten."
        )

        skipped_count += 1

        continue

    if current_reply_status is None:

        print(
            "SKIP: Could not safely verify "
            "current reply status. "
            "No reply posted."
        )

        failed_count += 1

        continue

    # ==================================================
    #
