import os
import json
import time
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build


# ==================================================
# Configuration
# ==================================================

SERVICE_ACCOUNT_JSON = os.environ.get("SERVICE_ACCOUNT_JSON")
PACKAGE_NAME = os.environ.get("PACKAGE_NAME")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

# Wait between different reviews.
REQUEST_INTERVAL = 4

# Retry the same review when Groq returns 429 / temporary errors.
MAX_AI_RETRIES = 5


print("=== Google Play Auto Reply ===")
print("Rule: Existing developer replies are NEVER modified.")
print(f"AI model: {GROQ_MODEL}")
print(
    f"Rate-limit protection: "
    f"{MAX_AI_RETRIES} retries + adaptive waiting."
)


# ==================================================
# Check environment variables
# ==================================================

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

    try:

        choices = result.get("choices", [])

        if not choices:
            print("AI response has no choices.")
            return None

        choice = choices[0]

        message = choice.get("message", {})

        content = message.get("content")

        # Normal response
        if isinstance(content, str):

            content = content.strip()

            if content:
                return content

        # Structured content compatibility
        if isinstance(content, list):

            parts = []

            for item in content:

                if isinstance(item, str):

                    if item.strip():
                        parts.append(item.strip())

                elif isinstance(item, dict):

                    text_value = item.get("text")

                    if isinstance(text_value, str):

                        if text_value.strip():
                            parts.append(
                                text_value.strip()
                            )

                    elif isinstance(text_value, dict):

                        value = text_value.get("value")

                        if (
                            isinstance(value, str)
                            and value.strip()
                        ):
                            parts.append(
                                value.strip()
                            )

            if parts:
                return "\n".join(parts).strip()

        # Compatibility fallback
        choice_text = choice.get("text")

        if (
            isinstance(choice_text, str)
            and choice_text.strip()
        ):
            return choice_text.strip()

        return None

    except Exception as e:

        print(
            f"Failed to parse AI response: {e}"
        )

        return None


# ==================================================
# Clean AI reply
# ==================================================

def clean_reply(reply):

    if not reply:
        return None

    reply = (
        reply
        .strip()
        .strip('"')
        .strip("'")
        .strip()
    )

    prefixes = [
        "Final answer:",
        "Final reply:",
        "Response:",
        "Reply:"
    ]

    for prefix in prefixes:

        if reply.lower().startswith(
            prefix.lower()
        ):

            reply = (
                reply[len(prefix):]
                .strip()
            )

    if not reply:
        return None

    # Google Play limit protection
    if len(reply) > 320:

        reply = (
            reply[:317]
            .rstrip()
            + "..."
        )

    return reply


# ==================================================
# Determine retry wait time
# ==================================================

def get_retry_wait(response, attempt):

    retry_after = response.headers.get(
        "retry-after"
    )

    if retry_after:

        try:

            wait_seconds = float(
                retry_after
            )

            # Small safety buffer
            return max(
                2,
                wait_seconds + 2
            )

        except Exception:
            pass

    # Fallback exponential waiting:
    # 10 -> 20 -> 40 -> 60 -> 60
    fallback = min(
        60,
        10 * (2 ** (attempt - 1))
    )

    return fallback


# ==================================================
# Generate targeted AI reply
# ==================================================

def ai_generate_reply(
    review_text,
    rating
):

    headers = {
        "Authorization":
            f"Bearer {GROQ_API_KEY}",
        "Content-Type":
            "application/json"
    }

    prompt = f"""
You are the official customer support representative for PitPat.

Write ONE short public response to this Google Play review.

Star rating: {rating}/5

Review:
"{review_text}"

Rules:

1. Reply in the SAME LANGUAGE as the original review.

2. Read the review carefully and respond to what the user
   actually said.

3. The reply must mention the specific experience, feature,
   praise, complaint, or suggestion in the review.

4. NEVER use generic replies such as:
   "Thanks for your feedback."
   "We'll address the issues you raised."
   "Thank you for your feedback. We will address your concerns."

5. Positive review:
   thank the user naturally and specifically mention what
   they liked.

6. Negative review:
   acknowledge the specific problem and apologize naturally
   when appropriate.

7. If the review mentions audio cues, voice coaching,
   treadmill connection, device pairing, workout tracking,
   achievements, milestones, PitPat Band, health data,
   Apple Health, subscription, payment, ads, account,
   reports, AI workouts, social features or another
   specific function, respond to that exact topic.

8. Do NOT invent troubleshooting steps.

9. Do NOT invent refunds, compensation or policies.

10. Do NOT claim an issue has already been fixed unless
    that information is known.

11. Do NOT ask the user to change their rating.

12. Do NOT mention AI, automation or automated replies.

13. Friendly, professional and natural tone.

14. Avoid repetitive wording.

15. Maximum 320 characters.

Return ONLY the final public reply.
"""

    data = {
        "model": GROQ_MODEL,

        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],

        "temperature": 0.5,

        "max_completion_tokens": 350,

        # GPT-OSS:
        # short review replies do not need heavy reasoning.
        "reasoning_effort": "low",

        # Do not return reasoning content.
        "include_reasoning": False,

        "stream": False
    }

    for attempt in range(
        1,
        MAX_AI_RETRIES + 1
    ):

        print(
            f"AI request attempt "
            f"{attempt}/{MAX_AI_RETRIES}..."
        )

        try:

            response = requests.post(
                GROQ_URL,
                headers=headers,
                json=data,
                timeout=60
            )

        except requests.exceptions.Timeout:

            print(
                "AI request timed out."
            )

            if attempt < MAX_AI_RETRIES:

                wait_seconds = min(
                    60,
                    10 * attempt
                )

                print(
                    f"Waiting {wait_seconds}s "
                    f"before retry..."
                )

                time.sleep(
                    wait_seconds
                )

                continue

            return None

        except Exception as e:

            print(
                f"AI request error: {e}"
            )

            if attempt < MAX_AI_RETRIES:

                wait_seconds = min(
                    60,
                    10 * attempt
                )

                print(
                    f"Waiting {wait_seconds}s "
                    f"before retry..."
                )

                time.sleep(
                    wait_seconds
                )

                continue

            return None


        print(
            f"AI HTTP status: "
            f"{response.status_code}"
        )


        # ==================================================
        # SUCCESS
        # ==================================================

        if response.status_code == 200:

            try:

                result = response.json()

            except Exception as e:

                print(
                    f"AI returned invalid JSON: {e}"
                )

                return None


            reply = extract_ai_reply(
                result
            )

            reply = clean_reply(
                reply
            )


            if reply:

                print(
                    "AI reply generated successfully."
                )

                return reply


            print(
                "AI returned no usable final reply."
            )

            # Safe diagnostic
            try:

                safe_debug = json.dumps(
                    result,
                    ensure_ascii=False
                )

                print(
                    "AI response structure: "
                    + safe_debug[:2500]
                )

            except Exception:
                pass

            return None


        # ==================================================
        # RATE LIMIT
        # ==================================================

        if response.status_code == 429:

            wait_seconds = get_retry_wait(
                response,
                attempt
            )

            print(
                "Groq rate limit reached."
            )

            if attempt < MAX_AI_RETRIES:

                print(
                    f"Waiting {wait_seconds:.1f}s "
                    f"before automatic retry..."
                )

                time.sleep(
                    wait_seconds
                )

                continue

            print(
                "Maximum rate-limit retries reached."
            )

            return None


        # ==================================================
        # TEMPORARY SERVER ERRORS
        # ==================================================

        if response.status_code in [
            500,
            502,
            503,
            504
        ]:

            if attempt < MAX_AI_RETRIES:

                wait_seconds = min(
                    60,
                    10 * attempt
                )

                print(
                    f"Temporary Groq error. "
                    f"Waiting {wait_seconds}s "
                    f"before retry..."
                )

                time.sleep(
                    wait_seconds
                )

                continue

            return None


        # ==================================================
        # NON-RETRYABLE ERROR
        # ==================================================

        print(
            f"AI request failed: "
            f"HTTP {response.status_code}"
        )

        print(
            f"AI error body: "
            f"{response.text[:1000]}"
        )

        return None


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
                        comment[
                            "userComment"
                        ]
                    )

                if "developerComment" in comment:

                    developer_comment = (
                        comment[
                            "developerComment"
                        ]
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
                "id":
                    review_id,

                "text":
                    review_text,

                "rating":
                    star_rating,

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
# Re-check reply before posting
# ==================================================

def has_reply_now(
    review_id
):

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

            if (
                review.get("reviewId")
                != review_id
            ):
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


        # If the review cannot be verified,
        # fail safely.
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
                packageName=
                    PACKAGE_NAME,

                reviewId=
                    review_id,

                body={
                    "replyText":
                        reply_text
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
        f"Review: "
        f"{review_text[:250]}"
    )


    # ==================================================
    # Existing reply -> NEVER TOUCH
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
    # No reply -> generate
    # ==================================================

    print(
        "No existing reply. "
        "Generating targeted response..."
    )


    reply = ai_generate_reply(
        review_text,
        rating
    )


    # AI ultimately failed:
    # leave review unanswered for next run.
    if not reply:

        print(
            "AI generation failed after retries. "
            "No reply posted."
        )

        failed_count += 1

        # Avoid immediately hammering API again.
        print(
            f"Waiting {REQUEST_INTERVAL}s "
            f"before next review..."
        )

        time.sleep(
            REQUEST_INTERVAL
        )

        continue


    print(
        f"Generated reply "
        f"({len(reply)} chars): "
        f"{reply}"
    )


    # ==================================================
    # Re-check immediately before posting
    # ==================================================

    current_reply_status = (
        has_reply_now(
            review_id
        )
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
    # Still unanswered -> post
    # ==================================================

    if post_reply(
        review_id,
        reply
    ):

        success_count += 1

    else:

        failed_count += 1


    # ==================================================
    # Slow down before next AI request
    # ==================================================

    print(
        f"Waiting {REQUEST_INTERVAL}s "
        f"before next review..."
    )

    time.sleep(
        REQUEST_INTERVAL
    )


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
