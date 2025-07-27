import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import json
import re
from datetime import datetime
import google.generativeai as genai
from urllib.parse import urljoin, urlparse
import time
import logging
import os
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv('config.env')

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DisruptAfricaScraper:
    def __init__(self, gemini_api_key=None):
        """
        Initialise le scraper avec la clé API Gemini
        """
        self.base_urls = [
            "https://disruptafrica.com/category/events/",
            "https://disruptafrica.com/category/hubs/"
        ]
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        # Configuration de session plus robuste
        self.session.mount('http://', requests.adapters.HTTPAdapter(max_retries=3))
        self.session.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))
        
        # Configuration Gemini AI - récupérer depuis l'environnement si non fournie
        api_key = gemini_api_key or os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("Clé API Gemini non trouvée. Vérifiez votre fichier config.env")
        
        genai.configure(api_key=api_key)
        
        # Utiliser le nouveau nom de modèle Gemini
        try:
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            logger.info("✓ Configuration Gemini AI réussie avec gemini-1.5-flash")
        except Exception as e:
            # Fallback vers d'autres modèles si disponibles
            try:
                self.model = genai.GenerativeModel('gemini-1.5-pro')
                logger.info("✓ Configuration Gemini AI réussie avec gemini-1.5-pro")
            except Exception as e2:
                logger.error(f"Erreur de configuration Gemini: {e}")
                logger.info("Listing des modèles disponibles...")
                try:
                    models = genai.list_models()
                    for model in models:
                        logger.info(f"Modèle disponible: {model.name}")
                except:
                    pass
                raise ValueError("Impossible de configurer Gemini AI")
        
        # Prompt pour l'extraction des métadonnées
        self.llm_prompt = """
        Analysez le contenu suivant et extrayez les informations demandées.
        
        Contenu: {content}
        Titre: {title}
        Date de publication: {published_date}
        
        Veuillez fournir UNIQUEMENT un JSON valide avec ces clés :
        - meta_title: Titre optimisé SEO (max 100 caractères)
        - meta_description: Description meta (max 160 caractères)
        - slug: URL slug (minuscules, tirets)
        - regions: Liste des régions (choisir parmi: ["Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi", "Cabo Verde", "Cameroon", "Central African Republic", "Chad", "Comoros", "Congo", "Côte d'Ivoire", "DR Congo", "Djibouti", "Egypt", "Equatorial Guinea", "Eritrea", "Eswatini", "Ethiopia", "Gabon", "Guinea", "Guinea-Bissau", "Kenya", "Lesotho", "Liberia", "Libya", "Madagascar", "Malawi", "Mali", "Mauritania", "Mauritius", "Morocco", "Mozambique", "Namibia", "Niger", "Nigeria", "Rwanda", "Sao Tome & Principe", "Senegal", "Seychelles", "Sierra Leone", "Somalia", "South Africa", "South Sudan", "Sudan", "Tanzania", "Togo", "Tunisia", "Uganda", "Zambia", "Zimbabwe"])
        - sectors: Liste des secteurs (choisir parmi: ["Regulatory Tech", "Spatial Computing", "AgriTech", "Agribusiness", "Artificial Intelligence", "Banking", "Blockchain", "Business Process Outsourcing (BPO)", "CleanTech", "Creative", "Cryptocurrencies", "Cybersecurity & Digital ID", "Data Aggregation", "Debt Management", "DeepTech", "Design & Applied Arts", "Digital & Interactive", "E-commerce and Retail", "Economic Development", "EdTech", "Energy", "Environmental Social Governance (ESG)", "FinTech", "Gaming", "HealthTech", "InsurTech", "Logistics", "ManuTech", "Manufacturing", "Media & Communication", "Mobility and Transportation", "Performing & Visual Arts", "Sector Agnostic", "Sport Management", "Sustainability", "Technology", "Tourism Innovation", "Transformative Digital Technologies", "Wearables"])
        - stages: Liste des étapes (choisir parmi: ["Not Applicable", "Pre-Series A", "Pre-seed", "Seed", "Series A", "Series B", "Series C", "Series D", "Series E", "Series F", "Stage Agnostic"])
        - categories: Liste des catégories (choisir parmi: ["Accelerator", "Bootcamp", "Competition", "Conference", "Event", "Funding Opportunity", "Hackathon", "Incubator", "Other", "Summit"])
        - draft_summary: Résumé naturel en 2-3 lignes
        - main_image_alt: Texte alternatif pour l'image principale
        - organizer_logo_alt: Texte alternatif pour le logo de l'organisateur (ou null si pas d'organisateur)
        - extracted_published_date: Date de publication extraite du contenu (format YYYY-MM-DD ou null)
        - extracted_deadline: Date limite d'application extraite du contenu (format YYYY-MM-DD ou null)
        - organization_name: Nom de l'organisation (ou null si non trouvé)
        - organization_website: Site web de l'organisation (ou null si non trouvé)
        - organization_logo: URL du logo de l'organisation (ou null si non trouvé)
        """

    def get_page_content_static(self, url, max_retries=3):
        """
        Récupère le contenu d'une page avec requests statique et retry
        """
        for attempt in range(max_retries):
            try:
                # Ajouter des headers plus réalistes
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                }
                
                response = self.session.get(
                    url, 
                    headers=headers,
                    timeout=(10, 30),  # timeout de connexion et de lecture
                    allow_redirects=True
                )
                response.raise_for_status()
                return response.text
                
            except (requests.RequestException, requests.exceptions.ConnectionError, 
                    requests.exceptions.Timeout) as e:
                logger.warning(f"Tentative {attempt + 1}/{max_retries} échouée pour {url}: {e}")
                
                if attempt < max_retries - 1:
                    # Attendre avant de réessayer (backoff exponentiel)
                    wait_time = (2 ** attempt) * 2  # 2, 4, 8 secondes
                    logger.info(f"Attente de {wait_time} secondes avant nouvelle tentative...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Échec définitif pour {url} après {max_retries} tentatives")
                    
        return None

    def get_page_content_dynamic(self, url):
        """
        Récupère le contenu d'une page avec Playwright (pour contenu dynamique)
        """
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

    def extract_article_links(self, html_content, base_url):
        """
        Extrait les liens des articles depuis la page de liste
        CORRIGÉ basé sur le débogage
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        links = []
        
        # Utiliser la structure correcte identifiée par le débogage
        articles = soup.find_all('article', class_=re.compile('l-post|list-post'))
        
        logger.info(f"Trouvé {len(articles)} articles sur la page")
        
        for article in articles:
            # Chercher le lien dans le titre h2
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
        """
        Extrait les données d'un article spécifique
        """
        logger.info(f"Extraction de: {url}")
        
        # Essayer d'abord avec requests statique
        html_content = self.get_page_content_static(url)
        
        # Si échec, utiliser Playwright
        if not html_content:
            html_content = self.get_page_content_dynamic(url)
            
        if not html_content:
            return None
            
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Extraction des données de base
        data = {
            'url': url,
            'title': None,
            'published_date': None,  # Sera mappé vers extracted_published_date
            'subtitle': None,
            'description': None,
            'deadline': None,  # Sera mappé vers extracted_deadline
            'content': None,
            'soup': soup  # Garder le soup pour l'extraction d'organisation
        }
        
        # Titre (h1 avec class post-title)
        title_elem = soup.find('h1', class_='post-title')
        if title_elem:
            data['title'] = title_elem.get_text(strip=True)
        else:
            # Fallback: chercher dans d'autres éléments
            title_elem = soup.find('h1') or soup.find('title')
            if title_elem:
                data['title'] = title_elem.get_text(strip=True)
        
        # Date de publication - Recherche plus précise
        # 1. Chercher dans post-meta
        meta_elem = soup.find('div', class_='post-meta')
        if meta_elem:
            date_text = meta_elem.get_text()
            # Pattern spécifique pour DisruptAfrica: "BY AUTHOR ON DATE"
            date_match = re.search(r'BY\s+[A-Z\s]+ON\s+([A-Z\s\d,]+)', date_text, re.IGNORECASE)
            if date_match:
                data['published_date'] = date_match.group(1).strip()
            else:
                # Pattern alternatif: "ON DATE"
                date_match = re.search(r'ON\s+([A-Z\s\d,]+)', date_text, re.IGNORECASE)
                if date_match:
                    data['published_date'] = date_match.group(1).strip()
        
        # 2. Si pas trouvé, chercher dans d'autres éléments
        if not data['published_date']:
            # Chercher dans les éléments time
            time_elem = soup.find('time')
            if time_elem:
                datetime_attr = time_elem.get('datetime')
                if datetime_attr:
                    data['published_date'] = datetime_attr
                else:
                    time_text = time_elem.get_text(strip=True)
                    # Vérifier que c'est bien une date
                    if re.search(r'\d{4}', time_text):  # Contient une année
                        data['published_date'] = time_text
            
            # Chercher directement le pattern dans tout le HTML
            if not data['published_date']:
                full_text = soup.get_text()
                date_match = re.search(r'BY\s+[A-Z\s]+ON\s+([A-Z\s\d,]+)', full_text, re.IGNORECASE)
                if date_match:
                    potential_date = date_match.group(1).strip()
                    # Vérifier que c'est bien une date (contient mois et année)
                    if any(month in potential_date.lower() for month in [
                        'january', 'february', 'march', 'april', 'may', 'june',
                        'july', 'august', 'september', 'october', 'november', 'december'
                    ]) and re.search(r'\d{4}', potential_date):
                        data['published_date'] = potential_date
        
        # Contenu principal (post-content-wrap ou similaire)
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
            # Récupérer tout le contenu texte
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
            
            # Recherche de deadline dans le contenu - Focus sur les dernières lignes
            content_lines = data['content'].split('\n')
            last_lines = [line.strip() for line in content_lines[-10:] if line.strip()]  # 10 dernières lignes non vides
            
            # Patterns de deadline plus précis - extraire SEULEMENT la date
            deadline_patterns = [
                r'deadline[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',  # deadline: june 29, 2024
                r'deadline[:\s]*(\d{1,2}\s+[a-z]+\s+\d{4})',   # deadline: 29 june 2024
                r'deadline[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{4})', # deadline: 29/06/2024
                r'apply by[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',  # apply by june 29, 2024
                r'apply by[:\s]*(\d{1,2}\s+[a-z]+\s+\d{4})',   # apply by 29 june 2024
                r'apply by[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{4})', # apply by 29/06/2024
                r'application deadline[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
                r'application deadline[:\s]*(\d{1,2}\s+[a-z]+\s+\d{4})',
                r'application deadline[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
                r'applications? close[s]?[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
                r'applications? close[s]?[:\s]*(\d{1,2}\s+[a-z]+\s+\d{4})',
                r'applications? close[s]?[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
                r'submission deadline[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
                r'submission deadline[:\s]*(\d{1,2}\s+[a-z]+\s+\d{4})',
                r'submission deadline[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
                r'due[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
                r'due[:\s]*(\d{1,2}\s+[a-z]+\s+\d{4})',
                r'due[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
                r'expires?[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
                r'expires?[:\s]*(\d{1,2}\s+[a-z]+\s+\d{4})',
                r'expires?[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
                r'until[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
                r'until[:\s]*(\d{1,2}\s+[a-z]+\s+\d{4})',
                r'until[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
                r'before[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
                r'before[:\s]*(\d{1,2}\s+[a-z]+\s+\d{4})',
                r'before[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
                r'by[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',  # by june 29, 2024
                r'by[:\s]*(\d{1,2}\s+[a-z]+\s+\d{4})',   # by 29 june 2024
                r'by[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{4})', # by 29/06/2024
                
                # Nouveaux patterns pour "until" sans année
                r'until[:\s]*([a-z]+\s+\d{1,2})',           # until september 30
                r'until[:\s]*(\d{1,2}\s+[a-z]+)',           # until 30 september
                
                # Patterns spécifiques pour des phrases complètes
                r'open.*?until[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',  # open until september 30, 2024
                r'open.*?until[:\s]*([a-z]+\s+\d{1,2})',            # open until september 30
                r'available.*?until[:\s]*([a-z]+\s+\d{1,2},?\s+\d{4})',
                r'available.*?until[:\s]*([a-z]+\s+\d{1,2})',
            ]
            
            # Aussi chercher des dates isolées dans les dernières lignes
            standalone_date_patterns = [
                r'\b([a-z]+\s+\d{1,2},?\s+\d{4})\b',      # june 29, 2024
                r'\b(\d{1,2}\s+[a-z]+\s+\d{4})\b',        # 29 june 2024
                r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b',     # 29/06/2024
                r'\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b',     # 2024/06/29
                r'\b([a-z]+\s+\d{1,2})\b',                # september 30 (sans année)
                r'\b(\d{1,2}\s+[a-z]+)\b',                # 30 september (sans année)
            ]
            
            # Recherche dans tout le contenu pour les phrases comme "Applications are open here until September 30"
            full_content_patterns = [
                r'applications?\s+are\s+open.*?until\s+([a-z]+\s+\d{1,2},?\s+\d{4})',  # Applications are open until september 30, 2024
                r'applications?\s+are\s+open.*?until\s+([a-z]+\s+\d{1,2})',           # Applications are open until september 30
                r'registration.*?until\s+([a-z]+\s+\d{1,2},?\s+\d{4})',
                r'registration.*?until\s+([a-z]+\s+\d{1,2})',
                r'submissions?.*?until\s+([a-z]+\s+\d{1,2},?\s+\d{4})',
                r'submissions?.*?until\s+([a-z]+\s+\d{1,2})',
                r'entries.*?until\s+([a-z]+\s+\d{1,2},?\s+\d{4})',
                r'entries.*?until\s+([a-z]+\s+\d{1,2})',
            ]
            
            # D'abord chercher dans le contenu complet pour les phrases spécifiques
            content_lower = data['content'].lower()
            for pattern in full_content_patterns:
                deadline_match = re.search(pattern, content_lower)
                if deadline_match:
                    potential_deadline = deadline_match.group(1).strip()
                    if self.is_valid_date(potential_deadline) or self.is_partial_date(potential_deadline):
                        data['deadline'] = potential_deadline
                        logger.info(f"✓ Deadline trouvée dans contenu complet: {potential_deadline}")
                        break
            
            # Si pas trouvé, chercher dans les dernières lignes
            if not data['deadline']:
                for line in last_lines:
                    line_lower = line.lower()
                    
                    # D'abord chercher avec les patterns de mots-clés
                    for pattern in deadline_patterns:
                        deadline_match = re.search(pattern, line_lower)
                        if deadline_match:
                            potential_deadline = deadline_match.group(1).strip()
                            if self.is_valid_date(potential_deadline) or self.is_partial_date(potential_deadline):
                                data['deadline'] = potential_deadline
                                break
                    
                    if data['deadline']:
                        break
                    
                    # Si pas trouvé, chercher des dates isolées
                    for pattern in standalone_date_patterns:
                        deadline_match = re.search(pattern, line_lower)
                        if deadline_match:
                            potential_deadline = deadline_match.group(1).strip()
                            if self.is_valid_date(potential_deadline) or self.is_partial_date(potential_deadline):
                                # Vérifier que ce n'est pas la date de publication
                                if potential_deadline != data.get('published_date', '').lower():
                                    data['deadline'] = potential_deadline
                                    break
                    
                    if data['deadline']:
                        break
        
        return data

    def get_pagination_urls(self, base_url, max_pages=3):
        """
        Génère les URLs pour les 3 premières pages
        """
        urls = [base_url]  # Page 1
        
        # Pages 2 et 3
        for page_num in range(2, max_pages + 1):
            if base_url.endswith('/'):
                pagination_url = f"{base_url}page/{page_num}/"
            else:
                pagination_url = f"{base_url}/page/{page_num}/"
            urls.append(pagination_url)
        
        return urls

    def extract_organization_info(self, soup, organization_name):
        """
        Extrait les informations de l'organisation (website et logo)
        1. D'abord chercher si le nom est cliquable dans l'article
        2. Sinon faire une recherche web
        """
        org_info = {
            'organization_website': None,
            'organization_logo': None
        }
        
        if not organization_name:
            return org_info
        
        logger.info(f"Recherche d'infos pour l'organisation: {organization_name}")
        
        # 1. Chercher dans l'article si le nom est cliquable
        org_info = self.find_clickable_organization(soup, organization_name)
        
        # 2. Si pas trouvé, faire une recherche web
        if not org_info['organization_website']:
            org_info = self.search_organization_online(organization_name)
        
        return org_info

    def find_clickable_organization(self, soup, organization_name):
        """
        Cherche si le nom de l'organisation est cliquable dans l'article
        """
        org_info = {
            'organization_website': None,
            'organization_logo': None
        }
        
        # Variations possibles du nom de l'organisation
        name_variations = [
            organization_name,
            organization_name.lower(),
            organization_name.replace(' ', ''),
            organization_name.replace(' ', '-'),
        ]
        
        # Chercher tous les liens dans l'article
        content_area = soup.find('div', class_='post-content-wrap') or soup.find('div', class_='post-content') or soup
        if content_area:
            links = content_area.find_all('a', href=True)
            
            for link in links:
                link_text = link.get_text(strip=True)
                href = link.get('href')
                
                # Vérifier si le texte du lien correspond au nom de l'organisation
                for variation in name_variations:
                    if variation.lower() in link_text.lower() or link_text.lower() in variation.lower():
                        if href and not href.startswith('#') and 'disruptafrica.com' not in href:
                            org_info['organization_website'] = href
                            logger.info(f"✓ Lien trouvé dans l'article: {href}")
                            
                            # Essayer d'extraire le logo depuis le site
                            org_info['organization_logo'] = self.extract_logo_from_website(href)
                            return org_info
        
        return org_info

    def extract_logo_from_website(self, website_url):
        """
        Visite le site web de l'organisation pour extraire son logo
        """
        try:
            logger.info(f"Extraction du logo depuis: {website_url}")
            
            # Ajouter https:// si manquant
            if not website_url.startswith(('http://', 'https://')):
                website_url = 'https://' + website_url
            
            response = self.session.get(website_url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Chercher le logo dans différents sélecteurs - ordre de priorité optimisé
            logo_selectors = [
                # Sélecteurs spécifiques pour logos dans le header
                'header img[alt*="logo" i]',
                'header .logo img',
                'header .brand img',
                'header .navbar-brand img',
                'header img[src*="logo" i]',
                'header img[class*="logo" i]',
                
                # Sélecteurs pour navigation et header à droite
                '.navbar img[alt*="logo" i]',
                '.navbar-brand img',
                '.nav img[alt*="logo" i]',
                'nav img[alt*="logo" i]',
                
                # Sélecteurs génériques mais prioritaires
                'img[alt*="logo" i]',
                'img[src*="logo" i]',
                'img[class*="logo" i]',
                '.logo img',
                '.site-logo img',
                '.brand img',
                
                # Sélecteurs pour des structures communes
                '.header img',
                '#header img',
                '.top-bar img',
                '.main-header img',
                
                # Fallback - première image du header
                'header img:first-of-type',
                'nav img:first-of-type'
            ]
            
            for selector in logo_selectors:
                logo_imgs = soup.select(selector)
                
                for logo_img in logo_imgs:
                    if logo_img and logo_img.get('src'):
                        logo_src = logo_img.get('src')
                        
                        # Filtrer les images qui ne sont probablement pas des logos
                        src_lower = logo_src.lower()
                        if any(exclude in src_lower for exclude in ['banner', 'ad', 'advertisement', 'social', 'icon-', 'facebook', 'twitter', 'linkedin']):
                            continue
                        
                        # Convertir en URL absolue
                        if logo_src.startswith('/'):
                            from urllib.parse import urlparse
                            parsed_url = urlparse(website_url)
                            logo_src = f"{parsed_url.scheme}://{parsed_url.netloc}{logo_src}"
                        elif not logo_src.startswith(('http://', 'https://')):
                            logo_src = urljoin(website_url, logo_src)
                        
                        # Vérifier que l'image existe et n'est pas trop petite
                        if self.validate_logo_image(logo_src):
                            logger.info(f"✓ Logo trouvé avec sélecteur '{selector}': {logo_src}")
                            return logo_src
            
            # Fallback avancé: chercher dans le header par position
            header = soup.find('header') or soup.find('div', class_=re.compile('header', re.I)) or soup.find('nav')
            if header:
                # Chercher toutes les images dans le header
                header_imgs = header.find_all('img')
                
                for img in header_imgs:
                    if img.get('src'):
                        logo_src = img.get('src')
                        alt_text = img.get('alt', '').lower()
                        src_text = logo_src.lower()
                        
                        # Vérifier si c'est probablement un logo
                        if ('logo' in alt_text or 'logo' in src_text or 
                            img.get('class') and any('logo' in str(cls).lower() for cls in img.get('class'))):
                            
                            # Convertir en URL absolue
                            if logo_src.startswith('/'):
                                from urllib.parse import urlparse
                                parsed_url = urlparse(website_url)
                                logo_src = f"{parsed_url.scheme}://{parsed_url.netloc}{logo_src}"
                            elif not logo_src.startswith(('http://', 'https://')):
                                logo_src = urljoin(website_url, logo_src)
                            
                            if self.validate_logo_image(logo_src):
                                logger.info(f"✓ Logo fallback trouvé dans header: {logo_src}")
                                return logo_src
                
                # Si toujours pas trouvé, prendre la première image significative du header
                for img in header_imgs[:3]:  # Limiter aux 3 premières images
                    if img.get('src'):
                        logo_src = img.get('src')
                        
                        # Filtrer les icônes et petites images
                        if any(exclude in logo_src.lower() for exclude in ['icon', 'arrow', 'menu', 'search', 'close']):
                            continue
                        
                        # Convertir en URL absolue
                        if logo_src.startswith('/'):
                            from urllib.parse import urlparse
                            parsed_url = urlparse(website_url)
                            logo_src = f"{parsed_url.scheme}://{parsed_url.netloc}{logo_src}"
                        elif not logo_src.startswith(('http://', 'https://')):
                            logo_src = urljoin(website_url, logo_src)
                        
                        if self.validate_logo_image(logo_src):
                            logger.info(f"✓ Logo par position trouvé: {logo_src}")
                            return logo_src
            
        except Exception as e:
            logger.warning(f"Erreur lors de l'extraction du logo: {e}")
        
        return None

    def validate_logo_image(self, logo_url):
        """
        Valide qu'une URL d'image est probablement un logo valide
        """
        try:
            # Vérifier que l'URL semble valide
            if not logo_url or len(logo_url) < 10:
                return False
            
            # Vérifier l'extension d'image
            valid_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']
            if not any(ext in logo_url.lower() for ext in valid_extensions):
                return False
            
            # Faire une requête HEAD pour vérifier que l'image existe
            try:
                head_response = self.session.head(logo_url, timeout=5)
                if head_response.status_code == 200:
                    content_type = head_response.headers.get('content-type', '')
                    if 'image' in content_type:
                        return True
            except:
                # Si HEAD échoue, essayer GET avec un petit timeout
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

    def search_organization_online(self, organization_name):
        """
        Fait une recherche web pour trouver le site officiel et le logo de l'organisation
        """
        org_info = {
            'organization_website': None,
            'organization_logo': None
        }
        
        try:
            # Recherche du site officiel
            search_query = f"{organization_name} official website"
            logger.info(f"Recherche web: {search_query}")
            
            search_response = self.session.get(
                "https://www.google.com/search",
                params={'q': search_query, 'num': 5},
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                },
                timeout=10
            )
            
            if search_response.status_code == 200:
                soup = BeautifulSoup(search_response.text, 'html.parser')
                
                # Extraire les liens des résultats de recherche
                result_links = []
                for result in soup.find_all('a', href=True):
                    href = result.get('href')
                    if href and '/url?q=' in href:
                        # Nettoyer l'URL Google
                        actual_url = href.split('/url?q=')[1].split('&')[0]
                        if actual_url.startswith('http') and 'google.com' not in actual_url:
                            result_links.append(actual_url)
                
                # Prendre le premier résultat crédible
                for url in result_links[:3]:
                    try:
                        # Vérifier si l'URL semble être le site officiel
                        domain_keywords = ['official', 'org', 'com', organization_name.lower().replace(' ', '')]
                        if any(keyword in url.lower() for keyword in domain_keywords):
                            org_info['organization_website'] = url
                            logger.info(f"✓ Site web trouvé via recherche: {url}")
                            
                            # Essayer d'extraire le logo
                            org_info['organization_logo'] = self.extract_logo_from_website(url)
                            break
                    except:
                        continue
            
        except Exception as e:
            logger.warning(f"Erreur lors de la recherche web: {e}")
        
        return org_info

    def analyze_with_llm(self, article_data):
        """
        Analyse le contenu avec Gemini AI pour extraire les métadonnées
        """
        try:
            prompt = self.llm_prompt.format(
                content=article_data.get('content', '')[:3000],  # Limiter la taille
                title=article_data.get('title', ''),
                published_date=article_data.get('published_date', '')
            )
            
            response = self.model.generate_content(prompt)
            
            # Parser la réponse JSON
            json_text = response.text.strip()
            if json_text.startswith('```json'):
                json_text = json_text[7:-3]
            elif json_text.startswith('```'):
                json_text = json_text[3:-3]
            
            llm_result = json.loads(json_text)
            
            # S'assurer que extracted_published_date et extracted_deadline sont bien formatées
            # Si le LLM a mis quelque chose d'incorrect, utiliser nos extractions
            if article_data.get('published_date'):
                # Vérifier si c'est vraiment une date
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
                # Vérifier si c'est vraiment une date/deadline
                deadline = article_data['deadline'].strip()
                
                # Nettoyer la deadline pour extraire seulement la date
                clean_deadline = self.extract_clean_date(deadline)
                
                if clean_deadline and self.is_valid_date(clean_deadline):
                    llm_result['extracted_deadline'] = clean_deadline
                else:
                    llm_result['extracted_deadline'] = None
            else:
                llm_result['extracted_deadline'] = None
            
            return llm_result
            
        except Exception as e:
            logger.error(f"Erreur LLM: {e}")
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

    def extract_clean_date(self, text):
        """
        Extrait une date propre à partir d'un texte qui peut contenir du texte supplémentaire
        Exemple: "june 29, with winning startups..." → "june 29"
        """
        if not text:
            return None
        
        text_lower = text.lower().strip()
        
        # Patterns pour extraire seulement la partie date
        date_patterns = [
            r'^([a-z]+\s+\d{1,2},?\s+\d{4})',                    # june 29, 2024 (début)
            r'^(\d{1,2}\s+[a-z]+\s+\d{4})',                      # 29 june 2024 (début)
            r'^(\d{1,2}[-/]\d{1,2}[-/]\d{4})',                   # 29/06/2024 (début)
            r'^(\d{4}[-/]\d{1,2}[-/]\d{1,2})',                   # 2024/06/29 (début)
            r'\b([a-z]+\s+\d{1,2},?\s+\d{4})\b',                 # june 29, 2024 (n'importe où)
            r'\b(\d{1,2}\s+[a-z]+\s+\d{4})\b',                   # 29 june 2024 (n'importe où)
            r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b',                # 29/06/2024 (n'importe où)
            r'\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b',                # 2024/06/29 (n'importe où)
            r'^([a-z]+\s+\d{1,2})',                              # june 29 (sans année, début)
            r'\b([a-z]+\s+\d{1,2})\b'                            # june 29 (sans année, n'importe où)
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text_lower)
            if match:
                extracted_date = match.group(1).strip()
                # Vérifier que c'est une vraie date
                if self.is_valid_date(extracted_date) or self.is_partial_date(extracted_date):
                    return extracted_date
        
        return None

    def is_partial_date(self, date_str):
        """
        Vérifie si c'est une date partielle valide (ex: "june 29" sans année)
        """
        if not date_str:
            return False
        
        date_str_lower = date_str.lower()
        
        # Vérifier format "mois jour" (ex: "june 29")
        month_day_pattern = r'^([a-z]+)\s+(\d{1,2})'
        match = re.search(month_day_pattern, date_str_lower)
        
        if match:
            month = match.group(1)
            day = int(match.group(2))
            
            # Vérifier que c'est un vrai mois
            valid_months = [
                'january', 'february', 'march', 'april', 'may', 'june',
                'july', 'august', 'september', 'october', 'november', 'december',
                'jan', 'feb', 'mar', 'apr', 'may', 'jun',
                'jul', 'aug', 'sep', 'oct', 'nov', 'dec'
            ]
            
            # Vérifier que c'est un jour valide (1-31)
            return month in valid_months and 1 <= day <= 31
        
        return False

    def is_valid_date(self, date_str):
        """
        Vérifie si une chaîne ressemble à une vraie date
        """
        if not date_str:
            return False
        
        date_str_lower = date_str.lower()
        
        # Vérifier la présence d'un mois
        has_month = any(month in date_str_lower for month in [
            'january', 'february', 'march', 'april', 'may', 'june',
            'july', 'august', 'september', 'october', 'november', 'december',
            'jan', 'feb', 'mar', 'apr', 'may', 'jun',
            'jul', 'aug', 'sep', 'oct', 'nov', 'dec'
        ])
        
        # Vérifier la présence d'une année
        has_year = re.search(r'\d{4}', date_str)
        
        # Ou format numérique de date
        is_numeric_date = re.search(r'\d{1,2}[-/]\d{1,2}[-/]\d{4}', date_str)
        
        return (has_month and has_year) or is_numeric_date

    def create_slug(self, title):
        """
        Crée un slug URL à partir du titre
        """
        if not title:
            return ""
        
        slug = title.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug)
        slug = slug.strip('-')
        return slug

    def scrape_opportunities(self):
        """
        Fonction principale pour scraper toutes les opportunités
        """
        all_opportunities = []
        
        for base_url in self.base_urls:
            logger.info(f"Scraping: {base_url}")
            
            # Obtenir les URLs des 3 premières pages
            page_urls = self.get_pagination_urls(base_url, max_pages=3)
            
            for page_url in page_urls:
                logger.info(f"Page: {page_url}")
                
                # Récupérer le contenu de la page
                html_content = self.get_page_content_static(page_url)
                if not html_content:
                    html_content = self.get_page_content_dynamic(page_url)
                
                if not html_content:
                    continue
                
                # Extraire les liens des articles
                article_links = self.extract_article_links(html_content, page_url)
                
                # Traiter chaque article
                for i, article_url in enumerate(article_links):
                    try:
                        logger.info(f"Traitement article {i+1}/{len(article_links)}: {article_url}")
                        
                        # Extraire les données de l'article
                        article_data = self.extract_article_data(article_url)
                        
                        if article_data and article_data.get('title'):
                            # Analyser avec LLM
                            llm_data = self.analyze_with_llm(article_data)
                            
                            # Extraire les informations de l'organisation si le LLM a trouvé un nom
                            organization_name = llm_data.get('organization_name')
                            if organization_name and article_data.get('soup'):
                                logger.info(f"Organisation détectée: {organization_name}")
                                org_info = self.extract_organization_info(article_data['soup'], organization_name)
                                
                                # Mettre à jour les données LLM avec les infos trouvées
                                llm_data.update(org_info)
                            
                            # Combiner les données avec mapping correct
                            opportunity = {
                                **article_data,
                                **llm_data,
                                # Mapper les champs correctement
                                'extracted_published_date': article_data.get('published_date'),
                                'extracted_deadline': article_data.get('deadline')
                            }
                            
                            # Supprimer les anciens champs pour éviter la duplication et nettoyer
                            fields_to_remove = ['published_date', 'deadline', 'soup']
                            for field in fields_to_remove:
                                if field in opportunity:
                                    del opportunity[field]
                            
                            all_opportunities.append(opportunity)
                            
                            logger.info(f"✓ Article traité: {article_data['title'][:60]}...")
                            
                            # Pause plus longue pour éviter de surcharger le serveur
                            time.sleep(3 + (len(all_opportunities) % 3))  # 3-5 secondes variables
                        else:
                            logger.warning(f"Données manquantes pour: {article_url}")
                            
                    except Exception as e:
                        logger.error(f"Erreur lors du traitement de {article_url}: {e}")
                        # Continuer avec l'article suivant même en cas d'erreur
                        time.sleep(2)  # Pause même en cas d'erreur
                        continue
        
        return all_opportunities

    def save_to_json(self, opportunities, filename="disruptafrica_opportunities.json"):
        """
        Sauvegarde les opportunités dans un fichier JSON
        """
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(opportunities, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Données sauvegardées dans {filename}")

# Exemple d'utilisation
def main():
    # La clé API sera automatiquement chargée depuis config.env
    scraper = DisruptAfricaScraper()
    
    try:
        # Lancer le scraping
        opportunities = scraper.scrape_opportunities()
        
        # Sauvegarder les résultats
        scraper.save_to_json(opportunities)
        
        print(f"Scraping terminé. {len(opportunities)} opportunités extraites.")
        
        # Afficher un exemple
        if opportunities:
            print("\nExemple d'opportunité:")
            print(json.dumps(opportunities[0], indent=2, ensure_ascii=False))
            
    except Exception as e:
        logger.error(f"Erreur générale: {e}")

if __name__ == "__main__":
    main()