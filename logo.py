import asyncio
from playwright.async_api import async_playwright
from urllib.parse import urljoin

async def detect_logo(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url)
        await page.wait_for_load_state('networkidle')

        # Récupérer toutes les balises <img>
        img_elements = await page.query_selector_all("img")
        
        for img in img_elements:
            src = await img.get_attribute("src")
            alt = await img.get_attribute("alt")

            if (src and "logo" in src.lower()) or (alt and "logo" in alt.lower()):
                full_url = urljoin(url, src)
                print("Premier logo détecté :", full_url)
                await browser.close()
                return  # Sortir dès qu’un logo est trouvé

        await browser.close()
        print("Aucun logo détecté.")

url = "https://india-africa.org/"

# Lancer la fonction
asyncio.run(detect_logo(url))
