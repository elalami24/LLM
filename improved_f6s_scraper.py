#!/usr/bin/env python3
"""
Scraper F6S utilisant les cookies d'authentification existants
Cette approche contourne la détection en utilisant une session déjà authentifiée
"""

import json
import time
import logging
import requests
import re
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Configuration
COOKIE_FILE = "cookies.json"
OUTPUT_DIR = Path("scraped_data")
LOG_FILE = "scraper.log"

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def create_output_directory():
    """Crée le dossier de sortie"""
    OUTPUT_DIR.mkdir(exist_ok=True)

def load_cookies():
    """Charge les cookies depuis le fichier JSON"""
    try:
        with open(COOKIE_FILE, "r") as f:
            cookies = json.load(f)
        
        if isinstance(cookies, dict):
            cookies = [cookies]
        
        logger.info(f"Cookies chargés: {len(cookies)} cookie(s)")
        return cookies
    except Exception as e:
        logger.error(f"Erreur lors du chargement des cookies: {e}")
        return []

def cookies_to_requests_format(playwright_cookies):
    """Convertit les cookies Playwright au format requests"""
    session_cookies = {}
    for cookie in playwright_cookies:
        session_cookies[cookie['name']] = cookie['value']
    return session_cookies

def scrape_with_requests():
    """Tentative de scraping avec requests (plus discret)"""
    logger.info("Tentative de scraping avec requests...")
    
    try:
        # Charger les cookies
        playwright_cookies = load_cookies()
        if not playwright_cookies:
            return None
        
        # Convertir au format requests
        cookies = cookies_to_requests_format(playwright_cookies)
        
        # Headers réalistes
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Cache-Control': 'max-age=0'
        }
        
        # Session avec cookies
        session = requests.Session()
        session.cookies.update(cookies)
        session.headers.update(headers)
        
        # Essayer différentes URLs
        urls_to_try = [
            "https://www.f6s.com/programs",
            "https://www.f6s.com/programs?page=1",
            "https://www.f6s.com/programs/all",
            "https://www.f6s.com/api/programs",  # Essayer l'API
        ]
        
        for url in urls_to_try:
            logger.info(f"Tentative avec: {url}")
            
            try:
                response = session.get(url, timeout=30)
                logger.info(f"Status code: {response.status_code}")
                
                if response.status_code == 200:
                    content = response.text
                    
                    # Vérifier si c'est du contenu valide
                    if len(content) > 10000 and "checking your browser" not in content.lower():
                        logger.info(f"Contenu valide obtenu de {url}")
                        return content, url
                    else:
                        logger.warning(f"Contenu suspect de {url} (taille: {len(content)})")
                
                time.sleep(2)  # Délai entre les tentatives
                
            except Exception as e:
                logger.warning(f"Erreur avec {url}: {e}")
        
        return None
        
    except Exception as e:
        logger.error(f"Erreur avec requests: {e}")
        return None

def scrape_with_playwright_stealth():
    """Scraping avec Playwright en mode ultra-discret"""
    logger.info("Tentative de scraping avec Playwright stealth...")
    
    try:
        cookies = load_cookies()
        if not cookies:
            return None
        
        with sync_playwright() as p:
            # Browser le plus discret possible
            browser = p.chromium.launch(
                headless=True,  # Mode invisible
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    "--mute-audio",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                ]
            )
            
            # Context avec cookies
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                extra_http_headers={
                    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"
                }
            )
            
            # Ajouter les cookies
            context.add_cookies(cookies)
            
            # Scripts anti-détection minimalistes
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                delete window.playwright;
                delete window.__playwright;
            """)
            
            page = context.new_page()
            
            # Bloquer les ressources non-essentielles pour accélérer
            page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2}", lambda route: route.abort())
            
            # URLs à essayer
            urls_to_try = [
                "https://www.f6s.com/programs",
                "https://f6s.com/programs",
                "https://www.f6s.com/programs?sort=latest",
                "https://www.f6s.com/opportunities"
            ]
            
            for url in urls_to_try:
                try:
                    logger.info(f"Tentative Playwright avec: {url}")
                    
                    # Navigation avec timeout court
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    
                    # Attendre un peu
                    time.sleep(3)
                    
                    # Vérifier le contenu
                    content = page.content()
                    title = page.title()
                    
                    logger.info(f"Titre: {title}")
                    logger.info(f"Taille du contenu: {len(content)}")
                    
                    # Vérifier si c'est du bon contenu
                    if (len(content) > 10000 and 
                        "checking your browser" not in content.lower() and
                        "programs" in title.lower()):
                        
                        logger.info(f"Contenu valide obtenu avec Playwright de {url}")
                        browser.close()
                        return content, url
                    
                    time.sleep(2)
                    
                except Exception as e:
                    logger.warning(f"Erreur Playwright avec {url}: {e}")
            
            browser.close()
            
    except Exception as e:
        logger.error(f"Erreur Playwright: {e}")
    
    return None

def extract_programs_from_html(html_content, source_url):
    """Extrait les programmes depuis le HTML"""
    logger.info("Extraction des programmes depuis le HTML...")
    
    soup = BeautifulSoup(html_content, 'html.parser')
    programs = []
    
    # Sauvegarder le HTML brut
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    html_file = OUTPUT_DIR / f"f6s_raw_{timestamp}.html"
    
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    logger.info(f"HTML sauvegardé: {html_file}")
    
    # Chercher des patterns JSON dans le HTML (données AJAX)
    json_patterns = [
        r'window\.__INITIAL_STATE__\s*=\s*({.+?});',
        r'window\.__APOLLO_STATE__\s*=\s*({.+?});',
        r'window\.APP_DATA\s*=\s*({.+?});',
        r'"programs"\s*:\s*(\[.+?\])',
        r'"opportunities"\s*:\s*(\[.+?\])'
    ]
    
    for pattern in json_patterns:
        matches = re.findall(pattern, html_content, re.DOTALL)
        for match in matches:
            try:
                data = json.loads(match)
                logger.info(f"JSON data trouvée avec pattern: {pattern[:20]}...")
                
                # Chercher des programmes dans les données JSON
                programs_found = extract_programs_from_json(data)
                if programs_found:
                    programs.extend(programs_found)
                    
            except json.JSONDecodeError:
                continue
    
    # Si pas de JSON, essayer l'extraction HTML classique
    if not programs:
        programs = extract_programs_from_dom(soup)
    
    # Créer le fichier de sortie
    output_data = {
        "timestamp": timestamp,
        "source_url": source_url,
        "extraction_method": "cookie_based",
        "total_programs": len(programs),
        "programs": programs
    }
    
    # Sauvegarder JSON
    json_file = OUTPUT_DIR / f"f6s_programs_{timestamp}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Données JSON sauvegardées: {json_file}")
    
    return programs

def extract_programs_from_json(data):
    """Extrait les programmes depuis des données JSON"""
    programs = []
    
    def search_programs_recursive(obj, path=""):
        """Recherche récursive de programmes dans l'objet JSON"""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.lower() in ['programs', 'opportunities', 'items', 'results']:
                    if isinstance(value, list):
                        logger.info(f"Programmes trouvés dans: {path}.{key}")
                        for item in value:
                            if isinstance(item, dict):
                                program = extract_program_from_json_item(item)
                                if program:
                                    programs.append(program)
                
                search_programs_recursive(value, f"{path}.{key}")
        
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                search_programs_recursive(item, f"{path}[{i}]")
    
    search_programs_recursive(data)
    return programs

def extract_program_from_json_item(item):
    """Extrait un programme depuis un item JSON"""
    if not isinstance(item, dict):
        return None
    
    program = {}
    
    # Mapping des champs communs
    field_mappings = {
        'title': ['title', 'name', 'program_name', 'opportunity_name'],
        'description': ['description', 'summary', 'details', 'about'],
        'organization': ['organization', 'company', 'organizer', 'brand'],
        'deadline': ['deadline', 'end_date', 'closing_date', 'due_date'],
        'location': ['location', 'city', 'country', 'region'],
        'funding': ['funding', 'amount', 'grant', 'prize'],
        'url': ['url', 'link', 'permalink', 'href'],
        'id': ['id', 'program_id', 'opportunity_id']
    }
    
    for field, possible_keys in field_mappings.items():
        for key in possible_keys:
            if key in item:
                program[field] = item[key]
                break
        
        if field not in program:
            program[field] = ""
    
    # Retourner seulement si on a au moins un titre
    return program if program.get('title') else None

def extract_programs_from_dom(soup):
    """Extraction depuis le DOM HTML"""
    programs = []
    
    # Sélecteurs à essayer
    selectors = [
        '[data-program-id]',
        '[data-opportunity-id]',
        '.program-card',
        '.opportunity-card',
        '.program-item',
        'article[class*="program"]',
        'div[class*="program"]',
        '.card[href*="program"]',
        '.opportunity',
        '.listing-item'
    ]
    
    for selector in selectors:
        elements = soup.select(selector)
        if elements:
            logger.info(f"Trouvé {len(elements)} éléments avec: {selector}")
            
            for element in elements:
                program = extract_program_from_element(element)
                if program:
                    programs.append(program)
            
            break  # Utiliser le premier sélecteur qui marche
    
    return programs

def extract_program_from_element(element):
    """Extrait un programme depuis un élément HTML"""
    program = {
        'title': '',
        'description': '',
        'organization': '',
        'deadline': '',
        'location': '',
        'funding': '',
        'url': ''
    }
    
    # Titre
    title_elem = element.select_one('h1, h2, h3, h4, .title, [class*="title"]')
    if title_elem:
        program['title'] = title_elem.get_text(strip=True)
    
    # Description
    desc_elem = element.select_one('.description, .summary, p')
    if desc_elem:
        program['description'] = desc_elem.get_text(strip=True)[:300]
    
    # URL
    link_elem = element.select_one('a[href]')
    if link_elem:
        href = link_elem.get('href', '')
        if href.startswith('/'):
            program['url'] = 'https://www.f6s.com' + href
        else:
            program['url'] = href
    
    return program if program['title'] else None

def main():
    """Fonction principale"""
    print("SCRAPER F6S AVEC COOKIES D'AUTHENTIFICATION")
    print("=" * 50)
    
    create_output_directory()
    
    # Essayer d'abord avec requests (plus discret)
    result = scrape_with_requests()
    
    # Si ça ne marche pas, essayer avec Playwright
    if not result:
        logger.info("Requests a échoué, essai avec Playwright...")
        result = scrape_with_playwright_stealth()
    
    if result:
        html_content, source_url = result
        logger.info(f"Contenu obtenu de: {source_url}")
        
        # Extraire les programmes
        programs = extract_programs_from_html(html_content, source_url)
        
        if programs:
            print(f"\n✅ Extraction réussie! {len(programs)} programmes trouvés")
            
            # Afficher quelques exemples
            print("\nExemples de programmes extraits:")
            for i, program in enumerate(programs[:3]):
                print(f"{i+1}. {program.get('title', 'Sans titre')}")
                if program.get('organization'):
                    print(f"   Organisation: {program['organization']}")
                if program.get('url'):
                    print(f"   URL: {program['url']}")
        else:
            print("\n⚠️ Aucun programme extrait - vérifiez le HTML sauvegardé")
    else:
        print("\n❌ Impossible d'obtenir le contenu de F6S")
        print("Vérifiez que vos cookies sont valides et non expirés")
    
    return result is not None

if __name__ == "__main__":
    main()