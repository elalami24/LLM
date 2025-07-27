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

class AfricanOpportunitiesScraper:
    def __init__(self, gemini_api_key=None):
        """
        Initialise le scraper pour les sites d'opportunités africaines
        """
        self.base_urls = [
            "https://www.opportunitiesforafricans.com/",
            "https://msmeafricaonline.com/category/opportunities/",
            "https://opportunitydesk.org/category/search-by-region/africa/"
        ]
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.session.mount('http://', requests.adapters.HTTPAdapter(max_retries=3))
        self.session.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))
        
        # Configuration Gemini AI
        api_key = gemini_api_key or os.getenv('GEMINI_API_KEY')
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
                raise ValueError("Impossible de configurer Gemini AI")
        
        # Prompt simplifié pour les nouveaux sites
        self.llm_prompt = """
        Analysez le contenu suivant d'une opportunité et extrayez les informations demandées.
        
        Titre: {title}
        Contenu: {content}
        Date de publication: {published_date}
        Deadline trouvée: {deadline}
        
        Veuillez fournir UNIQUEMENT un JSON valide avec ces clés :
        - meta_title: Titre optimisé SEO (max 100 caractères)
        - meta_description: Description meta (max 160 caractères)
        - slug: URL slug (minuscules, tirets)
        - regions: Liste des régions (choisir parmi: ["Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi", "Cabo Verde", "Cameroon", "Central African Republic", "Chad", "Comoros", "Congo", "Côte d'Ivoire", "DR Congo", "Djibouti", "Egypt", "Equatorial Guinea", "Eritrea", "Eswatini", "Ethiopia", "Gabon", "Guinea", "Guinea-Bissau", "Kenya", "Lesotho", "Liberia", "Libya", "Madagascar", "Malawi", "Mali", "Mauritania", "Mauritius", "Morocco", "Mozambique", "Namibia", "Niger", "Nigeria", "Rwanda", "Sao Tome & Principe", "Senegal", "Seychelles", "Sierra Leone", "Somalia", "South Africa", "South Sudan", "Sudan", "Tanzania", "Togo", "Tunisia", "Uganda", "Zambia", "Zimbabwe"])
        - sectors: Liste des secteurs (choisir parmi: ["Regulatory Tech", "Spatial Computing", "AgriTech", "Agribusiness", "Artificial Intelligence", "Banking", "Blockchain", "Business Process Outsourcing (BPO)", "CleanTech", "Creative", "Cryptocurrencies", "Cybersecurity & Digital ID", "Data Aggregation", "Debt Management", "DeepTech", "Design & Applied Arts", "Digital & Interactive", "E-commerce and Retail", "Economic Development", "EdTech", "Energy", "Environmental Social Governance (ESG)", "FinTech", "Gaming", "HealthTech", "InsurTech", "Logistics", "ManuTech", "Manufacturing", "Media & Communication", "Mobility and Transportation", "Performing & Visual Arts", "Sector Agnostic", "Sport Management", "Sustainability", "Technology", "Tourism Innovation", "Transformative Digital Technologies", "Wearables"])
        - stages: Liste des étapes (choisir parmi: ["Not Applicable", "Pre-Series A", "Pre-seed", "Seed", "Series A", "Series B", "Series C", "Series D", "Series E", "Series F", "Stage Agnostic"])
        - categories: Liste des catégories (choisir parmi: ["Accelerator", "Bootcamp", "Competition", "Conference", "Event", "Funding Opportunity", "Hackathon", "Incubator", "Other", "Summit"])
        - draft_summary: Résumé naturel en 2-3 lignes basé sur le contenu
        - main_image_alt: Texte alternatif pour l'image principale
        - organizer_logo_alt: Texte alternatif pour le logo de l'organisateur (ou null si pas d'organisateur)
        - extracted_published_date: Date de publication (format YYYY-MM-DD ou null)
        - extracted_deadline: Date limite d'application (format YYYY-MM-DD ou null)
        - organization_name: Nom de l'organisation trouvée dans le contenu (ou null si non trouvé)
        - organization_website: null (sera recherché séparément)
        - organization_logo: null (sera recherché séparément)
        """

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
        """Extrait les liens des articles depuis la page de liste"""
        soup = BeautifulSoup(html_content, 'html.parser')
        links = []
        
        # Patterns génériques pour différents sites
        article_selectors = [
            # Pour opportunitiesforafricans.com
            'article a',
            '.post-title a',
            '.entry-title a',
            'h2 a',
            'h3 a',
            
            # Pour msmeafricaonline.com
            '.entry-header a',
            '.post-header a',
            '.blog-post a',
            
            # Pour opportunitydesk.org
            '.post-item a',
            '.opportunity-item a',
            '.entry a',
            
            # Sélecteurs génériques
            'article h1 a',
            'article h2 a',
            'article h3 a',
            '.post a[href*="/"]',
            '.entry a[href*="/"]'
        ]
        
        for selector in article_selectors:
            elements = soup.select(selector)
            for element in elements:
                href = element.get('href')
                if href and not href.startswith('#'):
                    full_url = urljoin(base_url, href)
                    
                    # Filtrage amélioré des liens non pertinents
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
                    
                    # Vérifier si l'URL contient des patterns à exclure
                    should_exclude = any(pattern in full_url.lower() for pattern in exclude_patterns)
                    
                    # Vérifier que c'est bien un article du même domaine
                    base_domain = urlparse(base_url).netloc
                    link_domain = urlparse(full_url).netloc
                    is_same_domain = base_domain in link_domain or link_domain in base_domain
                    
                    if not should_exclude and is_same_domain and full_url not in links:
                        # Vérifier que le lien semble être un article (contient des segments d'URL)
                        url_path = urlparse(full_url).path
                        if len(url_path.split('/')) >= 3:  # Au moins /category/article-title/
                            links.append(full_url)
        
        # Dédupliquer et trier par longueur (articles ont généralement des URLs plus longues)
        unique_links = list(set(links))
        unique_links.sort(key=len, reverse=True)
        
        logger.info(f"Trouvé {len(unique_links)} liens d'articles valides après filtrage")
        return unique_links[:15]  # Limiter à 15 articles par page

    def extract_article_data(self, url):
        """Extrait les données d'un article spécifique"""
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
            'deadline': None,
            'content': None,
            'soup': soup
        }
        
        # Extraction du titre
        title_selectors = [
            'h1.entry-title',
            'h1.post-title', 
            'h1.page-title',
            'h1',
            '.entry-title',
            '.post-title',
            'title'
        ]
        
        for selector in title_selectors:
            title_elem = soup.select_one(selector)
            if title_elem:
                data['title'] = title_elem.get_text(strip=True)
                break
        
        # Extraction de la date de publication
        date_selectors = [
            'time',
            '.published',
            '.post-date',
            '.entry-date',
            '.date',
            '.post-meta time',
            '.entry-meta time'
        ]
        
        for selector in date_selectors:
            date_elem = soup.select_one(selector)
            if date_elem:
                # Essayer l'attribut datetime d'abord
                datetime_attr = date_elem.get('datetime')
                if datetime_attr:
                    data['published_date'] = datetime_attr
                    break
                
                # Sinon, prendre le texte
                date_text = date_elem.get_text(strip=True)
                if date_text and re.search(r'\d{4}', date_text):
                    data['published_date'] = date_text
                    break
        
        # Si pas trouvé, chercher dans le texte
        if not data['published_date']:
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
                        data['published_date'] = potential_date
                        break
        
        # Extraction du contenu principal
        content_selectors = [
            '.entry-content',
            '.post-content',
            '.content',
            '.post-body',
            'article .content',
            '.single-content',
            '.post-text'
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
            
            data['content'] = content_elem.get_text(strip=True)
        else:
            # Fallback: tout le texte de l'article
            data['content'] = soup.get_text(strip=True)
        
        # Extraction de la deadline
        if data['content']:
            data['deadline'] = self.extract_deadline(data['content'])
        
        return data

    def extract_deadline(self, content):
        """Extrait la deadline du contenu"""
        content_lower = content.lower()
        
        # Patterns pour deadline
        deadline_patterns = [
            r'application deadline[:\s]*([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?,?\s+\d{4})',
            r'deadline[:\s]*([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?,?\s+\d{4})',
            r'apply by[:\s]*([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?,?\s+\d{4})',
            r'applications?.*?close[s]?.*?([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?,?\s+\d{4})',
            r'deadline[:\s]*(\d{1,2}(?:th|st|nd|rd)?\s+[a-z]+\s+\d{4})',
            r'until[:\s]*([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?,?\s+\d{4})',
            r'until[:\s]*(\d{1,2}(?:th|st|nd|rd)?\s+[a-z]+\s+\d{4})',
            
            # Sans année
            r'deadline[:\s]*([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?)',
            r'apply by[:\s]*([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?)',
            r'until[:\s]*([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?)',
            
            # Formats avec "Application Deadline: August 9th, 2025"
            r'application deadline:\s*([a-z]+\s+\d{1,2}(?:th|st|nd|rd)?,?\s+\d{4})',
        ]
        
        for pattern in deadline_patterns:
            match = re.search(pattern, content_lower)
            if match:
                potential_deadline = match.group(1).strip()
                # Nettoyer les ordinaux
                potential_deadline = re.sub(r'(\d+)(?:th|st|nd|rd)', r'\1', potential_deadline)
                
                if self.is_valid_date(potential_deadline):
                    return potential_deadline
        
        return None

    def is_valid_date(self, date_str):
        """Vérifie si une chaîne ressemble à une vraie date"""
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
        
        # Vérifier la présence d'une année ou d'un jour
        has_year = re.search(r'\d{4}', date_str)
        has_day = re.search(r'\d{1,2}', date_str)
        
        return has_month and (has_year or has_day)

    def search_organization_online(self, organization_name):
        """Recherche en ligne les infos de l'organisation"""
        if not organization_name:
            return {'organization_website': None, 'organization_logo': None}
        
        try:
            search_query = f"{organization_name} official website"
            logger.info(f"Recherche web: {search_query}")
            
            search_response = self.session.get(
                "https://www.google.com/search",
                params={'q': search_query, 'num': 3},
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                timeout=10
            )
            
            if search_response.status_code == 200:
                soup = BeautifulSoup(search_response.text, 'html.parser')
                
                # Extraire les liens des résultats
                for result in soup.find_all('a', href=True):
                    href = result.get('href')
                    if href and '/url?q=' in href:
                        actual_url = href.split('/url?q=')[1].split('&')[0]
                        if actual_url.startswith('http') and 'google.com' not in actual_url:
                            # Tenter d'extraire le logo
                            logo_url = self.extract_logo_from_website(actual_url)
                            return {
                                'organization_website': actual_url,
                                'organization_logo': logo_url
                            }
        except Exception as e:
            logger.warning(f"Erreur lors de la recherche web: {e}")
        
        return {'organization_website': None, 'organization_logo': None}

    def extract_logo_from_website(self, website_url):
        """Extrait le logo d'un site web"""
        try:
            if not website_url.startswith(('http://', 'https://')):
                website_url = 'https://' + website_url
            
            response = self.session.get(website_url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            logo_selectors = [
                'img[alt*="logo" i]',
                'img[src*="logo" i]',
                '.logo img',
                'header img',
                '.navbar-brand img'
            ]
            
            for selector in logo_selectors:
                logo_img = soup.select_one(selector)
                if logo_img and logo_img.get('src'):
                    logo_src = logo_img.get('src')
                    
                    if logo_src.startswith('/'):
                        parsed_url = urlparse(website_url)
                        logo_src = f"{parsed_url.scheme}://{parsed_url.netloc}{logo_src}"
                    elif not logo_src.startswith(('http://', 'https://')):
                        logo_src = urljoin(website_url, logo_src)
                    
                    return logo_src
        except Exception as e:
            logger.warning(f"Erreur extraction logo: {e}")
        
        return None

    def analyze_with_llm(self, article_data):
        """Analyse le contenu avec Gemini AI"""
        try:
            prompt = self.llm_prompt.format(
                title=article_data.get('title', ''),
                content=article_data.get('content', '')[:3000],
                published_date=article_data.get('published_date', ''),
                deadline=article_data.get('deadline', '')
            )
            
            response = self.model.generate_content(prompt)
            json_text = response.text.strip()
            
            if json_text.startswith('```json'):
                json_text = json_text[7:-3]
            elif json_text.startswith('```'):
                json_text = json_text[3:-3]
            
            return json.loads(json_text)
            
        except Exception as e:
            logger.error(f"Erreur LLM: {e}")
            return {
                'meta_title': article_data.get('title', '')[:100],
                'meta_description': '',
                'slug': self.create_slug(article_data.get('title', '')),
                'regions': [],
                'sectors': [],
                'stages': [],
                'categories': [],
                'draft_summary': '',
                'main_image_alt': None,
                'organizer_logo_alt': None,
                'extracted_published_date': article_data.get('published_date'),
                'extracted_deadline': article_data.get('deadline'),
                'organization_name': None,
                'organization_website': None,
                'organization_logo': None
            }

    def create_slug(self, title):
        """Crée un slug URL à partir du titre"""
        if not title:
            return ""
        
        slug = title.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug)
        return slug.strip('-')

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

    def scrape_opportunities(self):
        """Fonction principale pour scraper toutes les opportunités"""
        all_opportunities = []
        
        for base_url in self.base_urls:
            logger.info(f"Scraping: {base_url}")
            
            page_urls = self.get_pagination_urls(base_url, max_pages=3)
            
            for page_url in page_urls:
                logger.info(f"Page: {page_url}")
                
                html_content = self.get_page_content_static(page_url)
                if not html_content:
                    html_content = self.get_page_content_dynamic(page_url)
                
                if not html_content:
                    continue
                
                article_links = self.extract_article_links(html_content, page_url)
                
                for i, article_url in enumerate(article_links):
                    try:
                        logger.info(f"Traitement article {i+1}/{len(article_links)}: {article_url}")
                        
                        article_data = self.extract_article_data(article_url)
                        
                        if article_data and article_data.get('title') and article_data.get('content'):
                            # Vérifier que ce n'est pas une page d'erreur ou vide
                            if len(article_data['content']) > 200:  # Au moins 200 caractères
                                # Analyser avec LLM
                                llm_data = self.analyze_with_llm(article_data)
                                
                                # Rechercher les infos de l'organisation
                                organization_name = llm_data.get('organization_name')
                                if organization_name:
                                    logger.info(f"Organisation détectée: {organization_name}")
                                    org_info = self.search_organization_online(organization_name)
                                    llm_data.update(org_info)
                                
                                # Combiner les données
                                opportunity = {
                                    'url': article_data['url'],
                                    'title': article_data['title'],
                                    'content': article_data['content'],
                                    **llm_data,
                                    'extracted_published_date': article_data.get('published_date'),
                                    'extracted_deadline': article_data.get('deadline')
                                }
                                
                                all_opportunities.append(opportunity)
                                logger.info(f"✓ Article traité: {article_data['title'][:60]}...")
                            else:
                                logger.warning(f"Contenu trop court pour: {article_url}")
                        else:
                            logger.warning(f"Données manquantes pour: {article_url}")
                        
                        time.sleep(2)  # Pause entre articles
                            
                    except Exception as e:
                        logger.error(f"Erreur lors du traitement de {article_url}: {e}")
                        continue
        
        return all_opportunities

    def save_to_json(self, opportunities, filename="african_opportunities.json"):
        """Sauvegarde les opportunités dans un fichier JSON"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(opportunities, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Données sauvegardées dans {filename}")

def main():
    scraper = AfricanOpportunitiesScraper()
    
    try:
        opportunities = scraper.scrape_opportunities()
        scraper.save_to_json(opportunities)
        
        print(f"Scraping terminé. {len(opportunities)} opportunités extraites.")
        
        if opportunities:
            print("\nExemple d'opportunité:")
            print(json.dumps(opportunities[0], indent=2, ensure_ascii=False))
            
    except Exception as e:
        logger.error(f"Erreur générale: {e}")

if __name__ == "__main__":
    main()