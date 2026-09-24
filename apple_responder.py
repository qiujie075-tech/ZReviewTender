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
print("Only reviews without a published response are processed.")
print(f"AI model: {GROQ_MODEL}")


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

    return jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers=headers
    )


def apple_headers():

    return {
        "Authorization": f"Bearer {create_apple_token()}",
        "Content-Type": "application/json"
    }


# ==================================================
# AI response extraction
# ==================================================

def extract_ai_reply(result):

    try:

        choices = result.get("choices", [])

        if not choices:
            return None

        choice = choices[0]

        message = choice.get(
            "message",
            {}
        )

        content = message.get(
            "content"
        )

        if isinstance(content, str):

            content = content.strip()

            if content:
                return content


        if isinstance(content, list):

            parts = []

            for item in content:

                if isinstance(item, str):

                    if item.strip():
                        parts.append(
                            item.strip()
                        )

                elif isinstance(item, dict):

                    text_value = item.get(
                        "text"
                    )

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

                return "\n".join(
                    parts
                ).strip()


        choice_text = choice.get(
            "text"
        )

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

    if len(reply) > 320:

        reply = (
            reply[:317]
            .rstrip()
            + "..."
        )

    return reply


# ==================================================
# Groq retry wait
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


    return min(
        60,
        10 * (2 ** (attempt - 1))
    )


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

3. The reply must respond specifically to the user's
   experience, praise, complaint or suggestion.

4. NEVER use generic responses such as:
   "Thanks for your feedback."
   "We'll address the issues you raised."
   "Thank you for your feedback. We will address your concerns."

5. For a positive review:
   thank the user naturally and mention the specific
   experience or feature they liked.

6. For a negative review:
   acknowledge the specific issue and apologize naturally
   when appropriate.

7. If the review mentions Apple Health, health data,
   steps, treadmill connection, device pairing,
   PitPat Band, workout tracking, audio cues,
   voice coaching, achievements, subscription,
   payment, advertising, login, reports,
   AI workouts, social features or another
   specific feature, respond to that exact topic.

8. Do NOT invent troubleshooting instructions.

9. Do NOT invent refunds, compensation or policies.

10. Do NOT claim something has already been fixed
    unless that information is known.

11. Do NOT ask the user to change their rating.

12. Do NOT mention AI, Groq, automation
    or automated replies.

13. Keep the tone friendly, professional and natural.

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
                    f"Temporary AI error. "
                    f"Waiting {wait_seconds}s "
                    f"before retry..."
                )

                time.sleep(
                    wait_seconds
                )

                continue

            return None


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
# Get ONLY Apple reviews without published responses
# ==================================================

def get_unanswered_reviews():

    url = (
        f"{APPLE_API_BASE}/apps/"
        f"{APP_ID}/customerReviews"
    )

    params = {
        "limit": 50,
        "sort": "-createdDate",

        # IMPORTANT:
        # Apple itself filters reviews that do NOT
        # currently have a published developer response.
        "exists[publishedResponse]": "false"
    }


    try:

        response = requests.get(
            url,
            headers=apple_headers(),
            params=params,
            timeout=30
        )


        print(
            f"Apple unanswered reviews HTTP status: "
            f"{response.status_code}"
        )


        if response.status_code != 200:

            print(
                "Failed to get unanswered reviews."
            )

            print(
                response.text[:1000]
            )

            return []


        result = response.json()

        reviews = result.get(
            "data",
            []
        )


        print(
            f"Apple API returned "
            f"{len(reviews)} reviews "
            f"without a published response."
        )


        return reviews


    except Exception as e:

        print(
            f"Failed to get Apple reviews: {e}"
        )

        return []


# ==================================================
# FINAL SAFETY CHECK
#
# Use Apple's relationship endpoint.
# We do NOT update existing responses.
# ==================================================

def has_response_now(
    review_id
):

    url = (
        f"{APPLE_API_BASE}/customerReviews/"
        f"{review_id}/relationships/response"
    )


    try:

        response = requests.get(
            url,
            headers=apple_headers(),
            timeout=30
        )


        print(
            f"Response safety check HTTP status: "
            f"{response.status_code}"
        )


        if response.status_code == 200:

            try:

                result = response.json()

            except Exception as e:

                print(
                    f"Unable to parse response relationship: {e}"
                )

                return None


            data = result.get(
                "data"
            )


            # No linked response
            if data is None:

                return False


            # Existing response linkage
            if isinstance(data, dict):

                response_id = data.get(
                    "id"
                )

                if response_id:

                    return True


            # Unexpected structure -> fail safely
            print(
                "Unexpected Apple response relationship structure."
            )

            return None


        # Review or relationship cannot be safely verified.
        if response.status_code == 404:

            print(
                "Safety check returned 404. "
                "Will NOT post automatically."
            )

            return None


        if response.status_code == 429:

            print(
                "Apple API rate limit during safety check."
            )

            return None


        print(
            f"Unexpected safety check status: "
            f"HTTP {response.status_code}"
        )

        print(
            response.text[:500]
        )

        return None


    except Exception as e:

        print(
            f"Safety check failed "
            f"for {review_id}: {e}"
        )

        return None


# ==================================================
# Post Apple reply
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


        print(
            f"Apple reply HTTP status: "
            f"{response.status_code}"
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
            f"{review_id}"
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
        "Apple App Store Auto Reply completed\n"
        f"New replies: {success}\n"
        f"Safety skips: {skipped}\n"
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
    "Getting unanswered Apple App Store reviews..."
)

reviews = get_unanswered_reviews()

print(
    f"Unanswered reviews checked: "
    f"{len(reviews)}"
)


success_count = 0
skipped_count = 0
failed_count = 0


for review in reviews:

    review_id = review.get(
        "id"
    )

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
        f"Review: {review_text[:250]}"
    )


    # ==================================================
    # First safety check
    # ==================================================

    existing_status = has_response_now(
        review_id
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
            "SKIP: Could not safely verify "
            "response status. "
            "No reply posted."
        )

        failed_count += 1

        continue


    # ==================================================
    # No response -> generate targeted AI reply
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
    # SECOND SAFETY CHECK
    #
    # Someone may have manually replied while
    # AI was generating.
    # ==================================================

    current_status = has_response_now(
        review_id
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
            "response status before posting. "
            "No reply posted."
        )

        failed_count += 1

        continue


    # ==================================================
    # Still unanswered -> POST
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
    f"{skipped_count} safety skips, "
    f"{failed_count} failed."
)


send_report(
    success_count,
    skipped_count,
    failed_count
)
