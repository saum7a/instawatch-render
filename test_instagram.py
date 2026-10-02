from playwright.sync_api import sync_playwright


USERNAME = "instagram"


def main():

    url = f"https://www.instagram.com/{USERNAME}/"

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            viewport={
                "width": 1280,
                "height": 900
            },
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/151.0 Safari/537.36"
            )
        )

        try:

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000
            )

            # Give Instagram a moment to render
            page.wait_for_timeout(3000)

            title = page.title()

            current_url = page.url

            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=10000
            )

            print(
                "USERNAME:",
                USERNAME
            )

            print(
                "TITLE:",
                title
            )

            print(
                "URL:",
                current_url
            )

            print(
                "TEXT LENGTH:",
                len(body_text)
            )

            print()
            print("FIRST 1000 CHARACTERS:")
            print(
                body_text[:1000]
            )

            print()
            print("=" * 50)
            print("BROWSER CLASSIFICATION")
            print("=" * 50)

            lower_title = title.lower()
            lower_text = body_text.lower()

            # ---------------------------------------------
            # Unavailable signals
            # ---------------------------------------------

            unavailable_markers = [
                "page isn't available",
                "page isn’t available",
                "page isnt available",
                "this page isn't available",
                "this page isn’t available",
                "this page isnt available",
                "sorry, this page isn't available",
                "sorry, this page isn’t available",
                "the link you followed may be broken",
                "profile isn't available",
                "profile isn’t available",
            ]

            unavailable_found = [
                x
                for x in unavailable_markers
                if x in lower_text
            ]

            # ---------------------------------------------
            # Active profile signals
            # ---------------------------------------------

            active_signals = []

            if "instagram photos and videos" in lower_title:
                active_signals.append(
                    "Instagram profile title"
                )

            if "followers" in lower_text:
                active_signals.append(
                    "followers"
                )

            if "following" in lower_text:
                active_signals.append(
                    "following"
                )

            if "posts" in lower_text:
                active_signals.append(
                    "posts"
                )

            if USERNAME.lower() in lower_text:
                active_signals.append(
                    "username"
                )

            # ---------------------------------------------
            # Result
            # ---------------------------------------------

            print()

            if unavailable_found:

                print(
                    "STATUS: UNAVAILABLE"
                )

                print(
                    "CONFIDENCE: HIGH"
                )

                print(
                    "REASON: "
                    "Clear unavailable-page signal"
                )

            elif (
                len(active_signals) >= 2
                and len(body_text) > 100
            ):

                print(
                    "STATUS: ACTIVE"
                )

                print(
                    "CONFIDENCE: HIGH"
                )

                print(
                    "REASON: "
                    "Browser-rendered public profile detected"
                )

                print(
                    "SIGNALS:",
                    ", ".join(active_signals)
                )

            elif (
                title.strip() == "Instagram"
                and len(body_text.strip()) == 0
            ):

                print(
                    "STATUS: UNAVAILABLE"
                )

                print(
                    "CONFIDENCE: HIGH"
                )

                print(
                    "REASON: "
                    "Instagram returned empty profile page"
                )

            else:

                print(
                    "STATUS: UNKNOWN"
                )

                print(
                    "CONFIDENCE: LOW"
                )

                print(
                    "REASON: "
                    "Browser could not establish reliable "
                    "profile status"
                )

        finally:

            browser.close()


if __name__ == "__main__":
    main()