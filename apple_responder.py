import os
import time
import json
import requests
import jwt
from datetime import datetime, timedelta, timezone


# ==================================================
# Configuration
# ==================================================

APP_ID = "1598065258"

APPLE_PRIVATE_KEY = os.environ.get("APPLE_PRIVATE_KEY")
APPLE_KEY_ID = os.environ.get("APPLE_KEY_ID")
APPLE_ISSUER_ID = os.environ.get("APPLE_ISSUER_ID")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

APPLE_API_BASE = "https://api.appstoreconnect.apple.com/v1"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

GROQ_MODEL = "openai/gpt-oss-20b"

REQUEST_INTERVAL = 4
MAX_AI_RETRIES = 5


print("=== Apple App Store Auto Reply ===")
print("Rule: Existing developer responses are NEVER modified.")
print(f"AI model: {GROQ_MODEL}")
print(
    f"Rate-limit protection: "
    f"{MAX_AI_RETRIES} retries + adaptive waiting."
)


# ==================================================
# Check environment variables
# ==================================================

required_envs = {
    "APPLE_PRIVATE_KEY": APPLE_PRIVATE_KEY,
    "APPLE_KEY_ID": APPLE_KEY_ID,
    "APPLE_ISSUER_ID": APPLE_ISSUER_ID,
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
# Apple JWT
# ==================================================

def create_apple_token():

    now = datetime.now(timezone.utc)

    payload = {
        "iss": APPLE_ISSUER_ID,
        "iat": int(now.timestamp()),
        "exp": int(
            (
                now + timedelta(minutes=20)
            ).timestamp()
        ),
        "aud": "appstoreconnect-v1"
    }

    headers = {
        "kid": APPLE_KEY_ID,
        "typ": "JWT"
    }

    private_key = APPLE_PRIVATE_KEY.replace(
        "\\n",
        "\n"
    )

    token = jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers=headers
    )

    return token


def apple_headers():

    return {
        "Authorization":
            f"Bearer {create_apple_token()}",
        "Content-Type":
            "application/json"
    }


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

        if isinstance(content, str):

            content = content.strip()

            if content:
                return content


        if isinstance(content, list):

            parts = []

            for item in content:

                if isinstance(item, str):

                    if item.strip():
                        parts.append(item.strip())

                elif isinstance(item, dict):

                    text_value = item.get("text")

                    if isinstance(
                        text_value,
                        str
                    ):

                        if text_value.strip():
                            parts.append(
                                text_value.strip()
                            )

                    elif isinstance(
                        text_value,
                        dict
                    ):

                        value = text_value.get(
                            "value"
                        )

                        if (
                            isinstance(value, str)
                            and value.strip()
                        ):

                            parts.append(
                                value.strip()
                            )

            if parts:
                return "\n".join(parts).strip()


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
# Clean reply
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

    # Keep Apple replies concise.
    if len(reply) > 320:

        reply = (
            reply[:317]
            .rstrip()
            + "..."
        )

    return reply


# ==================================================
# Groq retry waiting
# ==================================================

def get_retry_wait(
    response,
    attempt
):

    retry_after = response.headers.get(
        "retry-after"
    )

    if retry_after:

        try:

            wait_seconds = float(
                retry_after
            )

            return max(
                2,
                wait_seconds + 2
            )

        except Exception:
            pass


    fallback = min(
        60,
        10 * (2 ** (attempt - 1))
    )

    return fallback


# ==================================================
# AI targeted reply
# ==================================================

def ai_generate_reply(
    review_text,
    rating,
    title=""
):

    headers = {
        "Authorization":
            f"Bearer {GROQ_API_KEY}",
        "Content-Type":
            "application/json"
    }


    prompt = f"""
You are the official customer support representative for PitPat.

Write ONE short public response to this Apple App Store review.

Star rating: {rating}/5

Review title:
"{title}"

Review:
"{review_text}"

Rules:

1. Reply in the SAME LANGUAGE as the original review.

2. Carefully understand what the user actually said.

3. The reply must respond to the specific feature,
   experience, praise, complaint or suggestion.

4. NEVER use generic replies such as:
   "Thanks for your feedback."
   "We'll address the issues you raised."
   "Thank you for your feedback. We will address your concerns."

5. Positive review:
   - thank the user naturally;
   - specifically mention what they liked;
   - do not mention problems if they reported none.

6. Negative review:
   - acknowledge the specific problem;
   - apologize naturally when appropriate;
   - mention the actual area they had trouble with.

7. If the review mentions:
   - Apple Health
   - Health data
   - steps
   - activity data
   - treadmill
   - device connection
   - device pairing
   - PitPat Band
   - workout tracking
   - audio cues
   - voice coaching
   - achievements
   - milestones
   - subscription
   - payment
   - ads
   - account/login
   - reports
   - AI workouts
   - social features
   - another specific feature

   respond to that exact topic naturally.

8. Do NOT invent troubleshooting instructions.

9. Do NOT invent refunds, compensation or policies.

10. Do NOT claim something has already been fixed
    unless that information is known.

11. Do NOT ask the user to change their rating.

12. Do NOT mention AI, automation, Groq
    or automated replies.

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

        "reasoning_effort": "low",

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

            print("AI request timed out.")

            if attempt < MAX_AI_RETRIES:

                wait_seconds = min(
                    60,
                    10 * attempt
                )

                print(
                    f"Waiting {wait_seconds}s "
                    f"before retry..."
                )

                time.sleep(wait_seconds)

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

                time.sleep(wait_seconds)

                continue

            return None


        print(
            f"AI HTTP status: "
            f"{response.status_code}"
        )


        # SUCCESS
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


        # RATE LIMIT
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


        # TEMPORARY ERRORS
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


        # OTHER ERROR
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
# Get Apple reviews
# ==================================================

def get_reviews():

    url = (
        f"{APPLE_API_BASE}/apps/"
        f"{APP_ID}/customerReviews"
    )

    params = {
        "limit": 50,
        "sort": "-createdDate"
    }

    try:

        response = requests.get(
            url,
            headers=apple_headers(),
            params=params,
            timeout=30
        )

        print(
            f"Apple reviews HTTP status: "
            f"{response.status_code}"
        )

        if response.status_code != 200:

            print(
                f"Failed to get Apple reviews: "
                f"{response.text[:1000]}"
            )

            return []


        result = response.json()

        reviews = result.get(
            "data",
            []
        )

        print(
            f"Apple API returned "
            f"{len(reviews)} reviews."
        )

        return reviews


    except Exception as e:

        print(
            f"Failed to get Apple reviews: {e}"
        )

        return []


# ==================================================
# Check whether Apple review already has response
# ==================================================

def check_existing_response(
    review_id
):

    url = (
        f"{APPLE_API_BASE}/customerReviews/"
        f"{review_id}/response"
    )

    try:

        response = requests.get(
            url,
            headers=apple_headers(),
            timeout=30
        )


        # Existing developer response
        if response.status_code == 200:

            try:

                result = response.json()

                data = result.get("data")

                if data:
                    return True

            except Exception:
                pass

            # 200 but unable to safely determine state
            return None


        # No response exists
        if response.status_code == 404:

            return False


        print(
            f"Unexpected Apple response check "
            f"status for {review_id}: "
            f"HTTP {response.status_code}"
        )

        print(
            response.text[:500]
        )

        # Fail safely
        return None


    except Exception as e:

        print(
            f"Failed to check existing response "
            f"for {review_id}: {e}"
        )

        return None


# ==================================================
# Post Apple response
# ==================================================

def post_apple_reply(
    review_id,
    reply_text
):

    url = (
        f"{APPLE_API_BASE}/"
        f"customerReviewResponses"
    )


    payload = {
        "data": {
            "type":
                "customerReviewResponses",

            "attributes": {
                "responseBody":
                    reply_text
            },

            "relationships": {
                "review": {
                    "data": {
                        "type":
                            "customerReviews",

                        "id":
                            review_id
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
            timeout=30
        )


        if response.status_code in [
            200,
            201
        ]:

            print(
                f"Reply successful: "
                f"{review_id}"
            )

            return True


        print(
            f"Reply failed: "
            f"{review_id} - "
            f"HTTP {response.status_code}"
        )

        print(
            response.text[:1000]
        )

        return False


    except Exception as e:

        print(
            f"Reply failed: "
            f"{review_id} - {e}"
        )

        return False


# ==================================================
# Webhook
# ==================================================

def send_report(
    success,
    skipped,
    failed
):

    if not WEBHOOK_URL:
        return


    content = (
        "Apple App Store Auto Reply completed\n"
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
    "Getting Apple App Store reviews..."
)

reviews = get_reviews()

print(
    f"Reviews checked: "
    f"{len(reviews)}"
)


success_count = 0
skipped_count = 0
failed_count = 0


for review in reviews:

    review_id = review.get("id")

    attributes = review.get(
        "attributes",
        {}
    )

    rating = attributes.get(
        "rating",
        0
    )

    title = (
        attributes
        .get("title", "")
        .strip()
    )

    review_text = (
        attributes
        .get("body", "")
        .strip()
    )


    if not review_id:
        continue


    if not review_text:
        continue


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
        f"Title: {title[:150]}"
    )

    print(
        f"Review: "
        f"{review_text[:250]}"
    )


    # ==================================================
    # Check existing developer response
    # ==================================================

    existing_status = (
        check_existing_response(
            review_id
        )
    )


    if existing_status is True:

        print(
            "SKIP: Developer response already exists. "
            "It will NOT be modified."
        )

        skipped_count += 1

        continue


    if existing_status is None:

        print(
            "SKIP: Could not safely determine "
            "whether a response exists. "
            "No reply posted."
        )

        failed_count += 1

        continue


    # ==================================================
    # No response -> AI
    # ==================================================

    print(
        "No existing response. "
        "Generating targeted response..."
    )


    reply = ai_generate_reply(
        review_text,
        rating,
        title
    )


    if not reply:

        print(
            "AI generation failed after retries. "
            "No reply posted."
        )

        failed_count += 1

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
    # CRITICAL:
    # Check again immediately before posting.
    #
    # If you manually replied while AI was generating,
    # automation MUST NOT overwrite it.
    # ==================================================

    current_status = (
        check_existing_response(
            review_id
        )
    )


    if current_status is True:

        print(
            "SKIP: A developer response appeared "
            "before posting. "
            "It will NOT be overwritten."
        )

        skipped_count += 1

        continue


    if current_status is None:

        print(
            "SKIP: Could not safely verify "
            "current response status. "
            "No reply posted."
        )

        failed_count += 1

        continue


    # ==================================================
    # Still unanswered -> post
    # ==================================================

    if post_apple_reply(
        review_id,
        reply
    ):

        success_count += 1

    else:

        failed_count += 1


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
