import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright
import json
import re
from datetime import datetime
import google.generativeai as genai
from urllib.parse import urljoin, urlparse
import time
import logging
import os
from dotenv import load_dotenv
import base64
import asyncio

# =====================================
# CONFIGURATION GLOBALE
# =====================================

# Charger les variables d'environnement
load_dotenv('config.env')

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DisruptAfricaScraper:
    """
    Scraper complet pour DisruptAfrica avec extraction avancée de logos
    et enrichissement via SerpAPI
    """
    
    def __init__(self, gemini_api_key=None, serpapi_key=None):
        """Initialise le scraper avec les clés API Gemini et SerpAPI"""
        self.base_urls = [
            "https://disruptafrica.com/category/events/",
            "https://disruptafrica.com/category/hubs/"
        ]
        
        # Configuration des composants
        self._setup_session()
        self._setup_gemini(gemini_api_key)
        self._setup_serpapi(serpapi_key)
        self._setup_llm_prompt()

   
    # SECTION 1: CONFIGURATION INITIALE
   

    def _setup_session(self):
        """Configure la session HTTP avec retry et headers"""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.session.mount('http://', requests.adapters.HTTPAdapter(max_retries=3))
        self.session.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))

    def _setup_gemini(self, api_key):
        """Configure Gemini AI pour l'analyse de contenu"""
        api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("Clé API Gemini non trouvée. Vérifiez votre fichier config.env")
        
        genai.configure(api_key=api_key)
        
        try:
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            logger.info("✓ Configuration Gemini AI réussie avec gemini-1.5-flash")
        except Exception as e:
            try:
                self.model = genai.GenerativeModel('gemini-1.5-pro')
                logger.info("✓ Configuration Gemini AI réussie avec gemini-1.5-pro")
            except Exception as e2:
                logger.error(f"Erreur de configuration Gemini: {e}")
                raise ValueError("Impossible de configurer Gemini AI")

    def _setup_serpapi(self, api_key):
        """Configure SerpAPI pour l'enrichissement des données"""
        self.serpapi_key = api_key or os.getenv('SERPAPI_KEY')
        if self.serpapi_key:
            logger.info("✓ Clé API SerpAPI configurée")
        else:
            logger.warning("⚠️ Clé API SerpAPI non trouvée. Ajoutez SERPAPI_KEY dans config.env")

    def _setup_llm_prompt(self):
        """Configure le prompt pour l'extraction LLM des métadonnées"""
        self.llm_prompt = """
        Analysez le contenu suivant et extrayez les informations demandées.
        
        Contenu: {content}
        Titre: {title}
        Date de publication: {published_date}
        
        Veuillez fournir UNIQUEMENT un JSON valide avec ces clés :
        - meta_title: Titre optimisé SEO (max 100 caractères)
        - Meta Description: Based on the title and subtitle, create an SEO-optimized meta description, no longer than 130 characters.
        - slug: URL slug (minuscules, tirets)
        - regions: Liste des régions (choisir parmi: ["Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi", "Cabo Verde", "Cameroon", "Central African Republic", "Chad", "Comoros", "Congo", "Côte d'Ivoire", "DR Congo", "Djibouti", "Egypt", "Equatorial Guinea", "Eritrea", "Eswatini", "Ethiopia", "Gabon", "Guinea", "Guinea-Bissau", "Kenya", "Lesotho", "Liberia", "Libya", "Madagascar", "Malawi", "Mali", "Mauritania", "Mauritius", "Morocco", "Mozambique", "Namibia", "Niger", "Nigeria", "Rwanda", "Sao Tome & Principe", "Senegal", "Seychelles", "Sierra Leone", "Somalia", "South Africa", "South Sudan", "Sudan", "Tanzania", "Togo", "Tunisia", "Uganda", "Zambia", "Zimbabwe"])
        - sectors: Liste des secteurs (choisir parmi: ["Regulatory Tech", "Spatial Computing", "AgriTech", "Agribusiness", "Artificial Intelligence", "Banking", "Blockchain", "Business Process Outsourcing (BPO)", "CleanTech", "Creative", "Cryptocurrencies", "Cybersecurity & Digital ID", "Data Aggregation", "Debt Management", "DeepTech", "Design & Applied Arts", "Digital & Interactive", "E-commerce and Retail", "Economic Development", "EdTech", "Energy", "Environmental Social Governance (ESG)", "FinTech", "Gaming", "HealthTech", "InsurTech", "Logistics", "ManuTech", "Manufacturing", "Media & Communication", "Mobility and Transportation", "Performing & Visual Arts", "Sector Agnostic", "Sport Management", "Sustainability", "Technology", "Tourism Innovation", "Transformative Digital Technologies", "Wearables"])
        - stages: Liste des étapes (choisir parmi: ["Not Applicable", "Pre-Series A", "Pre-seed", "Seed", "Series A", "Series B", "Series C", "Series D", "Series E", "Series F", "Stage Agnostic"])
        - categories: Liste des catégories (choisir parmi: ["Accelerator", "Bootcamp", "Competition", "Conference", "Event", "Funding Opportunity", "Hackathon", "Incubator", "Other", "Summit"])
        - draft_summary: Please craft a fully structured, rephrased article from the provided information in bullet-point format. Begin with an introduction, continue with a detailed body under clear headings, and finish with a compelling closing statement. The piece must remain neutral—treat it as a media listing that simply highlights incubator and accelerator programs and their application details, without suggesting these are our own initiatives or that we accept applications.
        - main_image_alt: Texte alternatif pour l'image principale
        - organizer_logo_alt: Texte alternatif pour le logo de l'organisateur (ou null si pas d'organisateur)
        - extracted_published_date: Date de publication extraite du contenu (format YYYY-MM-DD ou null)
        - extracted_deadline: Date limite d'application extraite du contenu (format YYYY-MM-DD ou null)
        - organization_name: Identifie précisément le nom de l'organisation responsable ou associée à l'opportunité décrite dans le contenu . Ne retourne que le nom officiel de l'organisation (par exemple : "Milken Institute" ou "Motsepe Foundation"). Si aucune organisation n’est clairement identifiable, retourne "null".mais il existe il faut analyser bien le contenu pour trouver le nom de l'organization et cette organization peut etre qui lance ou soutient l'initiative décrite dans le contenu .
        - organization_website: Site web de l'organisation (ou null si non trouvé)
        - organization_logo: URL du logo de l'organisation (ou null si non trouvé)
        """


    # SECTION 2: RÉCUPÉRATION DE CONTENU WEB
   

    def get_page_content_static(self, url, max_retries=3):
        """Récupère le contenu d'une page avec requests statique et retry"""
        for attempt in range(max_retries):
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                }
                
                response = self.session.get(url, headers=headers, timeout=(10, 30), allow_redirects=True)
                response.raise_for_status()
                return response.text
                
            except (requests.RequestException, requests.exceptions.ConnectionError, 
                    requests.exceptions.Timeout) as e:
                logger.warning(f"Tentative {attempt + 1}/{max_retries} échouée pour {url}: {e}")
                
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 2
                    logger.info(f"Attente de {wait_time} secondes avant nouvelle tentative...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Échec définitif pour {url} après {max_retries} tentatives")
                    
        return None

    def get_page_content_dynamic(self, url):
        """Récupère le contenu d'une page avec Playwright (pour contenu dynamique)"""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.goto(url)
                page.wait_for_load_state('networkidle')
                content = page.content()
                browser.close()
                return content
        except Exception as e:
            logger.error(f"Erreur Playwright pour {url}: {e}")
            return None

  
    # SECTION 3: EXTRACTION D'ARTICLES
    

    def get_pagination_urls(self, base_url, max_pages=1):
        """Génère les URLs de pagination - configuré pour la première page seulement"""
        urls = [base_url]
        logger.info(f" Traitement de la première page uniquement: {base_url}")
        return urls

    def extract_article_links(self, html_content, base_url):
        """Extrait les liens des articles depuis la page de liste"""
        soup = BeautifulSoup(html_content, 'html.parser')
        links = []
        
        articles = soup.find_all('article', class_=re.compile('l-post|list-post'))
        logger.info(f"Trouvé {len(articles)} articles sur la page")
        
        for article in articles:
            title_elem = article.find('h2', class_='post-title')
            if title_elem:
                link_elem = title_elem.find('a')
                if link_elem and link_elem.get('href'):
                    full_url = urljoin(base_url, link_elem['href'])
                    links.append(full_url)
                    logger.debug(f"Lien trouvé: {full_url}")
        
        logger.info(f"Total liens extraits: {len(links)}")
        return links

    def extract_article_data(self, url):
        """Extrait les données complètes d'un article spécifique"""
        logger.info(f"Extraction de: {url}")
        
        html_content = self.get_page_content_static(url)
        if not html_content:
            html_content = self.get_page_content_dynamic(url)
            
        if not html_content:
            return None
            
        soup = BeautifulSoup(html_content, 'html.parser')
        
        data = {
            'url': url,
            'title': None,
            'published_date': None,
            'subtitle': None,
            'description': None,
            'deadline': None,
            'content': None,
            'soup': soup
        }
        
        # Extraction séquentielle des éléments
        self._extract_title(soup, data)
        self._extract_published_date(soup, data)
        self._extract_content(soup, data)
        
        return data

    def _extract_title(self, soup, data):
        """Extrait le titre de l'article"""
        title_elem = soup.find('h1', class_='post-title')
        if title_elem:
            data['title'] = title_elem.get_text(strip=True)
        else:
            title_elem = soup.find('h1') or soup.find('title')
            if title_elem:
                data['title'] = title_elem.get_text(strip=True)

    def _extract_published_date(self, soup, data):
        """Extrait la date de publication avec plusieurs stratégies"""
        # Stratégie 1: Chercher dans post-meta
        meta_elem = soup.find('div', class_='post-meta')
        if meta_elem:
            date_text = meta_elem.get_text()
            date_match = re.search(r'BY\s+[A-Z\s]+ON\s+([A-Z\s\d,]+)', date_text, re.IGNORECASE)
            if date_match:
                data['published_date'] = date_match.group(1).strip()
                return
            else:
                date_match = re.search(r'ON\s+([A-Z\s\d,]+)', date_text, re.IGNORECASE)
                if date_match:
                    data['published_date'] = date_match.group(1).strip()
                    return
        
        # Stratégie 2: Chercher dans les éléments time
        time_elem = soup.find('time')
        if time_elem:
            datetime_attr = time_elem.get('datetime')
            if datetime_attr:
                data['published_date'] = datetime_attr
            else:
                time_text = time_elem.get_text(strip=True)
                if re.search(r'\d{4}', time_text):
                    data['published_date'] = time_text

    def _extract_content(self, soup, data):
        """Extrait le contenu principal et recherche les deadlines"""
        content_selectors = [
            'div.post-content-wrap',
            'div.post-content',
            'div.entry-content',
            'div.content',
            'article .content',
            '.post-body',
            '.article-content'
        ]
        
        content_elem = None
        for selector in content_selectors:
            content_elem = soup.select_one(selector)
            if content_elem:
                break
        
        if content_elem:
            data['content'] = content_elem.get_text(strip=True)
            
            # Premier paragraphe comme subtitle
            first_p = content_elem.find('p')
            if first_p:
                data['subtitle'] = first_p.get_text(strip=True)
            
            # Reste du contenu comme description
            all_p = content_elem.find_all('p')
            if len(all_p) > 1:
                description_parts = [p.get_text(strip=True) for p in all_p[1:]]
                data['description'] = ' '.join(description_parts)
            
            # Recherche de deadline
            self._extract_deadline(data)

    def _extract_deadline(self, data):
        """Extrait la deadline avec patterns regex multiples"""
        if not data.get('content'):
            return
        
        content_lower = data['content'].lower()
        
        deadline_patterns = [
            r'deadline[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
            r'deadline[:\s]*(\d{1,2}\s+[a-z]+\s+\d{4})',
            r'apply by[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
            r'application deadline[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
            r'applications? close[s]?[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
            r'until[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
            r'until[:\s]*([a-z]+\s+\d{1,2})',
            r'applications?\s+are\s+open.*?until\s+([a-z]+\s+\d{1,2},?\s+\d{4})',
            r'applications?\s+are\s+open.*?until\s+([a-z]+\s+\d{1,2})',
        ]
        
        for pattern in deadline_patterns:
            deadline_match = re.search(pattern, content_lower)
            if deadline_match:
                potential_deadline = deadline_match.group(1).strip()
                if self.is_valid_date(potential_deadline) or self.is_partial_date(potential_deadline):
                    data['deadline'] = potential_deadline
                    logger.info(f"✓ Deadline trouvée: {potential_deadline}")
                    break

    # SECTION 4: VALIDATION DES URLs D'ORGANISATION
    

    def _is_valid_organization_url(self, url):
        """Vérifie si une URL est un site officiel d'organisation (pas un réseau social)"""
        if not url:
            return False
        
        url_lower = url.lower()
        
        # Liste complète des domaines à exclure
        excluded_domains = [
            # Réseaux sociaux principaux
            'facebook.com', 'fb.com', 'linkedin.com', 'twitter.com', 'x.com',
            'instagram.com', 'youtube.com', 'tiktok.com', 'snapchat.com',
            'pinterest.com', 'reddit.com', 'discord.com', 'telegram.org',
            'whatsapp.com', 'wechat.com', 'weibo.com',
            
            # Plateformes de financement et business
            'crunchbase.com', 'angel.co', 'angellist.com', 'gofundme.com',
            'kickstarter.com', 'indiegogo.com', 'patreon.com', 'fundrazr.com',
            
            # Plateformes de contenu et médias
            'medium.com', 'substack.com', 'wordpress.com', 'blogspot.com',
            'tumblr.com', 'github.com', 'gitlab.com',
            
            # Moteurs de recherche et encyclopédies
            'google.com', 'bing.com', 'yahoo.com', 'wikipedia.org',
            'wikimedia.org', 'wikidata.org',
            
            # Plateformes de mise en réseau professionnel
            'meetup.com', 'eventbrite.com', 'zoom.us', 'teams.microsoft.com',
            
            # Autres plateformes communes
            'apple.com', 'microsoft.com', 'amazon.com', 'ebay.com',
            'alibaba.com', 'paypal.com', 'stripe.com',
            
            # Plateformes de répertoires d'entreprises
            'yellowpages.com', 'yelp.com', 'foursquare.com',
        ]
        
        # Vérification des domaines exclus
        for domain in excluded_domains:
            if domain in url_lower:
                logger.debug(f"URL rejetée - domaine exclu '{domain}': {url}")
                return False
        
        # Vérification des patterns d'URLs de réseaux sociaux
        social_patterns = [
            r'facebook\.com/[^/]+/?$',
            r'linkedin\.com/in/',
            r'linkedin\.com/company/',
            r'twitter\.com/[^/]+/?$',
            r'x\.com/[^/]+/?$',
            r'instagram\.com/[^/]+/?$',
            r'youtube\.com/channel/',
            r'youtube\.com/user/',
            r'youtube\.com/c/',
            r'medium\.com/@',
            r'github\.com/[^/]+/?$',
        ]
        
        for pattern in social_patterns:
            if re.search(pattern, url_lower):
                logger.debug(f"URL rejetée - pattern réseau social détecté: {url}")
                return False
        
        # Validation de la structure URL
        try:
            parsed = urlparse(url)
            
            # Vérifications de base
            if parsed.scheme not in ['http', 'https']:
                return False
            if not parsed.netloc:
                return False
            
            # Vérification du domaine
            domain_parts = parsed.netloc.split('.')
            if len(domain_parts) < 2:
                return False
            
            # Exclusion des sous-domaines de plateformes
            subdomain_patterns = [
                r'\.wordpress\.com$', r'\.blogspot\.com$', r'\.medium\.com$',
                r'\.github\.io$', r'\.gitlab\.io$', r'\.herokuapp\.com$',
                r'\.netlify\.app$', r'\.vercel\.app$',
            ]
            
            for pattern in subdomain_patterns:
                if re.search(pattern, parsed.netloc.lower()):
                    logger.debug(f"URL rejetée - sous-domaine de plateforme: {url}")
                    return False
            
            logger.debug(f"URL validée comme site d'organisation: {url}")
            return True
            
        except Exception as e:
            logger.debug(f"Erreur lors de la validation de l'URL {url}: {e}")
            return False

   
    # SECTION 5: EXTRACTION D'ORGANISATIONS
    

    def find_clickable_organization(self, soup, organization_name):
        """Cherche les liens d'organisation dans l'article avec validation stricte"""
        org_info = {
            'organization_website': None,
            'organization_logo': None
        }
        
        logger.info(f" Recherche de liens pour: '{organization_name}'")
        
        # Génération des variations du nom
        name_variations = [
            organization_name,
            organization_name.lower(),
            organization_name.replace(' ', ''),
            organization_name.replace(' ', '-'),
            organization_name.replace(' ', '_'),
        ]
        
        logger.debug(f"Variations du nom: {name_variations}")
        
        # Recherche dans la zone de contenu
        content_area = soup.find('div', class_='post-content-wrap') or soup.find('div', class_='post-content') or soup
        if content_area:
            links = content_area.find_all('a', href=True)
            logger.info(f"Trouvé {len(links)} liens dans l'article")
            
            for link in links:
                link_text = link.get_text(strip=True)
                href = link.get('href')
                
                logger.debug(f"Lien analysé: '{link_text}' -> {href}")
                
                # Validation préalable de l'URL
                if not self._is_valid_organization_url(href):
                    logger.debug(f"URL rejetée (réseaux sociaux/plateforme tierce): {href}")
                    continue
                
                # Correspondance avec les variations du nom
                for variation in name_variations:
                    if variation.lower() in link_text.lower() or link_text.lower() in variation.lower():
                        if href and not href.startswith('#') and 'disruptafrica.com' not in href:
                            org_info['organization_website'] = href
                            logger.info(f" Lien d'organisation trouvé: '{link_text}' -> {href}")
                            
                            # Extraction du logo depuis le site
                            org_info['organization_logo'] = self.extract_logo_from_website(href)
                            
                            if org_info['organization_logo']:
                                logger.info(f" Logo extrait avec succès: {org_info['organization_logo']}")
                            else:
                                logger.warning(f" Échec extraction logo depuis: {href}")
                                
                            return org_info
                        else:
                            logger.debug(f"Lien ignoré (interne ou fragment): {href}")
        else:
            logger.warning(" Zone de contenu non trouvée dans l'article")
        
        logger.warning(f" Aucun lien trouvé pour l'organisation: {organization_name}")
        return org_info

  
    # SECTION 6: EXTRACTION DE LOGOS (8 STRATÉGIES)
   

    async def _find_logo_dynamic_strategy(self, website_url):
        """STRATÉGIE 8 (DYNAMIQUE): Utilise Playwright pour trouver le premier logo"""
        logger.debug(" STRATÉGIE DYNAMIQUE: Recherche avec Playwright")
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(website_url, wait_until='networkidle')
                
                # Récupération de toutes les balises <img>
                img_elements = await page.query_selector_all("img")
                
                for img in img_elements:
                    src = await img.get_attribute("src")
                    alt = await img.get_attribute("alt")
                    
                    if src:
                        src_lower = src.lower()
                        alt_lower = (alt or "").lower()
                        
                        # Détection des logos
                        if ("logo" in src_lower or "logo" in alt_lower):
                            full_url = urljoin(website_url, src)
                            logger.info(f"STRATÉGIE DYNAMIQUE - Premier logo détecté: {full_url}")
                            await browser.close()
                            return full_url
                
                await browser.close()
                logger.debug(" STRATÉGIE DYNAMIQUE: Aucun logo détecté")
                return None
                
        except Exception as e:
            logger.debug(f"Erreur stratégie dynamique: {e}")
            return None

    def extract_logo_from_website(self, website_url):
        """Extraction complète de logos avec 8 stratégies (7 statiques + 1 dynamique)"""
        try:
            logger.info(f" Extraction avancée du logo depuis: {website_url}")
            
            if not website_url.startswith(('http://', 'https://')):
                website_url = 'https://' + website_url
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/svg+xml,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            }
            
            response = self.session.get(website_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            header_elements = self._find_header_elements(soup)
            
            # Application des 7 stratégies statiques
            static_strategies = [
                self._find_logo_by_alt_attribute,      # Stratégie 1
                self._find_logo_svg_elements,          # Stratégie 2
                self._find_logo_in_containers,         # Stratégie 3
                self._find_logo_by_src_content,        # Stratégie 4
                self._find_logo_by_data_attributes,    # Stratégie 5
                self._find_logo_by_context_analysis,   # Stratégie 6
                self._find_logo_intelligent_fallback   # Stratégie 7
            ]
            
            for i, strategy in enumerate(static_strategies, 1):
                logo_url = strategy(header_elements, website_url)
                if logo_url:
                    return logo_url
            
            # Stratégie 8: Dynamique avec Playwright
            logger.info(" Tentative avec la stratégie dynamique (Playwright)...")
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                dynamic_logo = loop.run_until_complete(self._find_logo_dynamic_strategy(website_url))
                loop.close()
                
                if dynamic_logo:
                    return dynamic_logo
            except Exception as e:
                logger.debug(f"Erreur stratégie dynamique: {e}")
            
            logger.warning(f" Aucun logo trouvé avec toutes les stratégies sur: {website_url}")
            return None
            
        except Exception as e:
            logger.warning(f" Erreur lors de l'extraction avancée du logo: {e}")
            return None

    def _find_header_elements(self, soup):
        """Identifie tous les éléments pouvant contenir un header"""
        header_selectors = [
            'header', '[class*="header" i]', '[id*="header" i]', 'nav',
            '[class*="navbar" i]', '[class*="nav" i]', '[class*="top" i]',
            '[class*="brand" i]', '[role="banner"]', '.site-header',
            '.main-header', '.page-header', '#masthead', '.masthead'
        ]
        
        header_elements = []
        for selector in header_selectors:
            elements = soup.select(selector)
            header_elements.extend(elements)
        
        # Suppression des doublons
        unique_headers = []
        seen = set()
        for elem in header_elements:
            elem_id = id(elem)
            if elem_id not in seen:
                seen.add(elem_id)
                unique_headers.append(elem)
        
        logger.debug(f" Trouvé {len(unique_headers)} zones header potentielles")
        return unique_headers

    def _find_logo_by_alt_attribute(self, header_elements, base_url):
        """STRATÉGIE 1: Recherche d'images avec attribut alt contenant 'logo'"""
        logger.debug(" STRATÉGIE 1: Recherche par alt='logo'")
        
        logo_keywords = ['logo', 'brand', 'company', 'organization', 'site']
        
        for header in header_elements:
            images = header.find_all('img', alt=True)
            logger.debug(f"Trouvé {len(images)} images avec attribut alt dans le header")
            
            for img in images:
                alt_text = img.get('alt', '').lower()
                src = img.get('src')
                
                logger.debug(f"Image analysée: alt='{img.get('alt')}' src='{src}'")
                
                if any(keyword in alt_text for keyword in logo_keywords):
                    if src:
                        logo_url = self._normalize_logo_url(src, base_url)
                        if self._is_valid_logo_candidate(logo_url, img, confidence_boost=0.4):
                            logger.info(f" STRATÉGIE 1 - Logo trouvé par alt='{img.get('alt')}': {logo_url}")
                            return logo_url
        
        logger.debug(" STRATÉGIE 1: Aucun logo trouvé par alt")
        return None

    def _find_logo_svg_elements(self, header_elements, base_url):
        """STRATÉGIE 2: Recherche d'éléments SVG avec classes ou IDs logo"""
        logger.debug("🔍 STRATÉGIE 2: Recherche SVG avec classes logo")
        
        for header in header_elements:
            # SVG avec class contenant "logo"
            svg_elements = header.find_all('svg', class_=re.compile('logo', re.I))
            for svg in svg_elements:
                svg_url = self._extract_svg_as_logo(svg, base_url)
                if svg_url:
                    logger.info(f" STRATÉGIE 2 - SVG logo trouvé: {svg_url}")
                    return svg_url
            
            # SVG avec ID contenant "logo"
            svg_elements = header.find_all('svg', id=re.compile('logo', re.I))
            for svg in svg_elements:
                svg_url = self._extract_svg_as_logo(svg, base_url)
                if svg_url:
                    logger.info(f" STRATÉGIE 2 - SVG logo (ID) trouvé: {svg_url}")
                    return svg_url
            
            # SVG dans des containers logo
            logo_containers = header.find_all(['div', 'a', 'span'], class_=re.compile('logo', re.I))
            for container in logo_containers:
                svg = container.find('svg')
                if svg:
                    svg_url = self._extract_svg_as_logo(svg, base_url)
                    if svg_url:
                        logger.info(f" STRATÉGIE 2 - SVG dans container logo: {svg_url}")
                        return svg_url
        
        return None

    def _find_logo_in_containers(self, header_elements, base_url):
        """STRATÉGIE 3: Recherche dans containers avec class/id 'logo'"""
        logger.debug(" STRATÉGIE 3: Recherche dans containers logo")
        
        container_selectors = [
            '[class*="logo" i]', '[id*="logo" i]', '[class*="brand" i]', 
            '[id*="brand" i]', '.site-title', '.site-logo', '.brand-logo', '.company-logo'
        ]
        
        for header in header_elements:
            for selector in container_selectors:
                containers = header.select(selector)
                
                for container in containers:
                    # Image dans le container
                    img = container.find('img')
                    if img and img.get('src'):
                        logo_url = self._normalize_logo_url(img.get('src'), base_url)
                        if self._is_valid_logo_candidate(logo_url, img, confidence_boost=0.3):
                            logger.info(f" STRATÉGIE 3 - Logo dans container '{selector}': {logo_url}")
                            return logo_url
                    
                    # Container lui-même est une image
                    if container.name == 'img' and container.get('src'):
                        logo_url = self._normalize_logo_url(container.get('src'), base_url)
                        if self._is_valid_logo_candidate(logo_url, container, confidence_boost=0.3):
                            logger.info(f" STRATÉGIE 3 - Container image logo: {logo_url}")
                            return logo_url
        
        return None

    def _find_logo_by_src_content(self, header_elements, base_url):
        """STRATÉGIE 4: Images avec src contenant 'logo'"""
        logger.debug("🔍 STRATÉGIE 4: Recherche par src contenant 'logo'")
        
        for header in header_elements:
            images = header.find_all('img', src=True)
            
            for img in images:
                src = img.get('src', '').lower()
                
                if 'logo' in src and not any(exclude in src for exclude in ['icon', 'avatar', 'profile']):
                    logo_url = self._normalize_logo_url(img.get('src'), base_url)
                    if self._is_valid_logo_candidate(logo_url, img, confidence_boost=0.2):
                        logger.info(f" STRATÉGIE 4 - Logo par src contenant 'logo': {logo_url}")
                        return logo_url
        
        return None

    def _find_logo_by_data_attributes(self, header_elements, base_url):
        """STRATÉGIE 5: Images avec attributs data-* ou title contenant 'logo'"""
        logger.debug(" STRATÉGIE 5: Recherche par attributs data-* et title")
        
        for header in header_elements:
            images = header.find_all('img')
            
            for img in images:
                attrs = img.attrs
                
                for attr_name, attr_value in attrs.items():
                    if isinstance(attr_value, str) and 'logo' in attr_value.lower():
                        if attr_name in ['data-src', 'data-original', 'title', 'aria-label']:
                            src = img.get('src') or img.get('data-src') or img.get('data-original')
                            if src:
                                logo_url = self._normalize_logo_url(src, base_url)
                                if self._is_valid_logo_candidate(logo_url, img, confidence_boost=0.2):
                                    logger.info(f" STRATÉGIE 5 - Logo par {attr_name}='{attr_value}': {logo_url}")
                                    return logo_url
        
        return None

    def _find_logo_by_context_analysis(self, header_elements, base_url):
        """STRATÉGIE 6: Analyse contextuelle - images avec liens/textes indicateurs"""
        logger.debug(" STRATÉGIE 6: Analyse contextuelle")
        
        context_indicators = ['home', 'accueil', 'homepage', 'site', 'company', 'organization']
        
        for header in header_elements:
            home_links = header.find_all('a', href=True)
            
            for link in home_links:
                href = link.get('href', '').lower()
                link_text = link.get_text(strip=True).lower()
                
                if (href in ['/', '#', ''] or 
                    any(indicator in href for indicator in ['home', 'index']) or
                    any(indicator in link_text for indicator in context_indicators)):
                    
                    img = link.find('img')
                    if img and img.get('src'):
                        logo_url = self._normalize_logo_url(img.get('src'), base_url)
                        if self._is_valid_logo_candidate(logo_url, img, confidence_boost=0.1):
                            logger.info(f" STRATÉGIE 6 - Logo contextuel (lien home): {logo_url}")
                            return logo_url
        
        return None

    def _find_logo_intelligent_fallback(self, header_elements, base_url):
        """STRATÉGIE 7: Fallback intelligent - première image significative"""
        logger.debug("🔍 STRATÉGIE 7: Fallback intelligent")
        
        for header in header_elements:
            images = header.find_all('img', src=True)
            
            for img in images[:3]:  # Limiter aux 3 premières images
                src = img.get('src', '').lower()
                
                # Exclure les images clairement non-logo
                exclude_patterns = [
                    'icon', 'arrow', 'menu', 'search', 'close', 'burger', 'hamburger',
                    'facebook', 'twitter', 'linkedin', 'instagram', 'youtube', 'social',
                    'banner', 'ad', 'advertisement', 'avatar', 'profile', 'user'
                ]
                
                if any(pattern in src for pattern in exclude_patterns):
                    continue
                
                # Vérifier les dimensions si disponibles
                width = img.get('width')
                height = img.get('height')
                
                if width and height:
                    try:
                        w, h = int(width), int(height)
                        # Dimensions inadéquates pour un logo
                        if w < 30 or h < 20 or w/h > 10 or h/w > 3:
                            continue
                    except:
                        pass
                
                logo_url = self._normalize_logo_url(img.get('src'), base_url)
                if self._is_valid_logo_candidate(logo_url, img, confidence_boost=0):
                    logger.info(f" STRATÉGIE 7 - Logo fallback intelligent: {logo_url}")
                    return logo_url
        
        return None

    def _extract_svg_as_logo(self, svg_element, base_url):
        """Extrait un SVG comme logo - retourne URL ou data URL"""
        try:
            # SVG avec référence externe
            use_element = svg_element.find('use')
            if use_element and use_element.get('href'):
                href = use_element.get('href')
                if href.startswith('http'):
                    return href
                elif href.startswith('/'):
                    return self._normalize_logo_url(href, base_url)
            
            # SVG avec contenu inline significatif
            svg_content = str(svg_element)
            if len(svg_content) > 100 and ('path' in svg_content or 'circle' in svg_content or 'rect' in svg_content):
                # Créer une data URL pour le SVG
                svg_bytes = svg_content.encode('utf-8')
                svg_base64 = base64.b64encode(svg_bytes).decode('utf-8')
                return f"data:image/svg+xml;base64,{svg_base64}"
            
            return None
            
        except Exception as e:
            logger.debug(f"Erreur extraction SVG: {e}")
            return None

    def _normalize_logo_url(self, logo_src, base_url):
        """Normalise l'URL du logo (relative vers absolue)"""
        if not logo_src:
            return None
        
        if logo_src.startswith(('http://', 'https://')):
            return logo_src
        
        if logo_src.startswith('/'):
            parsed_url = urlparse(base_url)
            return f"{parsed_url.scheme}://{parsed_url.netloc}{logo_src}"
        
        return urljoin(base_url, logo_src)

    def _is_valid_logo_candidate(self, logo_url, img_element, confidence_boost=0):
        """Évalue la validité d'un candidat logo avec système de scoring"""
        if not logo_url:
            logger.debug(" Logo candidat rejeté: URL vide")
            return False
        
        confidence_score = confidence_boost
        logger.debug(f" Validation logo candidat: {logo_url}")
        logger.debug(f"Score initial avec boost: {confidence_score}")
        
        # Validation de l'extension/type
        if logo_url.startswith('data:image/'):
            confidence_score += 0.2
            logger.debug(f"Bonus data URL: +0.2 → {confidence_score}")
        else:
            valid_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']
            has_valid_ext = any(ext in logo_url.lower() for ext in valid_extensions)
            
            if not has_valid_ext:
                logger.debug(f" Extension invalide pour: {logo_url}")
                return False
            
            if '.svg' in logo_url.lower():
                confidence_score += 0.1
                logger.debug(f"Bonus SVG: +0.1 → {confidence_score}")
        
        # Analyse de l'élément img
        if img_element:
            alt_text = img_element.get('alt', '').lower()
            class_list = ' '.join(img_element.get('class', [])).lower()
            
            logger.debug(f"Alt text: '{alt_text}', Classes: '{class_list}'")
            
            # Bonus pour mots-clés logo
            logo_keywords = ['logo', 'brand', 'company', 'organization', 'site']
            if any(keyword in alt_text or keyword in class_list for keyword in logo_keywords):
                confidence_score += 0.3
                logger.debug(f"Bonus mots-clés logo: +0.3 → {confidence_score}")
            
            # Validation des dimensions
            width = img_element.get('width')
            height = img_element.get('height')
            if width and height:
                try:
                    w, h = int(width), int(height)
                    logger.debug(f"Dimensions: {w}x{h}")
                    if 50 <= w <= 500 and 20 <= h <= 200:
                        confidence_score += 0.1
                        logger.debug(f"Bonus dimensions: +0.1 → {confidence_score}")
                except:
                    logger.debug("Erreur parsing dimensions")
                    pass
        
        # Validation de l'accessibilité de l'image
        if not logo_url.startswith('data:'):
            if not self.validate_logo_image(logo_url):
                logger.debug(f" Image non accessible: {logo_url}")
                return False
            else:
                logger.debug(f" Image accessible: {logo_url}")
        
        # Décision finale basée sur le score
        min_confidence = 0.1
        decision = confidence_score >= min_confidence
        
        logger.debug(f" Score final: {confidence_score:.2f}, Minimum requis: {min_confidence}, Décision: {decision}")
        
        return decision

    
    # SECTION 7: VALIDATION ET UTILITAIRES
    

    def validate_logo_image(self, logo_url):
        """Valide qu'une URL d'image est accessible"""
        try:
            if not logo_url or len(logo_url) < 10:
                return False
            
            valid_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']
            if not any(ext in logo_url.lower() for ext in valid_extensions):
                return False
            
            try:
                head_response = self.session.head(logo_url, timeout=5)
                if head_response.status_code == 200:
                    content_type = head_response.headers.get('content-type', '')
                    if 'image' in content_type:
                        return True
            except:
                try:
                    get_response = self.session.get(logo_url, timeout=3, stream=True)
                    if get_response.status_code == 200:
                        content_type = get_response.headers.get('content-type', '')
                        return 'image' in content_type
                except:
                    pass
            
            return False
            
        except Exception:
            return False

    def validate_website(self, website_url):
        """Valide qu'une URL de site web est accessible"""
        if not website_url:
            return False
        
        try:
            if not website_url.startswith(('http://', 'https://')):
                website_url = 'https://' + website_url
            
            response = self.session.head(website_url, timeout=10, allow_redirects=True)
            return response.status_code == 200
        except:
            return False

    def is_partial_date(self, date_str):
        """Vérifie si c'est une date partielle valide (ex: 'june 29' sans année)"""
        if not date_str:
            return False
        
        date_str_lower = date_str.lower()
        month_day_pattern = r'^([a-z]+)\s+(\d{1,2})'
        match = re.search(month_day_pattern, date_str_lower)
        
        if match:
            month = match.group(1)
            day = int(match.group(2))
            
            valid_months = [
                'january', 'february', 'march', 'april', 'may', 'june',
                'july', 'august', 'september', 'october', 'november', 'december',
                'jan', 'feb', 'mar', 'apr', 'may', 'jun',
                'jul', 'aug', 'sep', 'oct', 'nov', 'dec'
            ]
            
            return month in valid_months and 1 <= day <= 31
        
        return False

    def is_valid_date(self, date_str):
        """Vérifie si une chaîne ressemble à une vraie date"""
        if not date_str:
            return False
        
        date_str_lower = date_str.lower()
        
        has_month = any(month in date_str_lower for month in [
            'january', 'february', 'march', 'april', 'may', 'june',
            'july', 'august', 'september', 'october', 'november', 'december',
            'jan', 'feb', 'mar', 'apr', 'may', 'jun',
            'jul', 'aug', 'sep', 'oct', 'nov', 'dec'
        ])
        
        has_year = re.search(r'\d{4}', date_str)
        is_numeric_date = re.search(r'\d{1,2}[-/]\d{1,2}[-/]\d{4}', date_str)
        
        return (has_month and has_year) or is_numeric_date

    def extract_clean_date(self, text):
        """Extrait une date propre à partir d'un texte"""
        if not text:
            return None
        
        text_lower = text.lower().strip()
        
        date_patterns = [
            r'^([a-z]+\s+\d{1,2},?\s+\d{4})',
            r'^(\d{1,2}\s+[a-z]+\s+\d{4})',
            r'^(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
            r'\b([a-z]+\s+\d{1,2},?\s+\d{4})\b',
            r'\b(\d{1,2}\s+[a-z]+\s+\d{4})\b',
            r'^([a-z]+\s+\d{1,2})',
            r'\b([a-z]+\s+\d{1,2})\b'
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text_lower)
            if match:
                extracted_date = match.group(1).strip()
                if self.is_valid_date(extracted_date) or self.is_partial_date(extracted_date):
                    return extracted_date
        
        return None

    def create_slug(self, title):
        """Crée un slug URL à partir du titre"""
        if not title:
            return ""
        
        slug = title.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug)
        slug = slug.strip('-')
        return slug

   
    # SECTION 8: SERPAPI ET ENRICHISSEMENT
  

    def calculate_website_relevance(self, organization_name, url, title, snippet):
        """Calcule la pertinence d'un résultat de recherche pour une organisation"""
        try:
            # Validation préalable de l'URL
            if not self._is_valid_organization_url(url):
                logger.debug(f"URL SerpAPI rejetée (réseau social/plateforme): {url}")
                return 0.0
            
            score = 0.0
            org_name_lower = organization_name.lower()
            url_lower = url.lower()
            
            org_words = re.findall(r'\b\w+\b', org_name_lower)
            org_words = [word for word in org_words if len(word) > 2]
            
            # Scoring par correspondance dans l'URL
            url_domain = urlparse(url).netloc.lower()
            for word in org_words:
                if word in url_domain:
                    score += 0.3
            
            # Scoring par correspondance dans le titre
            for word in org_words:
                if word in title:
                    score += 0.2
            
            # Scoring par correspondance dans le snippet
            for word in org_words:
                if word in snippet:
                    score += 0.1
            
            # Bonus pour indicateurs de sites officiels
            official_indicators = ['official', 'org', 'foundation', 'organization', 'initiative']
            for indicator in official_indicators:
                if indicator in url_lower or indicator in title or indicator in snippet:
                    score += 0.2
            
            # Bonus pour domaines institutionnels
            institutional_tlds = ['.org', '.edu', '.gov', '.foundation', '.institute']
            for tld in institutional_tlds:
                if tld in url_lower:
                    score += 0.2
                    break
            
            # Malus pour domaines non officiels (double vérification)
            unwanted_domains = ['wikipedia', 'crunchbase', 'bloomberg', 'reuters']
            for domain in unwanted_domains:
                if domain in url_lower:
                    score -= 0.5
            
            # Normalisation du score
            score = min(max(score, 0.0), 1.0)
            
            logger.debug(f"Score de pertinence pour {url}: {score:.2f}")
            return score
            
        except Exception as e:
            logger.debug(f"Erreur calcul pertinence: {e}")
            return 0.0

    def enrich_with_serpapi(self, organization_name, current_website=None, current_logo=None):
        """Enrichit les informations d'organisation avec SerpAPI (Google Search)"""
        if not self.serpapi_key or not organization_name:
            logger.info("API SerpAPI non configurée ou nom d'organisation manquant")
            return {
                'organization_website': current_website,
                'organization_logo': current_logo,
                'serpapi_enhanced': False
            }
        
        try:
            logger.info(f"🔍 Enrichissement SerpAPI pour: {organization_name}")
            
            # Validation des données actuelles
            website_valid = self.validate_website(current_website) if current_website else False
            logo_valid = self.validate_logo_image(current_logo) if current_logo else False
            
            # Skip si les deux sont déjà valides
            if website_valid and logo_valid:
                logger.info("✓ Website et logo déjà valides, pas d'enrichissement nécessaire")
                return {
                    'organization_website': current_website,
                    'organization_logo': current_logo,
                    'serpapi_enhanced': False
                }
            
            # Requêtes de recherche multiples
            search_queries = [
                f'"{organization_name}" site officiel',
                f'"{organization_name}" official website',
                f'{organization_name} organization official site',
                f'{organization_name} foundation website'
            ]
            
            found_website = None
            best_confidence = 0
            
            for query in search_queries:
                try:
                    logger.debug(f"🔎 Recherche SerpAPI: {query}")
                    
                    params = {
                        'api_key': self.serpapi_key,
                        'engine': 'google',
                        'q': query,
                        'num': 5,
                        'hl': 'en',
                        'gl': 'us'
                    }
                    
                    response = self.session.get("https://serpapi.com/search", params=params, timeout=15)
                    
                    if response.status_code == 200:
                        search_results = response.json()
                        
                        # Analyse des résultats organiques
                        if 'organic_results' in search_results:
                            for result in search_results['organic_results']:
                                url = result.get('link', '')
                                title = result.get('title', '').lower()
                                snippet = result.get('snippet', '').lower()
                                
                                # Filtrage préalable des URLs invalides
                                if not self._is_valid_organization_url(url):
                                    logger.debug(f"Résultat SerpAPI ignoré (URL invalide): {url}")
                                    continue
                                
                                confidence = self.calculate_website_relevance(
                                    organization_name, url, title, snippet
                                )
                                
                                if confidence > best_confidence and confidence > 0.4:
                                    if self.validate_website(url):
                                        found_website = url
                                        best_confidence = confidence
                                        logger.info(f"✓ Site web trouvé: {url} (confiance: {confidence:.2f})")
                                        
                                        if confidence > 0.8:
                                            break
                        
                        # Vérification du knowledge graph
                        if 'knowledge_graph' in search_results:
                            kg = search_results['knowledge_graph']
                            if 'website' in kg:
                                kg_website = kg['website']
                                
                                # Validation de l'URL du knowledge graph
                                if self._is_valid_organization_url(kg_website):
                                    confidence = self.calculate_website_relevance(
                                        organization_name, kg_website, 
                                        kg.get('title', ''), kg.get('description', '')
                                    )
                                    
                                    if confidence > best_confidence:
                                        if self.validate_website(kg_website):
                                            found_website = kg_website
                                            best_confidence = confidence
                                            logger.info(f"✓ Site web trouvé via Knowledge Graph: {kg_website}")
                                else:
                                    logger.debug(f"Knowledge Graph URL ignorée (invalide): {kg_website}")
                    
                    time.sleep(1)
                    
                    if best_confidence > 0.8:
                        break
                        
                except Exception as e:
                    logger.debug(f"Erreur pour requête '{query}': {e}")
                    continue
            
            final_website = found_website if found_website and not website_valid else current_website
            
            # Extraction de logo avancée avec Playwright
            final_logo = current_logo
            if not logo_valid and final_website:
                try:
                    logger.info(f" Tentative d'extraction de logo avancée depuis: {final_website}")
                    extracted_logo = self.extract_logo_from_website(final_website)
                    if extracted_logo:
                        final_logo = extracted_logo
                        logger.info(f" Logo extrait avec succès: {extracted_logo}")
                    else:
                        logger.warning(f" Impossible d'extraire le logo depuis: {final_website}")
                except Exception as e:
                    logger.debug(f"Erreur extraction logo avancée: {e}")
            
            success = found_website is not None or (website_valid and logo_valid)
            
            if success:
                logger.info(f" Enrichissement SerpAPI réussi - Website: {final_website}, Logo: {'Oui' if final_logo else 'Non'}")
            else:
                logger.info(f" Aucun résultat pertinent trouvé pour: {organization_name}")
            
            return {
                'organization_website': final_website,
                'organization_logo': final_logo,
                'serpapi_enhanced': success
            }
            
        except Exception as e:
            logger.error(f"Erreur lors de l'enrichissement SerpAPI: {e}")
            return {
                'organization_website': current_website,
                'organization_logo': current_logo,
                'serpapi_enhanced': False
            }

   
    # SECTION 9: ANALYSE LLM
  

    def analyze_with_llm(self, article_data):
        """Analyse le contenu avec Gemini AI pour extraire les métadonnées"""
        try:
            prompt = self.llm_prompt.format(
                content=article_data.get('content', '')[:3000],
                title=article_data.get('title', ''),
                published_date=article_data.get('published_date', '')
            )
            
            response = self.model.generate_content(prompt)
            
            json_text = response.text.strip()
            if json_text.startswith('```json'):
                json_text = json_text[7:-3]
            elif json_text.startswith('```'):
                json_text = json_text[3:-3]
            
            llm_result = json.loads(json_text)
            
            # LOG: Affichage des détections du LLM
            org_name = llm_result.get('organization_name')
            org_website = llm_result.get('organization_website')
            org_logo = llm_result.get('organization_logo')
            
            logger.info(f" LLM - Organisation détectée: '{org_name}'")
            logger.info(f" LLM - Website détecté: '{org_website}'")
            logger.info(f" LLM - Logo détecté: '{org_logo}'")
            
            # Validation et nettoyage des dates extraites
            if article_data.get('published_date'):
                pub_date = article_data['published_date']
                if any(month in pub_date.lower() for month in [
                    'january', 'february', 'march', 'april', 'may', 'june',
                    'july', 'august', 'september', 'october', 'november', 'december'
                ]) and re.search(r'\d{4}', pub_date):
                    llm_result['extracted_published_date'] = pub_date
                else:
                    llm_result['extracted_published_date'] = None
            else:
                llm_result['extracted_published_date'] = None
            
            if article_data.get('deadline'):
                deadline = article_data['deadline'].strip()
                clean_deadline = self.extract_clean_date(deadline)
                
                if clean_deadline and self.is_valid_date(clean_deadline):
                    llm_result['extracted_deadline'] = clean_deadline
                else:
                    llm_result['extracted_deadline'] = None
            else:
                llm_result['extracted_deadline'] = None
            
            return llm_result
            
        except Exception as e:
            logger.error(f" Erreur LLM: {e}")
            logger.info("Utilisation du résultat de secours LLM")
            return self._get_fallback_llm_result(article_data)

    def _get_fallback_llm_result(self, article_data):
        """Retourne un résultat de secours en cas d'erreur LLM"""
        return {
            'meta_title': article_data.get('title', '')[:100],
            'meta_description': article_data.get('subtitle', '')[:160],
            'slug': self.create_slug(article_data.get('title', '')),
            'regions': [],
            'sectors': [],
            'stages': [],
            'categories': [],
            'draft_summary': article_data.get('subtitle', ''),
            'main_image_alt': None,
            'organizer_logo_alt': None,
            'extracted_published_date': article_data.get('published_date') if self.is_valid_date(article_data.get('published_date')) else None,
            'extracted_deadline': article_data.get('deadline') if self.is_valid_date(article_data.get('deadline')) else None,
            'organization_name': None,
            'organization_website': None,
            'organization_logo': None
        }

   

    def enhance_opportunities_with_serpapi(self, opportunities):
        """Enrichit toutes les opportunités avec SerpAPI avant sauvegarde"""
        logger.info(f" Enrichissement de {len(opportunities)} opportunités avec SerpAPI...")
        
        enhanced_opportunities = []
        
        for i, opportunity in enumerate(opportunities):
            logger.info(f"Enrichissement {i+1}/{len(opportunities)}: {opportunity.get('title', 'Titre inconnu')[:50]}...")
            
            organization_name = opportunity.get('organization_name')
            current_website = opportunity.get('organization_website')
            current_logo = opportunity.get('organization_logo')
            
            if organization_name:
                # Enrichissement conditionnel basé sur la validité des données existantes
                website_valid = self.validate_website(current_website) if current_website else False
                logo_valid = self.validate_logo_image(current_logo) if current_logo else False
                
                if not website_valid or not logo_valid:
                    enriched_org_info = self.enrich_with_serpapi(
                        organization_name, 
                        current_website, 
                        current_logo
                    )
                    
                    # Mise à jour de l'opportunité avec les nouvelles informations
                    opportunity.update(enriched_org_info)
                    
                    if enriched_org_info.get('serpapi_enhanced'):
                        logger.info(f" Enrichi avec succès via SerpAPI: {organization_name}")
                    
                    # Pause pour respecter les limites de SerpAPI
                    time.sleep(3)
                else:
                    logger.info(f"✓ Données déjà valides pour: {organization_name}")
            
            enhanced_opportunities.append(opportunity)
        
        logger.info(f" Enrichissement terminé pour {len(enhanced_opportunities)} opportunités")
        return enhanced_opportunities

    def scrape_opportunities(self):
        """Fonction principale pour scraper toutes les opportunités"""
        all_opportunities = []
        
        for base_url in self.base_urls:
            logger.info(f" Scraping: {base_url}")
            
            # Traitement de la première page uniquement
            page_urls = self.get_pagination_urls(base_url, max_pages=1)
            
            for page_url in page_urls:
                logger.info(f" Page: {page_url}")
                
                # Récupération du contenu de la page
                html_content = self.get_page_content_static(page_url)
                if not html_content:
                    html_content = self.get_page_content_dynamic(page_url)
                
                if not html_content:
                    continue
                
                # Extraction des liens d'articles
                article_links = self.extract_article_links(html_content, page_url)
                
                # Traitement de chaque article
                for i, article_url in enumerate(article_links):
                    try:
                        logger.info(f" Traitement article {i+1}/{len(article_links)}: {article_url}")
                        
                        # ÉTAPE 1: Extraction des données de l'article
                        article_data = self.extract_article_data(article_url)
                        
                        if article_data and article_data.get('title'):
                            # ÉTAPE 2: Analyse avec LLM pour obtenir les métadonnées
                            llm_data = self.analyze_with_llm(article_data)
                            
                            # ÉTAPE 3: Recherche de liens d'organisation dans l'article
                            organization_name = llm_data.get('organization_name')
                            if organization_name and article_data.get('soup'):
                                logger.info(f" Organisation détectée par LLM: '{organization_name}'")
                                org_info = self.find_clickable_organization(article_data['soup'], organization_name)
                                
                                # Mise à jour des données LLM avec les informations trouvées
                                if org_info['organization_website']:
                                    llm_data['organization_website'] = org_info['organization_website']
                                    logger.info(f" Website mis à jour: {org_info['organization_website']}")
                                if org_info['organization_logo']:
                                    llm_data['organization_logo'] = org_info['organization_logo']
                                    logger.info(f" Logo mis à jour: {org_info['organization_logo']}")
                            else:
                                if not organization_name:
                                    logger.info(" Aucune organisation détectée par le LLM")
                                if not article_data.get('soup'):
                                    logger.warning(" Soup HTML manquant pour l'extraction d'organisation")
                            
                            # ÉTAPE 4: Combinaison des données
                            opportunity = {
                                **article_data,
                                **llm_data,
                                'extracted_published_date': article_data.get('published_date'),
                                'extracted_deadline': article_data.get('deadline')
                            }
                            
                            # Nettoyage des champs temporaires
                            fields_to_remove = ['published_date', 'deadline', 'soup']
                            for field in fields_to_remove:
                                if field in opportunity:
                                    del opportunity[field]
                            
                            all_opportunities.append(opportunity)
                            
                            logger.info(f"✓ Article traité: {article_data['title'][:60]}...")
                            
                            # Pause progressive pour éviter la surcharge
                            time.sleep(3 + (len(all_opportunities) % 3))
                        else:
                            logger.warning(f" Données manquantes pour: {article_url}")
                            
                    except Exception as e:
                        logger.error(f" Erreur lors du traitement de {article_url}: {e}")
                        time.sleep(2)
                        continue
        
        return all_opportunities

    def save_to_json(self, opportunities, filename="disruptafrica_opportunities.json"):
        """Sauvegarde les opportunités dans un fichier JSON avec encodage UTF-8"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(opportunities, f, ensure_ascii=False, indent=2)
        
        logger.info(f" Données sauvegardées dans {filename}")




def main():
    """Fonction principale d'exécution du scraper"""
    logger.info(" Démarrage du scraper DisruptAfrica")
    
    try:
        # Initialisation du scraper (clés API chargées depuis config.env)
        scraper = DisruptAfricaScraper()
        
        # PHASE 1: Scraping principal
        logger.info(" Phase 1: Scraping des opportunités...")
        opportunities = scraper.scrape_opportunities()
        
        if not opportunities:
            logger.warning(" Aucune opportunité trouvée lors du scraping")
            return
        
        logger.info(f"{len(opportunities)} opportunités extraites avec succès")
        
        # PHASE 2: Enrichissement avec SerpAPI
        logger.info(" Phase 2: Enrichissement avec SerpAPI...")
        enhanced_opportunities = scraper.enhance_opportunities_with_serpapi(opportunities)
        
        # PHASE 3: Sauvegarde des résultats
        logger.info(" Phase 3: Sauvegarde des résultats...")
        scraper.save_to_json(enhanced_opportunities)
        
        # Rapport final
        print(f"\n Scraping terminé avec succès!")
        print(f" {len(enhanced_opportunities)} opportunités extraites et enrichies")
        print(f" Données sauvegardées dans 'disruptafrica_opportunities.json'")
        
        # Affichage d'un exemple pour vérification
        if enhanced_opportunities:
            print(f"\n Exemple d'opportunité enrichie:")
            print("=" * 50)
            example = enhanced_opportunities[0]
            print(f"Titre: {example.get('title', 'N/A')}")
            print(f"Organisation: {example.get('organization_name', 'N/A')}")
            print(f"Website: {example.get('organization_website', 'N/A')}")
            print(f"Logo: {'Oui' if example.get('organization_logo') else 'Non'}")
            print(f"Régions: {', '.join(example.get('regions', [])[:3])}...")
            print(f"Secteurs: {', '.join(example.get('sectors', [])[:3])}...")
            print("=" * 50)
            
    except KeyboardInterrupt:
        logger.info(" Scraping interrompu par l'utilisateur")
    except Exception as e:
        logger.error(f" Erreur générale: {e}")
        raise


if __name__ == "__main__":
    main()