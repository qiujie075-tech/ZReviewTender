import os
import time
import jwt
import requests
from datetime import datetime

PRIVATE_KEY = os.environ.get("APPLE_PRIVATE_KEY")
KEY_ID = os.environ.get("APPLE_KEY_ID")
ISSUER_ID = os.environ.get("APPLE_ISSUER_ID")

APP_ID = "1598065258"

WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

print("=== Apple App Store Auto Reply ===")
print("Rule: Only reply to reviews that currently have NO developer response.")


# ==================================================
# Environment variables
# ==================================================

required_envs = {
    "APPLE_PRIVATE_KEY": PRIVATE_KEY,
    "APPLE_KEY_ID": KEY_ID,
    "APPLE_ISSUER_ID": ISSUER_ID,
    "GROQ_API_KEY": GROQ_API_KEY,
}

missing = [name for name, value in required_envs.items() if not value]

if missing:
    raise Exception(
        f"Missing environment variables: {', '.join(missing)}"
    )


# ==================================================
# Apple JWT
# ==================================================

def generate_token():

    headers = {
        "alg": "ES256",
        "kid": KEY_ID,
        "typ": "JWT"
    }

    payload = {
        "iss": ISSUER_ID,
        "exp": int(datetime.utcnow().timestamp()) + 20 * 60,
        "aud": "appstoreconnect-v1"
    }

    return jwt.encode(
        payload,
        PRIVATE_KEY,
        algorithm="ES256",
        headers=headers
    )


def apple_headers():

    return {
        "Authorization": f"Bearer {generate_token()}",
        "Content-Type": "application/json"
    }


# ==================================================
# Get reviews
# ==================================================

def get_reviews():

    url = (
        f"https://api.appstoreconnect.apple.com/v1/apps/"
        f"{APP_ID}/customerReviews"
        f"?limit=50&sort=-createdDate"
    )

    try:

        response = requests.get(
            url,
            headers=apple_headers(),
            timeout=20
        )

        if response.status_code != 200:

            print(
                f"Failed to get reviews: "
                f"{response.status_code} "
                f"{response.text[:500]}"
            )

            return []

        return response.json().get("data", [])

    except Exception as e:

        print(f"Get reviews error: {e}")

        return []


# ==================================================
# IMPORTANT:
# Check whether Apple currently has a developer reply
# ==================================================

def has_existing_reply(review_id):

    url = (
        "https://api.appstoreconnect.apple.com/v1/"
        f"customerReviews/{review_id}/response"
    )

    try:

        response = requests.get(
            url,
            headers=apple_headers(),
            timeout=20
        )

        # A response object exists.
        if response.status_code == 200:

            data = response.json().get("data")

            if data:
                return True

            return False

        # Apple says no response exists.
        if response.status_code == 404:
            return False

        # IMPORTANT:
        # If Apple returns an unexpected error,
        # DO NOT assume that there is no reply.
        # Skip the review instead to protect manual replies.
        print(
            f"Unable to verify existing response for {review_id}: "
            f"HTTP {response.status_code} "
            f"{response.text[:300]}"
        )

        return None

    except Exception as e:

        print(
            f"Unable to verify existing response for "
            f"{review_id}: {e}"
        )

        # Fail safe:
        # uncertain = do not reply
        return None


# ==================================================
# Generate targeted AI reply
# ==================================================

def generate_ai_reply(review_text, rating):

    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""
You are the official customer support representative for PitPat.

Write a short, natural and specific response to this App Store review.

Rating: {rating}/5

Review:
"{review_text}"

Requirements:

1. Reply in the SAME LANGUAGE as the user's review.

2. Read the review carefully and respond specifically to what
   the user actually said.

3. Do NOT use generic responses such as:
   "Thank you for your feedback. We will address your concerns."

4. If the user reports a bug or technical issue:
   acknowledge the specific problem and briefly apologize
   when appropriate.

5. If the review mentions login, connection, treadmill,
   device pairing, PitPat Band, workout tracking,
   subscription, payment, account, advertising, update,
   or another specific function, mention that issue naturally.

6. If the review is positive:
   thank the user naturally and respond to the specific
   feature or experience they liked.

7. If several issues are mentioned:
   acknowledge the main issue or issues instead of giving
   a generic response.

8. Do NOT invent troubleshooting steps.

9. Do NOT invent refunds, compensation, policies,
   product features or promises.

10. Do NOT claim that an issue has already been fixed
    unless that is known.

11. Do NOT ask the user to change their rating.

12. Do NOT mention AI or automated replies.

13. Keep the tone friendly, professional and human.

14. Maximum 300 characters.

Return ONLY the final reply.
"""

    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "max_tokens": 180,
        "temperature": 0.5
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=data,
            timeout=30
        )

        if response.status_code != 200:

            print(
                f"AI request failed: "
                f"HTTP {response.status_code} "
                f"{response.text[:500]}"
            )

            return None

        result = response.json()

        reply = (
            result
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        if not reply:

            print("AI returned empty response.")

            return None

        # Remove accidental quotation marks
        reply = reply.strip('"').strip("'").strip()

        # Length protection
        if len(reply) > 300:

            reply = reply[:297].rstrip() + "..."

        return reply

    except Exception as e:

        print(f"AI error: {e}")

        return None


# ==================================================
# Post Apple response
# ==================================================

def post_reply(review_id, reply_text):

    url = (
        "https://api.appstoreconnect.apple.com/v1/"
        "customerReviewResponses"
    )

    payload = {
        "data": {
            "type": "customerReviewResponses",
            "attributes": {
                "responseBody": reply_text
            },
            "relationships": {
                "review": {
                    "data": {
                        "id": review_id,
                        "type": "customerReviews"
                    }
                }
            }
        }
    }

    try:

        response = requests.post(
            url,
            headers=apple_headers(),
            json=payload,
            timeout=20
        )

        if response.status_code in (200, 201):

            print(f"Reply successful: {review_id}")

            return True

        print(
            f"Reply failed {review_id}: "
            f"HTTP {response.status_code} "
            f"{response.text[:500]}"
        )

        return False

    except Exception as e:

        print(
            f"Reply error {review_id}: {e}"
        )

        return False


# ==================================================
# Webhook report
# ==================================================

def send_report(success, skipped, failed):

    if not WEBHOOK_URL:
        return

    content = (
        "🍎 Apple App Store Auto Reply completed\n"
        f"New replies: {success}\n"
        f"Existing replies skipped: {skipped}\n"
        f"Failed / waiting for retry: {failed}"
    )

    payload = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }

    try:

        requests.post(
            WEBHOOK_URL,
            json=payload,
            timeout=10
        )

    except Exception as e:

        print(f"Webhook error: {e}")


# ==================================================
# Main
# ==================================================

def main():

    print("Getting App Store reviews...")

    reviews = get_reviews()

    print(f"Reviews received: {len(reviews)}")

    success_count = 0
    skipped_count = 0
    failed_count = 0

    for review in reviews:

        review_id = review.get("id")

        if not review_id:
            continue

        attributes = review.get("attributes", {})

        review_text = (
            attributes.get("body", "") or ""
        ).strip()

        rating = attributes.get("rating", 0)

        if not review_text:
            continue

        print("\n--------------------------------")

        print(f"Review ID: {review_id}")
        print(f"Rating: {rating}")
        print(f"Review: {review_text[:200]}")

        # ==========================================
        # MOST IMPORTANT PROTECTION
        # ==========================================

        existing_reply = has_existing_reply(review_id)

        # Already has Apple developer response:
        # NEVER modify it.
        if existing_reply is True:

            print(
                "SKIP: Developer response already exists. "
                "It will NOT be modified."
            )

            skipped_count += 1

            continue

        # We could not safely determine whether a response exists.
        # Do nothing to protect possible manual replies.
        if existing_reply is None:

            print(
                "SKIP: Could not safely verify response status."
            )

            failed_count += 1

            continue

        # ==========================================
        # No response -> AI reply
        # ==========================================

        print(
            "No existing response. "
            "Generating targeted reply..."
        )

        reply = generate_ai_reply(
            review_text,
            rating
        )

        # AI failed:
        # Do NOT post a generic fallback.
        if not reply:

            print(
                "AI generation failed. "
                "No reply will be posted."
            )

            failed_count += 1

            continue

        print(
            f"Generated reply ({len(reply)} chars): "
            f"{reply}"
        )

        # ==========================================
        # SECOND SAFETY CHECK
        #
        # Check Apple again immediately before POST.
        # This protects against someone manually
        # replying while this workflow is running.
        # ==========================================

        existing_reply_before_post = (
            has_existing_reply(review_id)
        )

        if existing_reply_before_post is True:

            print(
                "SKIP: A developer response appeared "
                "before posting. Do not overwrite."
            )

            skipped_count += 1

            continue

        if existing_reply_before_post is None:

            print(
                "SKIP: Could not safely re-check "
                "response status."
            )

            failed_count += 1

            continue

        # ==========================================
        # Still no response -> POST
        # ==========================================

        if post_reply(
            review_id,
            reply
        ):

            success_count += 1

        else:

            failed_count += 1

        time.sleep(2)

    print("\n================================")

    print(
        f"Completed: "
        f"{success_count} new replies, "
        f"{skipped_count} existing replies skipped, "
        f"{failed_count} failed/waiting."
    )

    send_report(
        success_count,
        skipped_count,
        failed_count
    )


if __name__ == "__main__":
    main()
