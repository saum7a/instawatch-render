from dataclasses import dataclass
from enum import Enum
import re


class Status(str, Enum):
    ACTIVE = "ACTIVE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


@dataclass
class CheckResult:
    status: Status
    confidence: str
    reason: str


def _count_signals(text: str, patterns):
    return sum(
        1 for pattern in patterns
        if re.search(pattern, text, re.IGNORECASE)
    )


def classify_response(
    status_code: int,
    final_url: str,
    body: str
) -> CheckResult:

    text = (body or "").lower()
    url = (final_url or "").lower()

    # =========================================================
    # 1. CLEAR UNAVAILABLE/BANNED SIGNALS
    # =========================================================

    unavailable_markers = [
        "page isn't available",
        "page isn’t available",
        "page isnt available",
        "page is not available",

        "this page isn't available",
        "this page isn’t available",
        "this page isnt available",
        "this page is not available",

        "sorry, this page isn't available",
        "sorry, this page isn’t available",
        "sorry, this page isnt available",

        "profile isn't available",
        "profile isn’t available",
        "profile isnt available",
        "profile is not available",

        "the link you followed may be broken",
        "the page may have been removed",
        "the link may be broken",
        "sorry, something went wrong",
    ]

    unavailable_hits = [
        marker
        for marker in unavailable_markers
        if marker in text
    ]

    if unavailable_hits:
        return CheckResult(
            Status.UNAVAILABLE,
            "HIGH",
            "Clear unavailable-page message"
        )

    # =========================================================
    # 2. HTTP 404
    # =========================================================

    if status_code == 404:
        return CheckResult(
            Status.UNAVAILABLE,
            "HIGH",
            "HTTP 404 — public profile not found"
        )

    # =========================================================
    # 3. STRONG PUBLIC PROFILE EVIDENCE
    #
    # Instagram currently returns a large HTML document that can
    # contain login/challenge text even for a perfectly accessible
    # public profile.
    #
    # Therefore login/challenge alone must NOT mean UNKNOWN.
    # =========================================================

    profile_patterns = [

        # Username/profile JSON
        r'"username"\s*:\s*"[^"]+"',

        # Profile name
        r'"full_name"\s*:\s*"[^"]+"',

        # Follower/following information
        r'"edge_followed_by"',
        r'"edge_follow"',
        r'"followers"',
        r'"following"',

        # Profile metadata
        r'"biography"\s*:',
        r'"profile_pic_url"',
        r'"profile_pic_url_hd"',

        # Instagram profile page metadata
        r'instagram.*photos.*videos',
        r'"is_verified"\s*:',
        r'"is_private"\s*:',

        # Common profile page structures
        r'"graphql"\s*:',
        r'"user"\s*:\s*\{',
    ]

    signal_count = _count_signals(
        text,
        profile_patterns
    )

    # Strong profile evidence.
    #
    # We intentionally require several independent signals rather
    # than one word such as "followers".
    if signal_count >= 3:

        return CheckResult(
            Status.ACTIVE,
            "HIGH",
            f"Strong public-profile evidence "
            f"({signal_count} signals)"
        )

    # =========================================================
    # 4. META / TITLE EVIDENCE
    # =========================================================

    meta_patterns = [

        r'<meta[^>]+property=["\']og:type["\'][^>]+content=["\']profile',

        r'<meta[^>]+property=["\']og:title["\']',

        r'<meta[^>]+property=["\']og:description["\']',

        r'<title>\s*instagram\s*\(@[^<]+\)',

        r'instagram\s*\(@[^)]+\)\s*•\s*instagram',
    ]

    meta_count = _count_signals(
        text,
        meta_patterns
    )

    if meta_count >= 2:

        return CheckResult(
            Status.ACTIVE,
            "HIGH",
            f"Public profile metadata detected "
            f"({meta_count} signals)"
        )

    # =========================================================
    # 5. PROFILE PAGE URL + CONTENT
    # =========================================================

    is_profile_url = bool(
        re.match(
            r"https?://(?:www\.)?instagram\.com/[^/?#]+/?$",
            url
        )
    )

    if is_profile_url and len(text) > 100_000:

        content_patterns = [
            r'instagram',
            r'followers',
            r'following',
            r'posts',
            r'profile',
        ]

        content_count = _count_signals(
            text,
            content_patterns
        )

        if content_count >= 4:

            return CheckResult(
                Status.ACTIVE,
                "MEDIUM",
                f"Large public profile page "
                f"with profile content ({content_count} signals)"
            )

    # =========================================================
    # 6. LOGIN / CHALLENGE / RATE LIMIT
    #
    # These are ambiguous because Instagram can include them in
    # normal public-page responses.
    # =========================================================

    ambiguous_markers = [
        "/accounts/login",
        "login to instagram",
        "log in to instagram",

        "challenge_required",
        "challenge required",

        "checkpoint_required",
        "checkpoint required",

        "please wait a few minutes",
        "temporarily blocked",
        "rate limit",
        "try again later",
    ]

    ambiguous_hits = [
        marker
        for marker in ambiguous_markers
        if marker in text or marker in url
    ]

    if ambiguous_hits:

        return CheckResult(
            Status.UNKNOWN,
            "LOW",
            "Login/challenge/rate-limit signal "
            "without reliable profile evidence"
        )

    # =========================================================
    # 7. OTHER HTTP FAILURES
    # =========================================================

    if status_code in (
        401,
        403,
        429,
        500,
        502,
        503,
        504,
    ):

        return CheckResult(
            Status.UNKNOWN,
            "LOW",
            f"HTTP {status_code}"
        )

    # =========================================================
    # 8. HTTP 200 BUT NOTHING RELIABLE
    # =========================================================

    if status_code == 200:

        return CheckResult(
            Status.UNKNOWN,
            "LOW",
            "HTTP 200 but no reliable profile evidence"
        )

    # =========================================================
    # 9. EVERYTHING ELSE
    # =========================================================

    return CheckResult(
        Status.UNKNOWN,
        "LOW",
        f"HTTP {status_code}"
    )