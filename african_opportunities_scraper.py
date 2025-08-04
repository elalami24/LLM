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
import asyncio
import base64
from dotenv import load_dotenv
import cv2
import numpy as np
from PIL import Image
import io

# Charger les variables d'environnement
load_dotenv('config.env')

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AfricanOpportunitiesScraper:
    """
    Scraper avancé pour les opportunités africaines avec extraction de logos et enrichissement SerpAPI
    """
    
    def __init__(self, gemini_api_key=None, serpapi_key=None):
        """Initialise le scraper avec toutes les configurations nécessaires"""
        self.base_urls = [
            "https://www.opportunitiesforafricans.com/",
            "https://msmeafricaonline.com/category/opportunities/",
            "https://opportunitydesk.org/category/search-by-region/africa/"
        ]
        
        # Configuration des composants
        self._setup_session()
        self._setup_gemini(gemini_api_key)
        self._setup_serpapi(serpapi_key)
        self._setup_llm_prompt()
        
        # Stockage des candidats logos pour analyse AI
        self.logo_candidates = []

    
    # CONFIGURATION ET INITIALISATION
   

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
            logger.warning(" Clé API SerpAPI non trouvée. Ajoutez SERPAPI_KEY dans config.env")

    def _setup_llm_prompt(self):
        """Configure le prompt pour l'extraction LLM des métadonnées"""
        self.llm_prompt = """
        Analysez le contenu suivant et extrayez les informations demandées.
        
        Contenu: {content}
        Titre: {title}
        Date de publication: {published_date}
        
        Veuillez fournir UNIQUEMENT un JSON valide avec ces clés :
        - meta_title: Titre optimisé SEO (max 100 caractères)
        - meta_description: Description SEO optimisée basée sur le titre et sous-titre (max 130 caractères)
        - subtitle: Sous-titre de l'opportunité (1-2 phrases) 
        - description: Description détaillée de l'opportunité (2-3 phrases)
        - slug: URL slug (minuscules, tirets)
        - regions: Liste des régions (choisir parmi: ["Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi", "Cabo Verde", "Cameroon", "Central African Republic", "Chad", "Comoros", "Congo", "Côte d'Ivoire", "DR Congo", "Djibouti", "Egypt", "Equatorial Guinea", "Eritrea", "Eswatini", "Ethiopia", "Gabon", "Guinea", "Guinea-Bissau", "Kenya", "Lesotho", "Liberia", "Libya", "Madagascar", "Malawi", "Mali", "Mauritania", "Mauritius", "Morocco", "Mozambique", "Namibia", "Niger", "Nigeria", "Rwanda", "Sao Tome & Principe", "Senegal", "Seychelles", "Sierra Leone", "Somalia", "South Africa", "South Sudan", "Sudan", "Tanzania", "Togo", "Tunisia", "Uganda", "Zambia", "Zimbabwe"])
        - sectors: Liste des secteurs (choisir parmi: ["Regulatory Tech", "Spatial Computing", "AgriTech", "Agribusiness", "Artificial Intelligence", "Banking", "Blockchain", "Business Process Outsourcing (BPO)", "CleanTech", "Creative", "Cryptocurrencies", "Cybersecurity & Digital ID", "Data Aggregation", "Debt Management", "DeepTech", "Design & Applied Arts", "Digital & Interactive", "E-commerce and Retail", "Economic Development", "EdTech", "Energy", "Environmental Social Governance (ESG)", "FinTech", "Gaming", "HealthTech", "InsurTech", "Logistics", "ManuTech", "Manufacturing", "Media & Communication", "Mobility and Transportation", "Performing & Visual Arts", "Sector Agnostic", "Sport Management", "Sustainability", "Technology", "Tourism Innovation", "Transformative Digital Technologies", "Wearables"])
        - stages: Liste des étapes (choisir parmi: ["Not Applicable", "Pre-Series A", "Pre-seed", "Seed", "Series A", "Series B", "Series C", "Series D", "Series E", "Series F", "Stage Agnostic"])
        - categories: Liste des catégories (choisir parmi: ["Accelerator", "Bootcamp", "Competition", "Conference", "Event", "Funding Opportunity", "Hackathon", "Incubator", "Other", "Summit"])
        - draft_summary: Objet structuré avec:
          - introduction: Introduction générale (1 paragraphe)
          - details: Array d'objets avec "heading" et "text" pour chaque section détaillée
          - closing: Conclusion avec informations pratiques
        - main_image_alt: Texte alternatif pour l'image principale
        - organizer_logo_alt: Texte alternatif pour le logo de l'organisateur (ou null si pas d'organisateur)
        - extracted_published_date: Date de publication extraite du contenu (format ISO 8601 ou null)
        - extracted_deadline: Date limite d'application extraite du contenu (format texte lisible ou null)
        - organization_name: Identifie précisément le nom de l'organisation responsable ou associée à l'opportunité décrite dans le contenu. Ne retourne que le nom officiel de l'organisation (par exemple : "Milken Institute and Motsepe Foundation"). Si aucune organisation n'est clairement identifiable, retourne "null". Il faut analyser bien le contenu pour trouver le nom de l'organisation qui lance ou soutient l'initiative décrite.
        - organization_website: Site web de l'organisation (ou null si non trouvé)
        - organization_logo: URL du logo de l'organisation (ou null si non trouvé)
        - serpapi_enhanced: false (sera mis à jour après enrichissement)
        """

    
    # RÉCUPÉRATION DE CONTENU WEB
    

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
        """Récupère le contenu d'une page avec Playwright"""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until='networkidle')
                content = page.content()
                browser.close()
                return content
        except Exception as e:
            logger.error(f"Erreur Playwright pour {url}: {e}")
            return None
    
    
    # EXTRACTION ET ANALYSE DES ARTICLES
    
    def extract_article_links(self, html_content, base_url):
        """Extrait les liens des articles depuis la page de liste"""
        soup = BeautifulSoup(html_content, 'html.parser')
        links = []
        
        # Patterns génériques pour différents sites
        article_selectors = [
            'article a', '.post-title a', '.entry-title a', 'h2 a', 'h3 a',
            '.entry-header a', '.post-header a', '.blog-post a',
            '.post-item a', '.opportunity-item a', '.entry a',
            'article h1 a', 'article h2 a', 'article h3 a',
            '.post a[href*="/"]', '.entry a[href*="/"]'
        ]
        
        for selector in article_selectors:
            elements = soup.select(selector)
            for element in elements:
                href = element.get('href')
                if href and not href.startswith('#'):
                    full_url = urljoin(base_url, href)
                    
                    # Filtrage des liens non pertinents
                    exclude_patterns = [
                        'facebook.com', 'twitter.com', 'linkedin.com', 'instagram.com',
                        'youtube.com', 'pinterest.com', 'telegram.me', 'whatsapp.com',
                        'mailto:', 'tel:', '#', 'javascript:',
                        '/sharer/', '/share', '/sharing',
                        'category/', 'tag/', 'author/', 'page/',
                        'contact', 'about', 'privacy', 'terms', 'cookies',
                        'wp-content', 'wp-admin', 'wp-login',
                        '.jpg', '.png', '.gif', '.pdf', '.doc'
                    ]
                    
                    should_exclude = any(pattern in full_url.lower() for pattern in exclude_patterns)
                    
                    # Vérifier que c'est bien un article du même domaine
                    base_domain = urlparse(base_url).netloc
                    link_domain = urlparse(full_url).netloc
                    is_same_domain = base_domain in link_domain or link_domain in base_domain
                    
                    if not should_exclude and is_same_domain and full_url not in links:
                        url_path = urlparse(full_url).path
                        if len(url_path.split('/')) >= 3:
                            links.append(full_url)
        
        # Dédupliquer et trier
        unique_links = list(set(links))
        unique_links.sort(key=len, reverse=True)
        
        logger.info(f"Trouvé {len(unique_links)} liens d'articles valides après filtrage")
        return unique_links[:15]

    def extract_article_data(self, url):
        """Extrait les données d'un article spécifique (MODIFIÉE pour stocker le soup)"""
        logger.info(f"Extraction de: {url}")
        
        # NOUVEAU: Stocker l'URL actuelle pour résoudre les liens relatifs
        self._current_article_url = url
        
        html_content = self.get_page_content_static(url)
        if not html_content:
            html_content = self.get_page_content_dynamic(url)
            
        if not html_content:
            return None
            
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # NOUVEAU: Stocker le soup pour l'extraction de liens
        self._current_article_soup = soup
        
        data = {
            'url': url,
            'title': None,
            'published_date': None,
            'deadline': None,
            'content': None,
            'description': None,
            'soup': soup
        }
        
        # Extraction du titre
        title_selectors = [
            'h1.entry-title', 'h1.post-title', 'h1.page-title', 'h1',
            '.entry-title', '.post-title', 'title'
        ]
        
        for selector in title_selectors:
            title_elem = soup.select_one(selector)
            if title_elem:
                data['title'] = title_elem.get_text(strip=True)
                break
        
        # Extraction de la description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            data['description'] = meta_desc.get('content', '').strip()
        else:
            first_p = soup.find('p')
            if first_p:
                data['description'] = first_p.get_text(strip=True)[:200] + '...'
        
        # Extraction de la date de publication
        data['published_date'] = self._extract_published_date(soup)
        
        # Extraction du contenu principal
        data['content'] = self._extract_main_content(soup)
        
        # Extraction de la deadline
        if data['content']:
            data['deadline'] = self.extract_deadline(data['content'])
        
        return data
    def _extract_published_date(self, soup):
        """Extrait la date de publication de l'article"""
        date_selectors = [
            'time', '.published', '.post-date', '.entry-date', '.date',
            '.post-meta time', '.entry-meta time'
        ]
        
        for selector in date_selectors:
            date_elem = soup.select_one(selector)
            if date_elem:
                datetime_attr = date_elem.get('datetime')
                if datetime_attr:
                    return datetime_attr
                
                date_text = date_elem.get_text(strip=True)
                if date_text and re.search(r'\d{4}', date_text):
                    return date_text
        
        # Si pas trouvé, chercher dans le texte
        full_text = soup.get_text()
        date_patterns = [
            r'published[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
            r'posted[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
            r'(\w+\s+\d{1,2},?\s+\d{4})',
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, full_text.lower())
            if match:
                potential_date = match.group(1).strip()
                if any(month in potential_date.lower() for month in [
                    'january', 'february', 'march', 'april', 'may', 'june',
                    'july', 'august', 'september', 'october', 'november', 'december'
                ]):
                    return potential_date
        
        return None

    def _extract_main_content(self, soup):
        """Extrait le contenu principal de l'article"""
        content_selectors = [
            '.entry-content', '.post-content', '.content', '.post-body',
            'article .content', '.single-content', '.post-text'
        ]
        
        content_elem = None
        for selector in content_selectors:
            content_elem = soup.select_one(selector)
            if content_elem:
                break
        
        if content_elem:
            # Supprimer les éléments indésirables
            for unwanted in content_elem.find_all(['script', 'style', 'nav', 'footer', '.social-share']):
                unwanted.decompose()
            
            return content_elem.get_text(strip=True)
        else:
            return soup.get_text(strip=True)

    def extract_deadline(self, content):
        """Extrait la deadline du contenu"""
        content_lower = content.lower()
        
        deadline_patterns = [
            r'application deadline[:\s]*([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?,?\s+\d{4})',
            r'deadline[:\s]*([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?,?\s+\d{4})',
            r'apply by[:\s]*([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?,?\s+\d{4})',
            r'applications?.*?close[s]?.*?([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?,?\s+\d{4})',
            r'deadline[:\s]*(\d{1,2}(?:th|st|nd|rd)?\s+[a-z]+\s+\d{4})',
            r'until[:\s]*([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?,?\s+\d{4})',
            r'application deadline:\s*([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?,?\s+\d{4})',
        ]
        
        for pattern in deadline_patterns:
            match = re.search(pattern, content_lower)
            if match:
                potential_deadline = match.group(1).strip()
                potential_deadline = re.sub(r'(\d+)(?:th|st|nd|rd)', r'\1', potential_deadline)
                
                if self.is_valid_date(potential_deadline):
                    return potential_deadline
        
        return None

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
        has_day = re.search(r'\d{1,2}', date_str)
        
        return has_month and (has_year or has_day)
     
    def extract_and_validate_organization_info_from_content(self, content, title, organization_name):
        """
        NOUVELLE VERSION AMÉLIORÉE: Extrait le site web de l'organisation depuis le contenu ET les liens HTML de l'article
        """
        try:
            logger.info(" Extraction du site web d'organisation depuis le contenu et les liens...")
            
            if not content:
                return {'content_extraction': False, 'organization_website': None, 'organization_logo': None}
            
            # ÉTAPE 1: Extraire les URLs depuis le texte brut (méthode améliorée)
            text_urls = self._extract_urls_from_text(content, organization_name)
            
            # ÉTAPE 2: Extraire les liens depuis le HTML de l'article (méthode améliorée)
            html_urls = self._extract_urls_from_article_html(content, title, organization_name)
            
            # Combiner toutes les URLs trouvées
            found_urls = text_urls + html_urls
            
            # NOUVEAU: Log détaillé des URLs trouvées
            if found_urls:
                logger.info(f" URLs trouvées avant validation:")
                for i, url in enumerate(set(found_urls), 1):
                    logger.info(f"   {i}. {url}")
            
            # Scoring et sélection de la meilleure URL
            if found_urls:
                scored_urls = []
                
                for url in set(found_urls):  # Dédupliquer
                    # NOUVEAU: Validation stricte avant scoring
                    if not self._is_valid_organization_website_candidate(url):
                        logger.debug(f" URL candidat rejetée (validation candidat): {url}")
                        continue
                    
                    score = self._score_organization_website_candidate(url, organization_name, content)
                    scored_urls.append((url, score))
                    logger.info(f" URL candidat scorée (score: {score:.2f}): {url}")
                
                if not scored_urls:
                    logger.warning(" Aucune URL valide après scoring")
                    return {'content_extraction': False, 'organization_website': None, 'organization_logo': None}
                
                # Trier par score décroissant
                scored_urls.sort(key=lambda x: x[1], reverse=True)
                
                # Tester les URLs par ordre de score avec validation stricte
                for url, score in scored_urls:
                    logger.info(f" Test URL candidat (score: {score:.2f}): {url}")
                    
                    # VALIDATION STRICTE: Vérifier que ce n'est pas un PDF
                    if self.validate_website(url):
                        logger.info(f" URL organisation validée depuis le contenu: {url}")
                        
                        # Extraire le logo depuis ce site
                        logo_url = None
                        try:
                            logo_url = self.extract_logo_from_website(url)
                            if logo_url:
                                logger.info(f" Logo extrait depuis le site de l'organisation: {logo_url}")
                        except Exception as e:
                            logger.debug(f"Erreur extraction logo depuis {url}: {e}")
                        
                        return {
                            'content_extraction': True,
                            'organization_website': url,
                            'organization_logo': logo_url
                        }
                    else:
                        logger.warning(f" URL candidat rejetée (validation finale): {url}")
            
            logger.info(" Aucun site web d'organisation valide trouvé dans le contenu")
            return {'content_extraction': False, 'organization_website': None, 'organization_logo': None}
            
        except Exception as e:
            logger.debug(f"Erreur lors de l'extraction depuis le contenu: {e}")
            return {'content_extraction': False, 'organization_website': None, 'organization_logo': None}

    def _extract_urls_from_text(self, content, organization_name):
        """NOUVELLE VERSION AMÉLIORÉE: Extrait les URLs depuis le texte brut"""
        url_extraction_patterns = [
            # Pattern amélioré pour "For more information visit"
            r'for\s+more\s+information[,:\s]*visit[:\s]+(?:the\s+)?(?:official\s+)?(?:website\s+)?(?:of\s+)?(?:the\s+)?([\w\s]+?)[:\s]*(https?://[^\s\)]+)',
            
            # NOUVEAU: Pattern pour "For more information, visit [Organization]" avec lien
            r'for\s+more\s+information[,:\s]*visit\s+([\w\s]+?)(?:\s|$)',
            
            # Pattern pour "Visit the official webpage of" + organization + URL
            r'visit\s+the\s+official\s+webpage\s+of\s+([\w\s]+?)[:\s]*(https?://[^\s\)]+)',
            
            # Pattern pour "Visit" + organization name + URL
            r'visit\s+(?:the\s+)?([\w\s]*?)[:\s]*(https?://[^\s\)]+)',
            
            # Pattern pour organization name suivi d'une URL
            rf'{re.escape(organization_name or "")}\s*[:\-–]?\s*(https?://[^\s\)]+)' if organization_name else None,
            
            # URLs génériques dans des contextes d'information
            r'(?:website|site|page|portal)[:\s]+(https?://[^\s\)]+)',
            r'(?:more|additional)\s+(?:information|details)[:\s]+.*?(https?://[^\s\)]+)',
            
            # NOUVEAU: Pattern pour extraire toutes les URLs dans des paragraphes d'information
            r'(?:information|details|visit|website|apply)[^.]*?(https?://[^\s\)]+)',
            
            # URLs isolées qui semblent être des sites officiels
            r'\b(https?://(?:www\.)?[a-zA-Z0-9-]+\.(?:org|edu|gov|com|net)/[^\s\)]*)\b',
            
            # "Apply at" ou "Register at" + URL
            r'(?:apply|register|submit)\s+(?:at|on|via)[:\s]+(https?://[^\s\)]+)',
        ]
        
        # Filtrer les patterns None
        url_extraction_patterns = [p for p in url_extraction_patterns if p is not None]
        
        found_urls = []
        content_lower = content.lower()
        
        # Extraction avec tous les patterns
        for pattern in url_extraction_patterns:
            matches = re.finditer(pattern, content_lower, re.IGNORECASE | re.DOTALL)
            for match in matches:
                # Déterminer quel groupe contient l'URL
                url = None
                if len(match.groups()) >= 2:
                    # Pattern avec organisation et URL
                    potential_url = match.group(2)
                    if potential_url and potential_url.startswith('http'):
                        url = potential_url
                elif len(match.groups()) == 1:
                    # Pattern avec seulement URL
                    potential_url = match.group(1)
                    if potential_url and potential_url.startswith('http'):
                        url = potential_url
                
                if url:
                    # Nettoyage de l'URL
                    url = re.sub(r'[.,;!?\)\]]+$', '', url)  # Supprimer la ponctuation de fin
                    
                    if self._is_valid_organization_website_candidate(url):
                        found_urls.append(url)
        
        return found_urls

    def _extract_urls_from_article_html(self, content, title, organization_name):
        """
        NOUVELLE VERSION AMÉLIORÉE: Extrait les URLs depuis les liens HTML de l'article original
        """
        found_urls = []
        
        try:
            # Récupérer l'article original pour analyser les liens HTML
            article_soup = getattr(self, '_current_article_soup', None)
            
            if not article_soup:
                logger.debug("Pas de soup HTML disponible pour extraire les liens")
                return found_urls
            
            # Chercher tous les liens dans l'article
            content_containers = article_soup.find_all(['div', 'article', 'section'], 
                                                    class_=re.compile(r'content|post|entry|article', re.I))
            
            if not content_containers:
                # Fallback: chercher dans tout le body
                content_containers = [article_soup.find('body')] if article_soup.find('body') else [article_soup]
            
            for container in content_containers:
                if not container:
                    continue
                    
                # Trouver tous les liens <a>
                links = container.find_all('a', href=True)
                
                for link in links:
                    href = link.get('href')
                    link_text = link.get_text(strip=True).lower()
                    
                    if not href or not self._is_valid_organization_website_candidate(href):
                        continue
                    
                    # Normaliser l'URL relative vers absolue si nécessaire
                    if href.startswith('/') or not href.startswith(('http://', 'https://')):
                        # Essayer de construire l'URL absolue
                        base_domain = self._extract_base_domain_from_current_url()
                        if base_domain:
                            if href.startswith('/'):
                                href = f"https://{base_domain}{href}"
                            else:
                                href = f"https://{base_domain}/{href}"
                    
                    # Vérifier si le lien semble être lié à l'organisation
                    is_org_related = self._is_link_organization_related(link_text, href, organization_name)
                    
                    if is_org_related:
                        logger.info(f"🔗 Lien organisation trouvé: '{link_text}' -> {href}")
                        found_urls.append(href)
            
            # NOUVEAU: Chercher des liens avec des textes spécifiques plus larges
            specific_link_patterns = [
                r'visit.*?official.*?website',
                r'more.*?information',
                r'official.*?page',
                r'learn.*?more',
                r'visit.*?website',
                r'visit.*?(?:here|link)',
                r'click.*?here',
                r'apply.*?(?:here|now)',
                r'register.*?(?:here|now)',
                rf'{re.escape(organization_name or "")}.*?website' if organization_name else None,
                # NOUVEAU: Pattern pour noms d'organisations même sans mot "website"
                rf'{re.escape(organization_name or "")}' if organization_name else None
            ]
            
            specific_link_patterns = [p for p in specific_link_patterns if p is not None]
            
            for container in content_containers:
                if not container:
                    continue
                    
                links = container.find_all('a', href=True)
                
                for link in links:
                    href = link.get('href')
                    link_text = link.get_text(strip=True).lower()
                    
                    if not href or not self._is_valid_organization_website_candidate(href):
                        continue
                    
                    # Vérifier les patterns spécifiques
                    for pattern in specific_link_patterns:
                        if re.search(pattern, link_text, re.IGNORECASE):
                            logger.info(f" Lien spécifique trouvé: '{link_text}' -> {href}")
                            found_urls.append(href)
                            break
            
        except Exception as e:
            logger.debug(f"Erreur extraction liens HTML: {e}")
        
        return found_urls

    def _is_link_organization_related(self, link_text, href, organization_name):
        """NOUVELLE VERSION AMÉLIORÉE: Détermine si un lien est lié à l'organisation"""
        if not link_text:
            return False
        
        # Mots-clés qui indiquent un lien vers l'organisation
        org_keywords = [
            'visit', 'website', 'official', 'page', 'portal', 'site',
            'more information', 'learn more', 'details', 'homepage',
            'organization', 'foundation', 'institute', 'company',
            'fellowship', 'society', 'association', 'program'  # NOUVEAU: mots-clés spécifiques
        ]
        
        # Vérifier si le texte du lien contient des mots-clés organisationnels
        has_org_keywords = any(keyword in link_text for keyword in org_keywords)
        
        # Vérifier si le nom d'organisation apparaît dans le lien
        has_org_name = False
        if organization_name:
            org_words = re.findall(r'\b\w+\b', organization_name.lower())
            org_words = [word for word in org_words if len(word) > 2]
            has_org_name = any(word in link_text for word in org_words)
        
        # NOUVEAU: Vérifier si c'est un nom d'organisation directement dans le lien
        # Exemples: "Amelia Earhart Fellowship", "East Africa Law Society"
        looks_like_org_name = (
            len(link_text.split()) >= 2 and  # Au moins 2 mots
            link_text[0].isupper() and  # Commence par une majuscule
            any(indicator in link_text for indicator in ['fellowship', 'society', 'foundation', 'institute', 'organization', 'association'])
        )
        
        # Vérifier si l'URL semble être institutionnelle
        has_institutional_domain = any(tld in href.lower() for tld in ['.org', '.edu', '.gov', '.foundation'])
        
        return has_org_keywords or has_org_name or looks_like_org_name or has_institutional_domain

    def _extract_base_domain_from_current_url(self):
        """Extrait le domaine de base de l'URL actuelle pour résoudre les liens relatifs"""
        try:
            current_url = getattr(self, '_current_article_url', '')
            if current_url:
                parsed = urlparse(current_url)
                return parsed.netloc
        except:
            pass
        return None

    def _is_valid_organization_website_candidate(self, url):
        """NOUVELLE VERSION AMÉLIORÉE: Valide qu'une URL est un candidat valide pour un site d'organisation"""
        if not url or len(url) < 10:
            return False
        
        url_lower = url.lower()
        
        # FILTRAGE STRICT: Exclure les PDFs et autres fichiers
        invalid_extensions = [
            '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
            '.zip', '.rar', '.tar', '.gz', '.7z',
            '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.ico',
            '.mp4', '.avi', '.mov', '.mp3', '.wav'
        ]
        
        for ext in invalid_extensions:
            if ext in url_lower:
                logger.debug(f"URL rejetée (contient {ext}): {url}")
                return False
        
        # Exclure les réseaux sociaux et plateformes non-officielles
        excluded_domains = [
            'facebook.com', 'twitter.com', 'linkedin.com', 'instagram.com',
            'youtube.com', 'pinterest.com', 'telegram.me', 'whatsapp.com',
            'reddit.com', 'quora.com', 'medium.com'
        ]
        
        for domain in excluded_domains:
            if domain in url_lower:
                logger.debug(f"URL rejetée (domaine exclu {domain}): {url}")
                return False
        
        # Exclure les liens internes du site de scraping
        scraping_domains = ['opportunitiesforafricans.com', 'msmeafricaonline.com', 'opportunitydesk.org']
        for domain in scraping_domains:
            if domain in url_lower:
                logger.debug(f"URL rejetée (site de scraping): {url}")
                return False
        
        # Vérifier que c'est une URL HTTP/HTTPS valide
        if not url.startswith(('http://', 'https://')):
            return False
        
        # Vérifier la structure de l'URL
        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                return False
        except:
            return False
        
        return True

    def _score_organization_website_candidate(self, url, organization_name, content):
        """NOUVELLE VERSION AMÉLIORÉE: Score un candidat de site web d'organisation"""
        if not url:
            return 0.0
        
        score = 0.0
        url_lower = url.lower()
        
        # Score de base pour un site web valide
        score += 0.1
        
        # Bonus pour domaines institutionnels
        institutional_tlds = ['.org', '.edu', '.gov', '.foundation', '.institute']
        for tld in institutional_tlds:
            if tld in url_lower:
                score += 0.3
                break
        
        # Bonus si le nom d'organisation apparaît dans l'URL
        if organization_name:
            org_words = re.findall(r'\b\w+\b', organization_name.lower())
            org_words = [word for word in org_words if len(word) > 3]  # Mots de plus de 3 caractères
            
            url_domain = urlparse(url).netloc.lower()
            for word in org_words:
                if word in url_domain:
                    score += 0.4
                    break
        
        # Bonus pour indicateurs dans l'URL
        official_indicators = ['official', 'main', 'home', 'www']
        for indicator in official_indicators:
            if indicator in url_lower:
                score += 0.1
                break
        
        # NOUVEAU: Bonus si l'URL est mentionnée dans un contexte approprié dans le contenu
        if content:
            content_lower = content.lower()
            
            # Patterns de contexte positif
            positive_contexts = [
                f'visit.*?{re.escape(url)}',
                f'more information.*?{re.escape(url)}',
                f'official.*?{re.escape(url)}',
                f'website.*?{re.escape(url)}'
            ]
            
            for pattern in positive_contexts:
                if re.search(pattern, content_lower, re.IGNORECASE):
                    score += 0.2
                    break
        
        # Malus pour URLs suspectes
        suspicious_patterns = ['redirect', 'proxy', 'shortened', 'bit.ly', 'tinyurl']
        for pattern in suspicious_patterns:
            if pattern in url_lower:
                score -= 0.3
                break
        
        return min(max(score, 0.0), 1.0)  # Normaliser entre 0 et 1

    # VALIDATION AMÉLIORÉE
    def validate_website(self, website_url):
        """NOUVELLE VERSION AMÉLIORÉE: Valide qu'une URL de site web est accessible et n'est pas un PDF"""
        if not website_url:
            return False
        
        # FILTRAGE STRICT: Vérifier que ce n'est pas un PDF ou autre fichier
        invalid_extensions = [
            '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', 
            '.zip', '.rar', '.tar', '.gz', '.7z',
            '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.ico',
            '.mp4', '.avi', '.mov', '.mp3', '.wav', '.txt'
        ]
        
        # Vérification dans l'URL complète (pas seulement la fin)
        website_url_lower = website_url.lower()
        for ext in invalid_extensions:
            if ext in website_url_lower:
                logger.debug(f"URL rejetée (contient fichier {ext}): {website_url}")
                return False
        
        # NOUVEAU: Vérification plus stricte des patterns de fichiers
        file_patterns = [
            r'\.pdf(?:\?|$|#)',  # .pdf suivi de ?, fin de ligne, ou #
            r'\.doc[x]?(?:\?|$|#)',
            r'\.xls[x]?(?:\?|$|#)',
            r'\.ppt[x]?(?:\?|$|#)',
            r'/wp-content/uploads/.*\.(pdf|doc|docx|xls|xlsx)',  # WordPress uploads
            r'/downloads?/.*\.(pdf|doc|docx|xls|xlsx)',  # Dossiers de téléchargement
            r'/files?/.*\.(pdf|doc|docx|xls|xlsx)',  # Dossiers de fichiers
            r'/attachments?/.*\.(pdf|doc|docx|xls|xlsx)'  # Pièces jointes
        ]
        
        for pattern in file_patterns:
            if re.search(pattern, website_url_lower):
                logger.debug(f"URL rejetée (pattern fichier): {website_url}")
                return False
        
        try:
            if not website_url.startswith(('http://', 'https://')):
                website_url = 'https://' + website_url
            
            # Faire une requête HEAD pour vérifier sans télécharger le contenu
            response = self.session.head(website_url, timeout=10, allow_redirects=True)
            
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '').lower()
                
                # VÉRIFICATION STRICTE: Rejeter explicitement les PDFs
                if any(pdf_type in content_type for pdf_type in ['application/pdf', 'pdf']):
                    logger.debug(f"URL rejetée (Content-Type PDF): {website_url}")
                    return False
                
                # Rejeter autres types de fichiers
                invalid_content_types = [
                    'application/msword',
                    'application/vnd.openxmlformats-officedocument',
                    'application/vnd.ms-excel',
                    'application/vnd.ms-powerpoint',
                    'application/zip',
                    'application/x-rar',
                    'image/',
                    'video/',
                    'audio/'
                ]
                
                for invalid_type in invalid_content_types:
                    if invalid_type in content_type:
                        logger.debug(f"URL rejetée (Content-Type invalide {invalid_type}): {website_url}")
                        return False
                
                # Accepter les types de contenu web valides
                valid_content_types = ['text/html', 'application/xhtml', 'text/plain']
                if any(valid_type in content_type for valid_type in valid_content_types):
                    return True
                
                # Si pas de content-type spécifique mais status 200, on accepte avec prudence
                if not content_type or content_type == 'application/octet-stream':
                    # NOUVEAU: Vérification additionnelle avec GET partiel
                    try:
                        partial_response = self.session.get(website_url, timeout=5, stream=True)
                        if partial_response.status_code == 200:
                            # Lire les premiers bytes pour détecter les fichiers binaires
                            first_bytes = next(partial_response.iter_content(chunk_size=1024), b'')
                            
                            # Signatures de fichiers PDF
                            if first_bytes.startswith(b'%PDF'):
                                logger.debug(f"URL rejetée (signature PDF détectée): {website_url}")
                                return False
                            
                            # Signatures de fichiers Office
                            office_signatures = [b'PK\x03\x04', b'\xd0\xcf\x11\xe0']  # ZIP-based et OLE
                            if any(first_bytes.startswith(sig) for sig in office_signatures):
                                logger.debug(f"URL rejetée (signature Office détectée): {website_url}")
                                return False
                            
                            # Si les premiers bytes ressemblent à du HTML
                            if b'<html' in first_bytes[:500].lower() or b'<!doctype' in first_bytes[:500].lower():
                                return True
                            
                            # Si ça contient du texte lisible, on accepte
                            try:
                                first_text = first_bytes.decode('utf-8', errors='ignore')
                                if len(first_text) > 50 and any(char.isalpha() for char in first_text):
                                    return True
                            except:
                                pass
                    
                    except Exception as e:
                        logger.debug(f"Erreur vérification partielle pour {website_url}: {e}")
                    
                    return False
                    
                return False
            
            # Essayer avec GET si HEAD échoue
            elif response.status_code == 405:  # Method Not Allowed
                try:
                    get_response = self.session.get(website_url, timeout=5, stream=True)
                    if get_response.status_code == 200:
                        content_type = get_response.headers.get('content-type', '').lower()
                        
                        # Même vérification que pour HEAD
                        if 'application/pdf' in content_type or 'pdf' in content_type:
                            logger.debug(f"URL rejetée (GET Content-Type PDF): {website_url}")
                            return False
                        
                        return any(valid_type in content_type for valid_type in ['text/html', 'application/xhtml'])
                except:
                    return False
            
            return False
            
        except Exception as e:
            logger.debug(f"Erreur validation website {website_url}: {e}")
            return False
    # EXTRACTION DE LOGOS - 11 STRATÉGIES AVANCÉES
    

    def extract_logo_from_website(self, website_url):
        """Extraction complète de logos avec 11 stratégies (10 statiques + 1 dynamique)"""
        try:
            logger.info(f" Extraction avancée du logo depuis: {website_url}")
            
            if not website_url.startswith(('http://', 'https://')):
                website_url = 'https://' + website_url
            
            # Réinitialiser les candidats pour cette extraction
            self.logo_candidates = []
            
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
            
            # Application des 10 stratégies statiques
            static_strategies = [
                (self._find_logo_by_alt_attribute, header_elements, website_url),      # Stratégie 1
                (self._find_logo_svg_elements, header_elements, website_url),          # Stratégie 2
                (self._find_logo_in_containers, header_elements, website_url),         # Stratégie 3
                (self._find_logo_by_src_content, header_elements, website_url),        # Stratégie 4
                (self._find_logo_by_data_attributes, header_elements, website_url),    # Stratégie 5
                (self._find_logo_by_context_analysis, header_elements, website_url),   # Stratégie 6
                (self._find_logo_intelligent_fallback, header_elements, website_url),  # Stratégie 7
                (self._find_logo_favicon_strategy, soup, website_url),                 # Stratégie 8 (améliorée)
                (self._find_logo_global_images_strategy, soup, website_url),           # Stratégie 9 (nouvelle)
                (self._find_logo_ai_analysis_strategy, website_url)                    # Stratégie 10 (nouvelle)
            ]
            
            for i, (strategy, *args) in enumerate(static_strategies, 1):
                logo_url = strategy(*args)
                if logo_url:
                    return logo_url
            
            # Stratégie 11: Dynamique avec Playwright (améliorée)
            logger.info("🎭 Tentative avec la stratégie dynamique (Playwright)...")
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
            '.main-header', '.page-header', '#masthead', '.masthead',
            '.header-wrapper', '.site-branding', '.logo-container', '.brand-container',
            'a[class*="logo" i]', 'a[id*="logo" i]', 'a[class*="brand" i]',
            'a[href="/"]', 'a[href="./"]', 'a[href="#"]'
        ]
        
        header_elements = []
        for selector in header_selectors:
            elements = soup.select(selector)
            header_elements.extend(elements)
        
        # Ajouter les premiers éléments du body qui peuvent contenir des logos
        body = soup.find('body')
        if body:
            first_divs = body.find_all('div', limit=5)
            for div in first_divs:
                div_class = ' '.join(div.get('class', [])).lower()
                div_id = div.get('id', '').lower()
                
                if any(keyword in div_class or keyword in div_id for keyword in 
                       ['header', 'top', 'nav', 'logo', 'brand', 'site']):
                    header_elements.append(div)
        
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
            
            for img in images:
                alt_text = img.get('alt', '').lower()
                src = img.get('src')
                
                if any(keyword in alt_text for keyword in logo_keywords):
                    if src:
                        logo_url = self._normalize_logo_url(src, base_url)
                        if self._is_valid_logo_candidate(logo_url, img, confidence_boost=0.4):
                            logger.info(f" STRATÉGIE 1 - Logo trouvé par alt='{img.get('alt')}': {logo_url}")
                            return logo_url
                        else:
                            self._add_logo_candidate(logo_url, img, 0.4, "Stratégie 1 - Alt attribute")
        
        return None

    def _find_logo_svg_elements(self, header_elements, base_url):
        """STRATÉGIE 2: Recherche d'éléments SVG avec classes ou IDs logo"""
        logger.debug(" STRATÉGIE 2: Recherche SVG avec classes logo")
        
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
                        else:
                            self._add_logo_candidate(logo_url, img, 0.3, "Stratégie 3 - Container")
                    
                    # Container lui-même est une image
                    if container.name == 'img' and container.get('src'):
                        logo_url = self._normalize_logo_url(container.get('src'), base_url)
                        if self._is_valid_logo_candidate(logo_url, container, confidence_boost=0.3):
                            logger.info(f" STRATÉGIE 3 - Container image logo: {logo_url}")
                            return logo_url
                        else:
                            self._add_logo_candidate(logo_url, container, 0.3, "Stratégie 3 - Container image")
        
        return None

    def _find_logo_by_src_content(self, header_elements, base_url):
        """STRATÉGIE 4: Images avec src contenant 'logo'"""
        logger.debug(" STRATÉGIE 4: Recherche par src contenant 'logo'")
        
        for header in header_elements:
            images = header.find_all('img', src=True)
            
            for img in images:
                src = img.get('src', '').lower()
                
                if 'logo' in src and not any(exclude in src for exclude in ['icon', 'avatar', 'profile']):
                    logo_url = self._normalize_logo_url(img.get('src'), base_url)
                    if self._is_valid_logo_candidate(logo_url, img, confidence_boost=0.2):
                        logger.info(f" STRATÉGIE 4 - Logo par src contenant 'logo': {logo_url}")
                        return logo_url
                    else:
                        self._add_logo_candidate(logo_url, img, 0.2, "Stratégie 4 - Src logo")
        
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
                                else:
                                    self._add_logo_candidate(logo_url, img, 0.2, f"Stratégie 5 - {attr_name}")
        
        return None

    def _find_logo_by_context_analysis(self, header_elements, base_url):
        """STRATÉGIE 6: Analyse contextuelle - images avec liens/textes indicateurs + liens avec logos"""
        logger.debug(" STRATÉGIE 6: Analyse contextuelle avancée")
        
        context_indicators = ['home', 'accueil', 'homepage', 'site', 'company', 'organization']
        
        for header in header_elements:
            home_links = header.find_all('a', href=True)
            
            for link in home_links:
                href = link.get('href', '').lower()
                link_text = link.get_text(strip=True).lower()
                link_class = ' '.join(link.get('class', [])).lower()
                link_id = link.get('id', '').lower()
                
                # Conditions pour identifier un lien "home" ou "logo"
                is_home_link = (
                    href in ['/', '#', '', './'] or 
                    any(indicator in href for indicator in ['home', 'index']) or
                    any(indicator in link_text for indicator in context_indicators) or
                    any(logo_word in link_class or logo_word in link_id for logo_word in ['logo', 'brand'])
                )
                
                if is_home_link:
                    # Chercher une image dans le lien
                    img = link.find('img')
                    if img and img.get('src'):
                        logo_url = self._normalize_logo_url(img.get('src'), base_url)
                        if self._is_valid_logo_candidate(logo_url, img, confidence_boost=0.2):
                            logger.info(f" STRATÉGIE 6 - Logo contextuel (lien avec image): {logo_url}")
                            return logo_url
                        else:
                            self._add_logo_candidate(logo_url, img, 0.2, "Stratégie 6 - Contextuel")
                    
                    # Chercher un SVG dans le lien
                    svg = link.find('svg')
                    if svg:
                        svg_url = self._extract_svg_as_logo(svg, base_url)
                        if svg_url:
                            logger.info(f" STRATÉGIE 6 - SVG contextuel (lien avec SVG): {svg_url}")
                            return svg_url
        
        return None

    def _find_logo_intelligent_fallback(self, header_elements, base_url):
        """STRATÉGIE 7: Fallback intelligent - première image significative dans le header"""
        logger.debug(" STRATÉGIE 7: Fallback intelligent dans header")
        
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
                        if w < 30 or h < 20 or w/h > 10 or h/w > 3:
                            continue
                    except:
                        pass
                
                logo_url = self._normalize_logo_url(img.get('src'), base_url)
                if self._is_valid_logo_candidate(logo_url, img, confidence_boost=0):
                    logger.info(f" STRATÉGIE 7 - Logo fallback intelligent: {logo_url}")
                    return logo_url
                else:
                    self._add_logo_candidate(logo_url, img, 0.1, "Stratégie 7 - Fallback")
        
        return None

    def _find_logo_favicon_strategy(self, soup, base_url):
        """STRATÉGIE 8: Extraction du favicon comme logo de secours (AMÉLIORÉE)"""
        logger.debug(" STRATÉGIE 8: Extraction du favicon (améliorée)")
        
        # NOUVEAU: Tester /favicon.ico en premier, même s'il n'est pas déclaré
        default_favicon = urljoin(base_url, '/favicon.ico')
        if self.validate_logo_image(default_favicon):
            logger.info(f" STRATÉGIE 8 - Favicon par défaut trouvé (/favicon.ico): {default_favicon}")
            return default_favicon
        
        favicon_selectors = [
            'link[rel="icon"]', 'link[rel="shortcut icon"]', 
            'link[rel="apple-touch-icon"]', 'link[rel="apple-touch-icon-precomposed"]',
            'link[rel="mask-icon"]', 'link[rel="fluid-icon"]'
        ]
        
        favicon_candidates = []
        
        for selector in favicon_selectors:
            favicons = soup.select(selector)
            for favicon in favicons:
                href = favicon.get('href')
                if href:
                    favicon_url = self._normalize_logo_url(href, base_url)
                    
                    # Scoring par taille
                    sizes = favicon.get('sizes', '')
                    size_score = 0.1
                    
                    if sizes and 'x' in sizes:
                        try:
                            dimensions = sizes.split('x')
                            width = int(dimensions[0])
                            height = int(dimensions[1]) if len(dimensions) > 1 else width
                            
                            if width >= 64 and height >= 64:
                                size_score = 0.3
                            elif width >= 32 and height >= 32:
                                size_score = 0.2
                        except:
                            pass
                    
                    favicon_candidates.append((favicon_url, size_score, selector))
        
        # Trier par score décroissant
        favicon_candidates.sort(key=lambda x: x[1], reverse=True)
        
        # Essayer chaque candidat
        for favicon_url, score, selector in favicon_candidates:
            if self.validate_logo_image(favicon_url):
                logger.info(f" STRATÉGIE 8 - Favicon trouvé via {selector}: {favicon_url}")
                return favicon_url
        
        return None

    def _find_logo_global_images_strategy(self, soup, base_url):
        """STRATÉGIE 9: Fallback sur les premières images globales significatives (NOUVELLE)"""
        logger.debug(" STRATÉGIE 9: Fallback sur images globales")
        
        # Chercher dans tout le document, pas seulement le header
        all_images = soup.find_all('img', src=True)
        
        for img in all_images[:10]:  # Limiter à 10 pour éviter de traiter trop d'images
            src = img.get('src', '').lower()
            alt = img.get('alt', '').lower()
            
            # Filtres d'exclusion stricts
            exclude_patterns = [
                'icon', 'arrow', 'menu', 'search', 'close', 'burger', 'hamburger',
                'facebook', 'twitter', 'linkedin', 'instagram', 'youtube', 'social',
                'banner', 'ad', 'advertisement', 'avatar', 'profile', 'user',
                'gallery', 'photo', 'pic', 'image', 'thumb', 'preview',
                'button', 'background', 'bg', 'pattern', 'texture'
            ]
            
            # Si l'image contient des mots-clés d'exclusion, ignorer
            if any(pattern in src or pattern in alt for pattern in exclude_patterns):
                continue
            
            # Bonus pour mots-clés logo
            logo_indicators = ['logo', 'brand', 'company', 'organization', 'site']
            has_logo_indicator = any(indicator in src or indicator in alt for indicator in logo_indicators)
            
            # Vérifier les dimensions si disponibles
            width = img.get('width')
            height = img.get('height')
            
            reasonable_dimensions = True
            if width and height:
                try:
                    w, h = int(width), int(height)
                    # Dimensions raisonnables pour un logo
                    if w < 30 or h < 20 or w > 800 or h > 400 or w/h > 8 or h/w > 3:
                        reasonable_dimensions = False
                except:
                    pass
            
            if reasonable_dimensions:
                logo_url = self._normalize_logo_url(img.get('src'), base_url)
                confidence_boost = 0.15 if has_logo_indicator else 0.05
                
                if self._is_valid_logo_candidate(logo_url, img, confidence_boost=confidence_boost):
                    logger.info(f" STRATÉGIE 9 - Logo global trouvé: {logo_url}")
                    return logo_url
                else:
                    self._add_logo_candidate(logo_url, img, confidence_boost, "Stratégie 9 - Global")
        
        return None

    def _find_logo_ai_analysis_strategy(self, base_url):
        """STRATÉGIE 10: Analyse AI/ML des candidats logos collectés (NOUVELLE)"""
        logger.debug(" STRATÉGIE 10: Analyse AI des candidats logos")
        
        if not self.logo_candidates:
            return None
        
        try:
            # Trier les candidats par score de confiance
            sorted_candidates = sorted(self.logo_candidates, key=lambda x: x['confidence'], reverse=True)
            
            # Analyser les 3 meilleurs candidats avec des heuristiques avancées
            for candidate in sorted_candidates[:3]:
                logo_url = candidate['url']
                
                # Analyse des caractéristiques de l'URL
                url_score = self._analyze_logo_url_features(logo_url)
                
                # Si disponible, analyse visuelle de l'image
                visual_score = self._analyze_logo_visual_features(logo_url)
                
                total_score = candidate['confidence'] + url_score + visual_score
                
                logger.debug(f" Candidat AI: {logo_url[:50]}... Score: {total_score:.2f}")
                
                # Seuil plus élevé pour cette stratégie
                if total_score > 0.6:
                    logger.info(f" STRATÉGIE 10 - Logo AI sélectionné: {logo_url}")
                    return logo_url
        
        except Exception as e:
            logger.debug(f"Erreur analyse AI: {e}")
        
        return None

    def _analyze_logo_url_features(self, logo_url):
        """Analyse les caractéristiques de l'URL pour détecter un logo"""
        if not logo_url:
            return 0
        
        score = 0
        url_lower = logo_url.lower()
        
        # Formats d'image appropriés pour les logos
        if any(ext in url_lower for ext in ['.svg', '.png']):
            score += 0.2
        elif any(ext in url_lower for ext in ['.jpg', '.jpeg', '.webp']):
            score += 0.1
        
        # Mots-clés dans le chemin
        if 'logo' in url_lower:
            score += 0.3
        if any(word in url_lower for word in ['brand', 'company', 'org']):
            score += 0.2
        
        # Structure de dossier typique
        if any(folder in url_lower for folder in ['/assets/', '/images/', '/img/', '/static/']):
            score += 0.1
        
        # Taille de fichier raisonnable (approximation par l'URL)
        if 'thumb' in url_lower or 'small' in url_lower:
            score -= 0.1
        if 'large' in url_lower or 'big' in url_lower:
            score -= 0.05
        
        return min(score, 0.5)  # Limiter à 0.5

    def _analyze_logo_visual_features(self, logo_url):
        """Analyse visuelle basique de l'image pour détecter un logo"""
        try:
            # Télécharger l'image
            response = self.session.get(logo_url, timeout=5, stream=True)
            if response.status_code != 200:
                return 0
            
            # Analyser avec PIL
            image = Image.open(io.BytesIO(response.content))
            width, height = image.size
            
            score = 0
            
            # Ratio d'aspect approprié pour un logo
            ratio = width / height if height > 0 else 0
            if 0.5 <= ratio <= 4:  # Logos généralement horizontaux ou carrés
                score += 0.2
            
            # Taille appropriée
            if 50 <= width <= 500 and 30 <= height <= 300:
                score += 0.2
            elif width < 50 or height < 30:
                score -= 0.1
            
            # Analyse de complexité (nombre de couleurs)
            if image.mode in ['RGB', 'RGBA']:
                colors = image.getcolors(maxcolors=256)
                if colors and len(colors) <= 10:  # Logos simples
                    score += 0.1
                elif colors and len(colors) > 50:  # Trop complexe
                    score -= 0.1
            
            return min(score, 0.3)  # Limiter à 0.3
            
        except Exception as e:
            logger.debug(f"Erreur analyse visuelle: {e}")
            return 0

    async def _find_logo_dynamic_strategy(self, website_url):
        """STRATÉGIE 11: Recherche dynamique avancée avec Playwright (AMÉLIORÉE)"""
        logger.debug(" STRATÉGIE 11: Recherche dynamique avancée avec Playwright")
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                # Attendre le chargement complet
                await page.goto(website_url, wait_until='networkidle')
                
                # NOUVEAU: Attendre le chargement des logos dynamiques
                try:
                    await page.wait_for_timeout(2000)  # 2 secondes supplémentaires
                    await page.wait_for_selector("img", timeout=3000)
                except:
                    pass
                
                # Chercher dans les éléments header
                header_selectors = ['header', '[class*="header"]', '[id*="header"]', 'nav', '[class*="navbar"]']
                
                for selector in header_selectors:
                    try:
                        header_elements = await page.query_selector_all(selector)
                        
                        for header in header_elements:
                            # Images avec alt/src contenant "logo"
                            img_elements = await header.query_selector_all('img[alt*="logo" i], img[src*="logo" i]')
                            
                            for img in img_elements:
                                src = await img.get_attribute("src")
                                if src:
                                    full_url = urljoin(website_url, src)
                                    if self.validate_logo_image(full_url):
                                        logger.info(f" STRATÉGIE 11 - Logo header trouvé: {full_url}")
                                        await browser.close()
                                        return full_url
                            
                            # SVG avec classe logo
                            svg_elements = await header.query_selector_all('svg[class*="logo" i], svg[id*="logo" i]')
                            
                            for svg in svg_elements:
                                svg_content = await svg.inner_html()
                                if svg_content and len(svg_content) > 50:
                                    svg_bytes = f'<svg>{svg_content}</svg>'.encode('utf-8')
                                    svg_base64 = base64.b64encode(svg_bytes).decode('utf-8')
                                    svg_url = f"data:image/svg+xml;base64,{svg_base64}"
                                    logger.info(f" STRATÉGIE 11 - SVG header trouvé: {svg_url[:100]}...")
                                    await browser.close()
                                    return svg_url
                            
                            # Liens contenant des logos
                            link_elements = await header.query_selector_all('a[href="/"], a[href="./"], a[class*="logo" i], a[class*="brand" i]')
                            
                            for link in link_elements:
                                # Image dans le lien
                                img_in_link = await link.query_selector('img')
                                if img_in_link:
                                    src = await img_in_link.get_attribute("src")
                                    if src:
                                        full_url = urljoin(website_url, src)
                                        if self.validate_logo_image(full_url):
                                            logger.info(f" STRATÉGIE 11 - Logo dans lien trouvé: {full_url}")
                                            await browser.close()
                                            return full_url
                                
                                # SVG dans le lien
                                svg_in_link = await link.query_selector('svg')
                                if svg_in_link:
                                    svg_content = await svg_in_link.inner_html()
                                    if svg_content and len(svg_content) > 50:
                                        svg_bytes = f'<svg>{svg_content}</svg>'.encode('utf-8')
                                        svg_base64 = base64.b64encode(svg_bytes).decode('utf-8')
                                        svg_url = f"data:image/svg+xml;base64,{svg_base64}"
                                        logger.info(f" STRATÉGIE 11 - SVG dans lien trouvé: {svg_url[:100]}...")
                                        await browser.close()
                                        return svg_url
                    except Exception as e:
                        logger.debug(f"Erreur avec sélecteur {selector}: {e}")
                        continue
                
                # NOUVEAU: Chercher dans toute la page si rien trouvé dans header
                all_imgs = await page.query_selector_all('img[alt*="logo" i], img[src*="logo" i]')
                for img in all_imgs[:5]:  # Limiter à 5
                    src = await img.get_attribute("src")
                    if src:
                        full_url = urljoin(website_url, src)
                        if self.validate_logo_image(full_url):
                            logger.info(f" STRATÉGIE 11 - Logo global trouvé: {full_url}")
                            await browser.close()
                            return full_url
                
                await browser.close()
                return None
                
        except Exception as e:
            logger.debug(f"Erreur stratégie dynamique: {e}")
            return None

    
    # UTILITAIRES POUR L'EXTRACTION DE LOGOS
    
    def _add_logo_candidate(self, logo_url, img_element, confidence, strategy):
        """Ajoute un candidat logo pour analyse ultérieure"""
        if logo_url and len(self.logo_candidates) < 20:  # Limiter le nombre de candidats
            self.logo_candidates.append({
                'url': logo_url,
                'confidence': confidence,
                'strategy': strategy,
                'alt': img_element.get('alt', '') if img_element else '',
                'class': ' '.join(img_element.get('class', [])) if img_element else '',
                'src': img_element.get('src', '') if img_element else ''
            })

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
            return False
        
        confidence_score = confidence_boost
        
        # Validation de l'extension/type
        if logo_url.startswith('data:image/'):
            confidence_score += 0.2
        else:
            valid_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico']
            has_valid_ext = any(ext in logo_url.lower() for ext in valid_extensions)
            
            if not has_valid_ext:
                return False
            
            if '.svg' in logo_url.lower():
                confidence_score += 0.1
        
        # Analyse de l'élément img
        if img_element:
            alt_text = img_element.get('alt', '').lower()
            class_list = ' '.join(img_element.get('class', [])).lower()
            
            # Bonus pour mots-clés logo
            logo_keywords = ['logo', 'brand', 'company', 'organization', 'site']
            if any(keyword in alt_text or keyword in class_list for keyword in logo_keywords):
                confidence_score += 0.3
            
            # Validation des dimensions
            width = img_element.get('width')
            height = img_element.get('height')
            if width and height:
                try:
                    w, h = int(width), int(height)
                    if 50 <= w <= 500 and 20 <= h <= 200:
                        confidence_score += 0.1
                except:
                    pass
        
        # Validation de l'accessibilité de l'image (avec HEAD request optimisée)
        if not logo_url.startswith('data:'):
            if not self.validate_logo_image_fast(logo_url):
                return False
        
        # Décision finale
        return confidence_score >= 0.1

    # VALIDATION ET UTILITAIRES AMÉLIORÉS
    

    def validate_logo_image_fast(self, logo_url):
        """Validation rapide avec HEAD request optimisée"""
        try:
            if not logo_url or len(logo_url) < 10:
                return False
            
            # Accepter les data URLs
            if logo_url.startswith('data:image/'):
                return True
            
            # Extensions valides (inclut .ico pour favicon)
            valid_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico']
            if not any(ext in logo_url.lower() for ext in valid_extensions):
                return False
            
            # HEAD request optimisée
            try:
                head_response = self.session.head(logo_url, timeout=3, allow_redirects=True)
                if head_response.status_code == 200:
                    content_type = head_response.headers.get('content-type', '').lower()
                    return any(img_type in content_type for img_type in ['image', 'icon'])
            except:
                # Fallback avec GET si HEAD échoue
                try:
                    get_response = self.session.get(logo_url, timeout=2, stream=True)
                    if get_response.status_code == 200:
                        content_type = get_response.headers.get('content-type', '').lower()
                        return any(img_type in content_type for img_type in ['image', 'icon'])
                except:
                    pass
            
            return False
            
        except Exception:
            return False

    def validate_logo_image(self, logo_url):
        """Validation complète de logo (version originale pour compatibilité)"""
        try:
            if not logo_url or len(logo_url) < 10:
                return False
            
            # Accepter les data URLs
            if logo_url.startswith('data:image/'):
                return True
            
            # Extensions valides (inclut .ico pour favicon)
            valid_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico']
            if not any(ext in logo_url.lower() for ext in valid_extensions):
                return False
            
            try:
                head_response = self.session.head(logo_url, timeout=5)
                if head_response.status_code == 200:
                    content_type = head_response.headers.get('content-type', '')
                    if any(img_type in content_type for img_type in ['image', 'icon']):
                        return True
            except:
                try:
                    get_response = self.session.get(logo_url, timeout=3, stream=True)
                    if get_response.status_code == 200:
                        content_type = get_response.headers.get('content-type', '')
                        if any(img_type in content_type for img_type in ['image', 'icon']):
                            return True
                        
                        # Pour les .ico, vérifier la signature binaire
                        if logo_url.lower().endswith('.ico'):
                            first_bytes = get_response.content[:4]
                            if first_bytes and len(first_bytes) >= 4:
                                if first_bytes[0:2] == b'\x00\x00' and first_bytes[2:4] in [b'\x01\x00', b'\x02\x00']:
                                    return True
                except:
                    pass
            
            return False
            
        except Exception:
            return False

    def validate_website(self, website_url):
        """Valide qu'une URL de site web est accessible et n'est pas un PDF"""
        if not website_url:
            return False
        
        # Vérifier que ce n'est pas un PDF ou autre fichier
        invalid_extensions = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', 
                            '.zip', '.rar', '.tar', '.gz', '.jpg', '.png', '.gif', '.svg']
        
        for ext in invalid_extensions:
            if website_url.lower().endswith(ext):
                logger.debug(f"URL rejetée (fichier {ext}): {website_url}")
                return False
        
        try:
            if not website_url.startswith(('http://', 'https://')):
                website_url = 'https://' + website_url
            
            response = self.session.head(website_url, timeout=10, allow_redirects=True)
            
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '').lower()
                
                # Vérifier que c'est bien du HTML
                if 'application/pdf' in content_type:
                    logger.debug(f"URL rejetée (Content-Type PDF): {website_url}")
                    return False
                
                valid_content_types = ['text/html', 'application/xhtml', 'text/plain']
                if any(valid_type in content_type for valid_type in valid_content_types):
                    return True
                
                # Si pas de content-type spécifique, on assume que c'est valide
                if not content_type or content_type == 'application/octet-stream':
                    return True
                    
                return False
            
            return False
        except Exception as e:
            logger.debug(f"Erreur validation website {website_url}: {e}")
            return False

    
    # RECHERCHE ET ENRICHISSEMENT D'ORGANISATIONS AMÉLIORÉ
    

    def search_organization_online(self, organization_name):
        """Recherche en ligne les infos de l'organisation"""
        if not organization_name:
            return {'organization_website': None, 'organization_logo': None}
        
        try:
            search_query = f"{organization_name} official website"
            logger.info(f"🔍 Recherche web: {search_query}")
            
            search_response = self.session.get(
                "https://www.google.com/search",
                params={'q': search_query, 'num': 3},
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                timeout=10
            )
            
            if search_response.status_code == 200:
                soup = BeautifulSoup(search_response.text, 'html.parser')
                
                for result in soup.find_all('a', href=True):
                    href = result.get('href')
                    if href and '/url?q=' in href:
                        actual_url = href.split('/url?q=')[1].split('&')[0]
                        if actual_url.startswith('http') and 'google.com' not in actual_url:
                            logo_url = self.extract_logo_from_website(actual_url)
                            return {
                                'organization_website': actual_url,
                                'organization_logo': logo_url
                            }
        except Exception as e:
            logger.warning(f"Erreur lors de la recherche web: {e}")
        
        return {'organization_website': None, 'organization_logo': None}

    def _is_valid_organization_url(self, url):
        """Valide qu'une URL est appropriée pour une organisation"""
        if not url:
            return False
        
        # Exclure les fichiers PDF et autres documents
        invalid_extensions = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', 
                            '.zip', '.rar', '.tar', '.gz']
        for ext in invalid_extensions:
            if url.lower().endswith(ext):
                logger.debug(f"URL SerpAPI rejetée (fichier {ext}): {url}")
                return False
        
        # Exclure les réseaux sociaux et plateformes génériques
        excluded_domains = [
            'facebook.com', 'twitter.com', 'linkedin.com', 'instagram.com',
            'youtube.com', 'wikipedia.org', 'crunchbase.com', 'bloomberg.com',
            'reuters.com', 'techcrunch.com', 'forbes.com'
        ]
        
        return not any(domain in url.lower() for domain in excluded_domains)

    
    # SERPAPI ET ENRICHISSEMENT AVANCÉ AMÉLIORÉ
    

    def calculate_website_relevance(self, organization_name, url, title, snippet):
        """Calcule la pertinence d'un résultat de recherche pour une organisation"""
        try:
            if not self._is_valid_organization_url(url):
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
            
            # Malus pour domaines non officiels
            unwanted_domains = ['wikipedia', 'crunchbase', 'bloomberg', 'reuters']
            for domain in unwanted_domains:
                if domain in url_lower:
                    score -= 0.5
            
            # Normalisation du score
            score = min(max(score, 0.0), 1.0)
            return score
            
        except Exception as e:
            logger.debug(f"Erreur calcul pertinence: {e}")
            return 0.0

    def enrich_with_serpapi(self, organization_name, current_website=None, current_logo=None):
        """Enrichit les informations d'organisation avec SerpAPI (AMÉLIORÉ)"""
        if not self.serpapi_key or not organization_name:
            return {
                'organization_website': current_website,
                'organization_logo': current_logo,
                'serpapi_enhanced': False
            }
        try:
            logger.info(f" Enrichissement SerpAPI pour: {organization_name}")
            
            # Validation des données actuelles
            website_valid = self.validate_website(current_website) if current_website else False
            logo_valid = self.validate_logo_image(current_logo) if current_logo else False
            
            if website_valid and logo_valid:
                return {
                    'organization_website': current_website,
                    'organization_logo': current_logo,
                    'serpapi_enhanced': False
                }
            
            # Requêtes de recherche multiples et plus ciblées
            search_queries = [
                f'"{organization_name}" site officiel',
                f'"{organization_name}" official website',
                f'{organization_name} organization official site',
                f'{organization_name} foundation website',
                f'{organization_name} institution homepage'  # NOUVEAU
            ]
            
            found_website = None
            best_confidence = 0
            
            for query in search_queries:
                try:
                    params = {
                        'api_key': self.serpapi_key,
                        'engine': 'google',
                        'q': query,
                        'num': 8,  # AUGMENTÉ de 5 à 8
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
                                
                                if not self._is_valid_organization_url(url):
                                    continue
                                
                                confidence = self.calculate_website_relevance(
                                    organization_name, url, title, snippet
                                )
                                
                                if confidence > best_confidence and confidence > 0.4:
                                    if self.validate_website(url):
                                        found_website = url
                                        best_confidence = confidence
                                        
                                        if confidence > 0.8:
                                            break
                        
                        # Vérification du knowledge graph
                        if 'knowledge_graph' in search_results:
                            kg = search_results['knowledge_graph']
                            if 'website' in kg:
                                kg_website = kg['website']
                                
                                if self._is_valid_organization_url(kg_website):
                                    confidence = self.calculate_website_relevance(
                                        organization_name, kg_website, 
                                        kg.get('title', ''), kg.get('description', '')
                                    )
                                    
                                    if confidence > best_confidence:
                                        if self.validate_website(kg_website):
                                            found_website = kg_website
                                            best_confidence = confidence
                    
                    time.sleep(1)
                    
                    if best_confidence > 0.8:
                        break
                        
                except Exception as e:
                    logger.debug(f"Erreur pour requête '{query}': {e}")
                    continue
            
            final_website = found_website if found_website and not website_valid else current_website
            
            # Extraction de logo avancée avec toutes les stratégies
            final_logo = current_logo
            if not logo_valid and final_website:
                try:
                    extracted_logo = self.extract_logo_from_website(final_website)
                    if extracted_logo:
                        final_logo = extracted_logo
                except Exception as e:
                    logger.debug(f"Erreur extraction logo avancée: {e}")
            
            success = found_website is not None or (website_valid and logo_valid)
            
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

    def enrich_organization_with_serpapi_fallback(self, content, title):
        """NOUVEAU: Utilise SerpAPI pour trouver l'organisation quand organization_name est null"""
        if not self.serpapi_key:
            return {
                'organization_name': None,
                'organization_website': None,
                'organization_logo': None,
                'serpapi_enhanced': False
            }
        
        try:
            logger.info(" Recherche d'organisation via SerpAPI (organization_name null)")
            
            # Extraire des mots-clés du titre et du contenu
            combined_text = f"{title} {content[:500]}"
            
            # Patterns pour identifier des organisations
            org_patterns = [
                r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:Foundation|Institute|Organization|Initiative|Fund|Program|Award|Prize|Competition|Challenge)\b',
                r'\b(?:The\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:Foundation|Institute|Organization)\b',
                r'\borganized\s+by\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b',
                r'\bsponsored\s+by\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b',
                r'\bpartnership\s+with\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b'
            ]
            
            potential_orgs = []
            for pattern in org_patterns:
                matches = re.finditer(pattern, combined_text, re.IGNORECASE)
                for match in matches:
                    org_name = match.group(1).strip()
                    if len(org_name) > 3 and org_name not in potential_orgs:
                        potential_orgs.append(org_name)
            
            if not potential_orgs:
                return {
                    'organization_name': None,
                    'organization_website': None,
                    'organization_logo': None,
                    'serpapi_enhanced': False
                }
            
            # Rechercher chaque organisation potentielle
            for org_name in potential_orgs[:3]:  # Limiter à 3 recherches
                try:
                    search_query = f'"{org_name}" official website organization'
                    
                    params = {
                        'api_key': self.serpapi_key,
                        'engine': 'google',
                        'q': search_query,
                        'num': 5,
                        'hl': 'en',
                        'gl': 'us'
                    }
                    
                    response = self.session.get("https://serpapi.com/search", params=params, timeout=15)
                    
                    if response.status_code == 200:
                        search_results = response.json()
                        
                        # Vérifier le knowledge graph en premier
                        if 'knowledge_graph' in search_results:
                            kg = search_results['knowledge_graph']
                            kg_title = kg.get('title', '')
                            kg_website = kg.get('website', '')
                            
                            # Vérifier si c'est bien une organisation
                            if any(keyword in kg_title.lower() for keyword in ['foundation', 'institute', 'organization', 'university', 'company']):
                                if self._is_valid_organization_url(kg_website) and self.validate_website(kg_website):
                                    logo_url = self.extract_logo_from_website(kg_website)
                                    return {
                                        'organization_name': kg_title,
                                        'organization_website': kg_website,
                                        'organization_logo': logo_url,
                                        'serpapi_enhanced': True
                                    }
                        
                        # Analyser les résultats organiques
                        if 'organic_results' in search_results:
                            for result in search_results['organic_results']:
                                url = result.get('link', '')
                                title_result = result.get('title', '')
                                snippet = result.get('snippet', '')
                                
                                # Vérifier si c'est un site officiel d'organisation
                                if (any(keyword in title_result.lower() or keyword in snippet.lower() 
                                       for keyword in ['foundation', 'institute', 'organization', 'official']) and
                                    self._is_valid_organization_url(url) and 
                                    self.validate_website(url)):
                                    
                                    logo_url = self.extract_logo_from_website(url)
                                    return {
                                        'organization_name': org_name,
                                        'organization_website': url,
                                        'organization_logo': logo_url,
                                        'serpapi_enhanced': True
                                    }
                    
                    time.sleep(1)  # Respecter les limites de taux
                    
                except Exception as e:
                    logger.debug(f"Erreur recherche SerpAPI pour '{org_name}': {e}")
                    continue
            
            return {
                'organization_name': potential_orgs[0] if potential_orgs else None,
                'organization_website': None,
                'organization_logo': None,
                'serpapi_enhanced': False
            }
            
        except Exception as e:
            logger.error(f"Erreur enrichissement SerpAPI fallback: {e}")
            return {
                'organization_name': None,
                'organization_website': None,
                'organization_logo': None,
                'serpapi_enhanced': False
            }

   
    # ANALYSE LLM ET TRAITEMENT DE DONNÉES
    

    def analyze_with_llm(self, article_data):
        """MODIFIÉE: Analyse le contenu avec Gemini AI + extraction améliorée depuis le contenu"""
        try:
            prompt = self.llm_prompt.format(
                title=article_data.get('title', ''),
                content=article_data.get('content', '')[:3000],
                published_date=article_data.get('published_date', '')
            )
            
            response = self.model.generate_content(prompt)
            json_text = response.text.strip()

            # Nettoyage du bloc de réponse JSON
            if json_text.startswith('```json'):
                json_text = json_text[7:-3].strip()
            elif json_text.startswith('```'):
                json_text = json_text[3:-3].strip()

            parsed_data = json.loads(json_text)

            # NOUVEAU: Essayer d'extraire le site web et logo depuis le contenu de l'article
            organization_name = parsed_data.get('organization_name')
            if organization_name:
                logger.info(f" Tentative d'extraction du site web depuis le contenu pour: {organization_name}")
                
                content_org_info = self.extract_and_validate_organization_info_from_content(
                    article_data.get('content', ''),
                    article_data.get('title', ''),
                    organization_name
                )

                # Mise à jour avec les infos extraites du contenu
                if content_org_info.get('content_extraction'):
                    logger.info(f" Site web extrait du contenu: {content_org_info.get('organization_website')}")
                    parsed_data['organization_website'] = content_org_info.get('organization_website')
                    parsed_data['organization_logo'] = content_org_info.get('organization_logo')
                    parsed_data['content_extracted_website'] = True  # Flag pour savoir d'où vient l'info
                else:
                    parsed_data['content_extracted_website'] = False

            return parsed_data

        except Exception as e:
            logger.error(f"Erreur LLM: {e}")
            return {
                'meta_title': article_data.get('title', '')[:100],
                'meta_description': article_data.get('description', '')[:130],
                'subtitle': '',
                'description': article_data.get('description', ''),
                'slug': self.create_slug(article_data.get('title', '')),
                'regions': [],
                'sectors': [],
                'stages': [],
                'categories': [],
                'draft_summary': {
                    'introduction': '',
                    'details': [],
                    'closing': ''
                },
                'main_image_alt': None,
                'organizer_logo_alt': None,
                'extracted_published_date': article_data.get('published_date'),
                'extracted_deadline': article_data.get('deadline'),
                'organization_name': None,
                'organization_website': None,
                'organization_logo': None,
                'serpapi_enhanced': False,
                'content_extracted_website': False
            }

    def create_slug(self, title):
        """Crée un slug URL à partir du titre"""
        if not title:
            return ""
        
        slug = title.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug)
        return slug.strip('-')

    def build_opportunity_object(self, article_data, llm_data):
        """Construit un objet opportunité dans le format exact demandé"""
        return {
            "url": article_data.get('url'),
            "title": article_data.get('title'),
            "subtitle": llm_data.get('subtitle', ''),
            "description": llm_data.get('description') or article_data.get('description', ''),
            "content": article_data.get('content', ''),
            "meta_title": llm_data.get('meta_title'),
            "meta_description": llm_data.get('meta_description'),
            "slug": llm_data.get('slug'),
            "regions": llm_data.get('regions', []),
            "sectors": llm_data.get('sectors', []),
            "stages": llm_data.get('stages', []),
            "categories": llm_data.get('categories', []),
            "draft_summary": llm_data.get('draft_summary', {}),
            "main_image_alt": llm_data.get('main_image_alt'),
            "organizer_logo_alt": llm_data.get('organizer_logo_alt'),
            "extracted_published_date": llm_data.get('extracted_published_date') or article_data.get('published_date'),
            "extracted_deadline": llm_data.get('extracted_deadline') or article_data.get('deadline'),
            "organization_name": llm_data.get('organization_name'),
            "organization_website": llm_data.get('organization_website'),
            "organization_logo": llm_data.get('organization_logo'),
            "serpapi_enhanced": llm_data.get('serpapi_enhanced', False)
        }

    
    # FONCTIONS PRINCIPALES DE SCRAPING AMÉLIORÉES
    
    def enhance_opportunities_with_serpapi(self, opportunities):
        """MODIFIÉE: Enrichit toutes les opportunités avec SerpAPI APRÈS tentative d'extraction du contenu"""
        logger.info(f" Enrichissement de {len(opportunities)} opportunités avec SerpAPI...")
        
        enhanced_opportunities = []
        
        for i, opportunity in enumerate(opportunities):
            logger.info(f" Enrichissement {i+1}/{len(opportunities)}: {opportunity.get('title', 'Titre inconnu')[:50]}...")
            
            organization_name = opportunity.get('organization_name')
            current_website = opportunity.get('organization_website')
            current_logo = opportunity.get('organization_logo')
            content_extracted = opportunity.get('content_extracted_website', False)
            
            # NOUVEAU: Si organization_name est null, essayer de la trouver avec SerpAPI
            if not organization_name:
                logger.info(" Organization_name null - recherche via SerpAPI...")
                serpapi_org_info = self.enrich_organization_with_serpapi_fallback(
                    opportunity.get('content', ''), 
                    opportunity.get('title', '')
                )
                
                if serpapi_org_info.get('organization_name'):
                    opportunity.update(serpapi_org_info)
                    organization_name = serpapi_org_info.get('organization_name')
                    current_website = serpapi_org_info.get('organization_website')
                    current_logo = serpapi_org_info.get('organization_logo')
                    logger.info(f" Organisation trouvée via SerpAPI: {organization_name}")
            
            # MODIFIÉ: Enrichissement avec SerpAPI seulement si extraction du contenu a échoué
            if organization_name:
                website_valid = self.validate_website(current_website) if current_website else False
                logo_valid = self.validate_logo_image(current_logo) if current_logo else False
                
                # Si site web extrait du contenu et valide, ne pas utiliser SerpAPI pour le site web
                if content_extracted and website_valid:
                    logger.info(f" Site web déjà extrait du contenu: {current_website}")
                    
                    # Mais essayer d'extraire le logo si pas encore trouvé
                    if not logo_valid and current_website:
                        try:
                            extracted_logo = self.extract_logo_from_website(current_website)
                            if extracted_logo and self.validate_logo_image(extracted_logo):
                                opportunity['organization_logo'] = extracted_logo
                                logger.info(f" Logo extrait depuis le site: {extracted_logo}")
                        except Exception as e:
                            logger.debug(f"Erreur extraction logo: {e}")
                    
                    opportunity['serpapi_enhanced'] = False
                    
                # Sinon, utiliser SerpAPI pour compléter les infos manquantes
                elif not website_valid or not logo_valid:
                    logger.info(f"🔍 Utilisation de SerpAPI pour compléter les infos manquantes...")
                    enriched_org_info = self.enrich_with_serpapi(
                        organization_name, 
                        current_website, 
                        current_logo
                    )
                    
                    opportunity.update({
                        'organization_website': enriched_org_info.get('organization_website'),
                        'organization_logo': enriched_org_info.get('organization_logo'),
                        'serpapi_enhanced': enriched_org_info.get('serpapi_enhanced', False)
                    })
                    
                    if enriched_org_info.get('serpapi_enhanced'):
                        logger.info(f" Enrichi avec succès via SerpAPI: {organization_name}")
                    
                    time.sleep(3)
                else:
                    logger.info(f" Données déjà valides pour: {organization_name}")
                    opportunity['serpapi_enhanced'] = False
            else:
                opportunity['serpapi_enhanced'] = False
            
            enhanced_opportunities.append(opportunity)
        
        logger.info(f" Enrichissement terminé pour {len(enhanced_opportunities)} opportunités")
        return enhanced_opportunities

    def scrape_opportunities(self, first_page_only=True):
        """MODIFIÉE: Fonction principale pour scraper les opportunités avec extraction améliorée du contenu"""
        all_opportunities = []
        
        for base_url in self.base_urls:
            logger.info(f" Scraping: {base_url}")
            
            if first_page_only:
                page_urls = [base_url]
                logger.info(" Mode première page seulement activé")
            else:
                page_urls = self.get_pagination_urls(base_url, max_pages=3)
                logger.info(f" Mode pagination activé - {len(page_urls)} pages à traiter")
            
            for page_url in page_urls:
                logger.info(f" Traitement de la page: {page_url}")
                
                html_content = self.get_page_content_static(page_url)
                if not html_content:
                    html_content = self.get_page_content_dynamic(page_url)
                
                if not html_content:
                    logger.warning(f" Impossible de récupérer le contenu de: {page_url}")
                    continue
                
                article_links = self.extract_article_links(html_content, page_url)
                logger.info(f" {len(article_links)} articles trouvés")
                
                for i, article_url in enumerate(article_links):
                    try:
                        logger.info(f" Traitement article {i+1}/{len(article_links)}: {article_url}")
                        
                        article_data = self.extract_article_data(article_url)
                        
                        if article_data and article_data.get('title') and article_data.get('content'):
                            if len(article_data['content']) > 200:
                                # Analyser avec LLM (inclut maintenant l'extraction améliorée depuis le contenu)
                                llm_data = self.analyze_with_llm(article_data)
                                
                                # MODIFIÉ: Rechercher les infos de l'organisation SEULEMENT si pas déjà extraites du contenu
                                organization_name = llm_data.get('organization_name')
                                if organization_name and not llm_data.get('content_extracted_website'):
                                    logger.info(f" Organisation détectée: {organization_name}")
                                    org_info = self.search_organization_online(organization_name)
                                    
                                    # Mettre à jour seulement si pas déjà présent
                                    if not llm_data.get('organization_website'):
                                        llm_data['organization_website'] = org_info.get('organization_website')
                                    if not llm_data.get('organization_logo'):
                                        llm_data['organization_logo'] = org_info.get('organization_logo')
                                elif organization_name and llm_data.get('content_extracted_website'):
                                    logger.info(f" Site web déjà extrait du contenu pour: {organization_name}")
                                
                                # Combiner les données
                                opportunity = self.build_opportunity_object(article_data, llm_data)
                                
                                all_opportunities.append(opportunity)
                                logger.info(f" Article traité: {article_data['title'][:60]}...")
                            else:
                                logger.warning(f" Contenu trop court pour: {article_url}")
                        else:
                            logger.warning(f" Données manquantes pour: {article_url}")
                        
                        time.sleep(2)
                            
                    except Exception as e:
                        logger.error(f" Erreur lors du traitement de {article_url}: {e}")
                        continue
        
        return all_opportunities
   
    # UTILITAIRES ET PAGINATION
    def get_pagination_urls(self, base_url, max_pages=3):
        """Génère les URLs pour les premières pages avec pagination"""
        urls = [base_url]
        
        if 'opportunitiesforafricans.com' in base_url:
            for page in range(2, max_pages + 1):
                urls.append(f"{base_url}page/{page}/")
        elif 'msmeafricaonline.com' in base_url:
            for page in range(2, max_pages + 1):
                urls.append(f"{base_url}page/{page}/")
        elif 'opportunitydesk.org' in base_url:
            for page in range(2, max_pages + 1):
                urls.append(f"{base_url}page/{page}/")
        
        return urls

    def save_to_json(self, opportunities, filename="african_opportunities.json"):
        """Sauvegarde les opportunités dans un fichier JSON"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(opportunities, f, ensure_ascii=False, indent=2)
        
        logger.info(f" Données sauvegardées dans {filename}")
        return filename

    def debug_website_extraction(self, content, title, organization_name):
        """NOUVELLE: Fonction de debug pour tester l'extraction de sites web"""
        print(f"\n{'='*60}")
        print(f"DEBUG EXTRACTION POUR: {organization_name}")
        print(f"{'='*60}")
        
        print(f"\n TITRE: {title}")
        print(f" CONTENU (premiers 500 chars):\n{content[:500]}...")
        
        # Test extraction depuis le texte
        print(f"\n EXTRACTION DEPUIS LE TEXTE:")
        text_urls = self._extract_urls_from_text(content, organization_name)
        if text_urls:
            for i, url in enumerate(text_urls, 1):
                print(f"   {i}. {url}")
                # Test de validation
                is_valid_candidate = self._is_valid_organization_website_candidate(url)
                is_valid_website = self.validate_website(url) if is_valid_candidate else False
                print(f"      → Candidat valide: {is_valid_candidate}")
                print(f"      → Site web valide: {is_valid_website}")
                
                if is_valid_candidate:
                    score = self._score_organization_website_candidate(url, organization_name, content)
                    print(f"      → Score: {score:.2f}")
        else:
            print("   Aucune URL trouvée dans le texte")
        
        # Test extraction depuis HTML
        print(f"\n🔗 EXTRACTION DEPUIS LES LIENS HTML:")
        html_urls = self._extract_urls_from_article_html(content, title, organization_name)
        if html_urls:
            for i, url in enumerate(html_urls, 1):
                print(f"   {i}. {url}")
                # Test de validation
                is_valid_candidate = self._is_valid_organization_website_candidate(url)
                is_valid_website = self.validate_website(url) if is_valid_candidate else False
                print(f"      → Candidat valide: {is_valid_candidate}")
                print(f"      → Site web valide: {is_valid_website}")
                
                if is_valid_candidate:
                    score = self._score_organization_website_candidate(url, organization_name, content)
                    print(f"      → Score: {score:.2f}")
        else:
            print("   Aucune URL trouvée dans les liens HTML")
        
        # Test complet
        print(f"\n RÉSULTAT FINAL:")
        result = self.extract_and_validate_organization_info_from_content(content, title, organization_name)
        print(f"   Content extraction: {result.get('content_extraction')}")
        print(f"   Website: {result.get('organization_website')}")
        print(f"   Logo: {result.get('organization_logo')}")
        
        print(f"\n{'='*60}")
        return result

# FONCTION PRINCIPALE AMÉLIORÉE


async def main():
   """Fonction principale d'exécution du scraper (AMÉLIORÉE)"""
   try:
       logger.info(" Démarrage du scraper d'opportunités africaines (VERSION AMÉLIORÉE)")
       
       # Initialisation du scraper
       scraper = AfricanOpportunitiesScraper()
       
       # PHASE 1: Scraping principal (première page seulement)
       logger.info(" Phase 1: Scraping des opportunités (première page seulement)...")
       opportunities = scraper.scrape_opportunities(first_page_only=True)
       
       if not opportunities:
           logger.warning(" Aucune opportunité trouvée lors du scraping")
           return
       
       logger.info(f" {len(opportunities)} opportunités extraites avec succès")
       
       # PHASE 2: Enrichissement avec SerpAPI (si configuré)
       if scraper.serpapi_key:
           logger.info(" Phase 2: Enrichissement avec SerpAPI (incluant recherche d'organisations)...")
           enhanced_opportunities = scraper.enhance_opportunities_with_serpapi(opportunities)
       else:
           logger.info(" Phase 2: SerpAPI non configuré, enrichissement ignoré")
           enhanced_opportunities = opportunities
       
       # PHASE 3: Sauvegarde des résultats
       logger.info(" Phase 3: Sauvegarde des résultats...")
       filename = scraper.save_to_json(enhanced_opportunities)
       
       # PHASE 4: Statistiques et rapport final
       logger.info(" Phase 4: Génération du rapport final...")
       
       # Calcul des statistiques
       total_orgs = len([opp for opp in enhanced_opportunities if opp.get('organization_name')])
       total_websites = len([opp for opp in enhanced_opportunities if opp.get('organization_website')])
       total_logos = len([opp for opp in enhanced_opportunities if opp.get('organization_logo')])
       total_serpapi_enhanced = len([opp for opp in enhanced_opportunities if opp.get('serpapi_enhanced')])
       
       # Rapport détaillé
       print(f"\n SCRAPING TERMINÉ AVEC SUCCÈS!")
       print("=" * 80)
       print(f" STATISTIQUES GÉNÉRALES:")
       print(f"   • Total d'opportunités extraites: {len(enhanced_opportunities)}")
       print(f"   • Organisations identifiées: {total_orgs} ({total_orgs/len(enhanced_opportunities)*100:.1f}%)")
       print(f"   • Sites web trouvés: {total_websites} ({total_websites/len(enhanced_opportunities)*100:.1f}%)")
       print(f"   • Logos extraits: {total_logos} ({total_logos/len(enhanced_opportunities)*100:.1f}%)")
       print(f"   • Enrichies avec SerpAPI: {total_serpapi_enhanced} ({total_serpapi_enhanced/len(enhanced_opportunities)*100:.1f}%)")
       print(f"   • Données sauvegardées dans: '{filename}'")
       
       # Affichage d'exemples pour vérification
       if enhanced_opportunities:
           print(f"\n EXEMPLES D'OPPORTUNITÉS:")
           print("=" * 80)
           
           # Exemple avec organisation complète
           complete_example = None
           for opp in enhanced_opportunities:
               if (opp.get('organization_name') and 
                   opp.get('organization_website') and 
                   opp.get('organization_logo')):
                   complete_example = opp
                   break
           
           if complete_example:
               print(" EXEMPLE COMPLET (avec organisation, site web et logo):")
               print(f"   Titre: {complete_example.get('title', 'N/A')[:70]}...")
               print(f"   Organisation: {complete_example.get('organization_name', 'N/A')}")
               print(f"   Site web: {complete_example.get('organization_website', 'N/A')}")
               print(f"   Logo trouvé: ")
               print(f"   Deadline: {complete_example.get('extracted_deadline', 'N/A')}")
               print(f"   SerpAPI: {'✅' if complete_example.get('serpapi_enhanced') else '❌'}")
               print()
           
           # Exemple général
           example = enhanced_opportunities[0]
           print(" PREMIER EXEMPLE GÉNÉRAL:")
           print(f"   Titre: {example.get('title', 'N/A')}")
           print(f"   Description: {example.get('description', 'N/A')[:100]}...")
           print(f"   Organisation: {example.get('organization_name', 'N/A')}")
           print(f"   Site web: {example.get('organization_website', 'N/A')}")
           print(f"   Logo: {'✅' if example.get('organization_logo') else '❌'}")
           print(f"   Deadline: {example.get('extracted_deadline', 'N/A')}")
           print(f"   Régions: {', '.join(example.get('regions', [])[:3])}...")
           print(f"   Secteurs: {', '.join(example.get('sectors', [])[:3])}...")
           print(f"   SerpAPI enrichi: {'✅' if example.get('serpapi_enhanced') else '❌'}")
           
           # Analyse des stratégies de logos réussies
           logo_strategies = {}
           for opp in enhanced_opportunities:
               if opp.get('organization_logo'):
                   # Cette information pourrait être ajoutée lors de l'extraction
                   strategy = "Extraction réussie"
                   logo_strategies[strategy] = logo_strategies.get(strategy, 0) + 1
           
           if logo_strategies:
               print(f"\n PERFORMANCE DES STRATÉGIES DE LOGOS:")
               for strategy, count in logo_strategies.items():
                   print(f"   • {strategy}: {count} logos")
       
       print("=" * 80)
       
       # Recommandations
       print(f"\n RECOMMANDATIONS:")
       if total_orgs < len(enhanced_opportunities) * 0.8:
           print("   • Améliorer la détection d'organisations dans le contenu")
       if total_logos < total_websites * 0.7:
           print("   • Optimiser l'extraction de logos depuis les sites web")
       if scraper.serpapi_key and total_serpapi_enhanced < total_orgs * 0.5:
           print("   • Vérifier la configuration SerpAPI pour un meilleur enrichissement")
       if not scraper.serpapi_key:
           print("   • Configurer SerpAPI pour un enrichissement optimal des données")
       
       print("\n Scraping terminé avec succès!")
           
   except KeyboardInterrupt:
       logger.info(" Scraping interrompu par l'utilisateur")
   except Exception as e:
       logger.error(f" Erreur générale: {e}")
       raise
if __name__ == "__main__":
    asyncio.run(main())