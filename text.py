import asyncio
import re
import urllib.parse

import httpx


async def test_search_undraw(query: str, color_hex: str = "6c63ff"):
    print(f"🔍 Searching unDraw for: '{query}' with custom color #{color_hex}...\n")

    # unDraw's undocumented search endpoint
    search_url = f"https://undraw.co/api/search?q={urllib.parse.quote(query)}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(search_url)

            # Since this is an undocumented API, we handle potential changes gracefully
            if response.status_code != 200:
                print(
                    f"❌ API Error: unDraw returned status code {response.status_code}."
                )
                print(
                    "They might have changed their internal search API or blocked scraping."
                )
                return

            data = response.json()

            # Check if the search returned any matching illustrations
            if not data.get("hasMore") and not data.get("illusts"):
                print(f"⚠️ No illustrations found for '{query}'. Try another keyword.")
                return

            # Grab the first result
            first_result = data["illusts"][0]
            image_url = first_result["image"]
            print(f"✅ Found illustration: {first_result.get('title', 'Untitled')}")
            print(f"🔗 Original Image URL: {image_url}\n")

            # Fetch the raw SVG code
            print("⏳ Fetching and recoloring SVG...")
            svg_response = await client.get(image_url)
            svg_response.raise_for_status()
            raw_svg = svg_response.text

            # Dynamically replace unDraw's default purple (#6c63ff) with our requested color
            formatted_hex = f"#{color_hex.lstrip('#')}"
            customized_svg = re.sub(
                r"#6c63ff", formatted_hex, raw_svg, flags=re.IGNORECASE
            )

            print("🎨 Here is the customized SVG snippet (first 300 characters):")
            print("-" * 50)
            print(f"{customized_svg[:300]}...\n</svg>")
            print("-" * 50)

        except Exception as e:
            print(f"❌ Error during execution: {e}")


if __name__ == "__main__":
    # We are testing with the keyword "server" and a custom teal color
    asyncio.run(test_search_undraw(query="server", color_hex="00ADB5"))
