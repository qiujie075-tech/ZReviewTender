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
    credentials=credentials
)


# ==================================================
# Generate targeted AI reply
# ==================================================

def ai_generate_reply(review_text, rating):

    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""
You are the official customer support representative for PitPat.

Write a short, natural and specific response to this Google Play review.

Rating:
{rating}/5

Review:
"{review_text}"

Requirements:

1. Reply in the SAME LANGUAGE as the user's review.

2. Carefully understand what the user actually said and respond
   specifically to their experience, complaint, suggestion or praise.

3. NEVER give a generic response such as:
   "Thanks for your feedback."
   "We'll address the issues you raised."
   "Thank you for your feedback. We will address your concerns."

4. The response must clearly show that you understood the actual
   content of the review.

5. If the review is positive:
   - thank the user naturally;
   - specifically mention the feature, experience or improvement
     they liked;
   - do NOT talk about "issues" or "problems" when the user
     did not report one.

6. If the user reports a bug or technical issue:
   - acknowledge the specific problem;
   - briefly apologize when appropriate;
   - say the team will investigate or improve it when appropriate.

7. If the review mentions login, connection, treadmill,
   device pairing, PitPat Band, workout tracking,
   achievements, milestones, subscription, payment,
   account, advertising, updates, reports, AI workouts,
   health data or another specific function,
   mention the relevant topic naturally.

8. If several problems are mentioned:
   acknowledge the main problem or problems rather than
   giving a vague response.

9. Do NOT invent troubleshooting steps.

10. Do NOT invent refunds, compensation, policies,
    product features or promises.

11. Do NOT claim an issue has already been fixed unless
    that is explicitly known.

12. Do NOT ask the user to change their rating.

13. Do NOT mention AI, automation or automated replies.

14. Keep the tone friendly, professional and human.

15. Avoid repetitive wording.

16. Maximum 320 characters.

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

            print("AI returned empty reply.")

            return None

        # Remove accidental quotation marks
        reply = (
            reply
            .strip('"')
            .strip("'")
            .strip()
        )

        # Final length protection
        if len(reply) > 320:
            reply = reply[:317].rstrip() + "..."

        return reply

    except Exception as e:

        print(f"AI error: {e}")

        return None


# ==================================================
# Get Google Play reviews
# ==================================================

def get_all_reviews():

    results = []

    try:

        request = service.reviews().list(
            packageName=PACKAGE_NAME,
            maxResults=100
        )

        while request is not None:

            response = request.execute()

            reviews = response.get(
                "reviews",
                []
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

                # Google can return both userComment
                # and developerComment inside comments.
                # Do not assume comments[0] is always userComment.
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

                # ======================================
                # CORE PROTECTION
                #
                # As long as Google currently has
                # a developer reply, NEVER touch it.
                #
                # It does not matter whether the reply
                # was created by AI or edited manually.
                # ======================================

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

            request = (
                service
                .reviews()
                .list_next(
                    previous_request=request,
                    previous_response=response
                )
            )

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
# Double-check one review before posting
# ==================================================

def has_reply_now(review_id):

    try:

        review = (
            service
            .reviews()
            .get(
                packageName=PACKAGE_NAME,
                reviewId=review_id
            )
            .execute()
        )

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

    except Exception as e:

        # IMPORTANT:
        # If we cannot safely check the current status,
        # do NOT post anything.
        print(
            f"Unable to re-check reply status "
            f"for {review_id}: {e}"
        )

        return None


# ==================================================
# Post Google Play reply
# ==================================================

def post_reply(
    review_id,
    reply_text
):

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
            f"Reply successful: "
            f"{review_id}"
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

print(
    "Getting Google Play reviews..."
)

reviews = get_all_reviews()

print(
    f"Reviews checked: "
    f"{len(reviews)}"
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
        f"Review: {review_text[:200]}"
    )

    # ==================================================
    # FIRST PROTECTION:
    # Existing developer reply = NEVER TOUCH IT
    # ==================================================

    if review[
        "has_developer_reply"
    ]:

        print(
            "SKIP: Developer reply already exists. "
            "It will NOT be modified."
        )

        skipped_count += 1

        continue

    # ==================================================
    # No reply -> generate targeted AI response
    # ==================================================

    print(
        "No existing reply. "
        "Generating targeted response..."
    )

    reply = ai_generate_reply(
        review_text,
        rating
    )

    # AI failure:
    # Do NOT use a generic fallback.
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
    # SECOND PROTECTION:
    #
    # Check Google AGAIN immediately before posting.
    #
    # If someone manually replied while AI was
    # generating the response, do not overwrite it.
    # ==================================================

    current_reply_status = (
        has_reply_now(review_id)
    )

    if current_reply_status is True:

        print(
            "SKIP: A developer reply appeared "
            "before posting. Do not overwrite."
        )

        skipped_count += 1

        continue

    if current_reply_status is None:

        print(
            "SKIP: Could not safely verify "
            "current reply status."
        )

        failed_count += 1

        continue

    # ==================================================
    # Still no reply -> safe to post
    # ==================================================

    if post_reply(
        review_id,
        reply
    ):

        success_count += 1

    else:

        failed_count += 1

    time.sleep(2)


# ==================================================
# Final report
# ==================================================

print(
    "\n=============================="
)

print(
    f"Completed: "
    f"{success_count} new replies, "
    f"{skipped_count} existing replies skipped, "
    f"{failed_count} failed."
)

send_report(
    success_count,
    skipped_count,
    failed_count
)
