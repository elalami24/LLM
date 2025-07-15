import asyncio
import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from urllib.parse import urljoin, urlparse
import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import google.generativeai as genai
import re
import logging
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv("config.env")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class OpportunityData:
    """Data class representing the opportunity schema"""
    opportunity_id: str
    title: str
    subtitle: str
    meta_title: str
    meta_description: str
    slug: str
    organizer_name: str
    organizer_website: str
    organizer_logo: str
    organizer_logo_alt: str
    program_url: str
    main_image: str
    main_image_alt: str
    regions: List[str]
    sectors: List[str]
    stages: List[str]
    categories: List[str]
    published_date: Optional[str]
    application_deadline: Optional[str]
    description: str
    draft_summary: str
    status: str = "draft"

class OpportunityScraper:
    def __init__(self, gemini_api_key: str = None):
        self.session = None
        self.playwright = None
        self.browser = None
        
        # Configure Gemini
        if gemini_api_key:
            genai.configure(api_key=gemini_api_key)
            self.gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        else:
            self.gemini_model = None
        
        # Site-specific configurations
        self.site_configs = {
            'disruptafrica.com': {
                'selectors': {
                    'title': 'h1.entry-title, h1.post-title, .title, h1',
                    'content': '.entry-content, .post-content, .content, article',
                    'date': '.entry-date, .post-date, .date, time',
                    'organizer': '.organizer, .company, .organization, .author',
                    'deadline': '.deadline, .apply-by, .application-deadline',
                    'image': '.featured-image img, .post-image img, .wp-post-image',
                    'links': 'a[href*="apply"], a[href*="register"], a[href*="submit"]'
                },
                'pagination': '.pagination a, .next-page'
            },
            'vc4a.com': {
                'selectors': {
                    'title': 'h1, .program-title, .title',
                    'content': '.program-description, .content, .description',
                    'date': '.date, .published, .created',
                    'organizer': '.organizer, .partner, .company',
                    'deadline': '.deadline, .apply-deadline, .closing-date',
                    'image': '.program-image img, .featured-image img',
                    'links': 'a[href*="apply"], a[href*="join"]'
                }
            },
            'opportunitiesforafricans.com': {
                'selectors': {
                    'title': 'h1.entry-title, .post-title, h1',
                    'content': '.entry-content, .post-content, .content',
                    'date': '.entry-date, .post-date, time',
                    'organizer': '.organizer, .sponsor, .author',
                    'deadline': '.deadline, .closing-date, .apply-by',
                    'image': '.featured-image img, .wp-post-image',
                    'links': 'a[href*="apply"], a[href*="link"]'
                }
            },
            'msmeafricaonline.com': {
                'selectors': {
                    'title': 'h1.entry-title, h1, .title',
                    'content': '.entry-content, .content, article',
                    'date': '.entry-date, .date, time',
                    'organizer': '.organizer, .author',
                    'deadline': '.deadline, .closing-date',
                    'image': '.wp-post-image, .featured-image img',
                    'links': 'a[href*="apply"]'
                }
            },
            'opportunitydesk.org': {
                'selectors': {
                    'title': 'h1.entry-title, .post-title, h1',
                    'content': '.entry-content, .post-content, .content',
                    'date': '.entry-date, .post-date, time',
                    'organizer': '.organizer, .sponsor, .author',
                    'deadline': '.deadline, .application-deadline',
                    'image': '.featured-image img, .wp-post-image',
                    'links': 'a[href*="apply"], a[href*="register"]'
                }
            }
        }

    async def __aenter__(self):
        # Configure session with headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.session = aiohttp.ClientSession(headers=headers)
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def crawl_category_urls(self, base_url: str, max_pages: int = 5) -> List[str]:
        """Crawl category pages to extract opportunity URLs"""
        opportunity_urls = []
        domain = urlparse(base_url).netloc
        
        for page in range(1, max_pages + 1):
            try:
                # Construct paginated URL
                if page == 1:
                    url = base_url
                else:
                    url = f"{base_url}page/{page}/" if base_url.endswith('/') else f"{base_url}/page/{page}/"
                
                logger.info(f"Crawling page {page}: {url}")
                
                async with self.session.get(url) as response:
                    if response.status != 200:
                        logger.warning(f"Failed to fetch {url}: {response.status}")
                        continue
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Extract opportunity URLs based on common patterns
                    links = soup.find_all('a', href=True)
                    page_urls = []
                    
                    for link in links:
                        href = link.get('href')
                        if self._is_opportunity_url(href, domain):
                            full_url = urljoin(base_url, href)
                            if full_url not in opportunity_urls:
                                opportunity_urls.append(full_url)
                                page_urls.append(full_url)
                    
                    logger.info(f"Found {len(page_urls)} opportunities on page {page}")
                    
                    # If no opportunities found, we might have reached the end
                    if not page_urls and page > 1:
                        break
                        
            except Exception as e:
                logger.error(f"Error crawling {url}: {e}")
                
        logger.info(f"Total opportunities found: {len(opportunity_urls)}")
        return opportunity_urls

    def _is_opportunity_url(self, href: str, domain: str) -> bool:
        """Check if a URL is likely an opportunity page"""
        if not href:
            return False
            
        # Skip unwanted URLs
        skip_patterns = [
            '/category/', '/tag/', '/author/', '/page/', '/search/',
            '#', 'javascript:', 'mailto:', 'tel:', '.pdf', '.doc',
            '/wp-admin/', '/wp-content/', '/comments/', '/feed/',
            '/privacy/', '/about/', '/contact/', '/terms/'
        ]
        
        for pattern in skip_patterns:
            if pattern in href:
                return False
        
        # Check for opportunity-related patterns
        opportunity_patterns = [
            'opportunity', 'program', 'competition', 'grant', 'fellowship',
            'scholarship', 'accelerator', 'incubator', 'startup', 'funding',
            'award', 'prize', 'challenge', 'apply', 'open-call', 'call-for',
            'application', 'submit', 'register', 'participate'
        ]
        
        href_lower = href.lower()
        return any(pattern in href_lower for pattern in opportunity_patterns)

    async def scrape_opportunity_content(self, url: str, use_playwright: bool = False) -> Dict[str, Any]:
        """Scrape content from an opportunity page"""
        domain = urlparse(url).netloc
        config = self.site_configs.get(domain, self.site_configs['disruptafrica.com'])
        
        try:
            if use_playwright:
                # Use Playwright for dynamic content
                page = await self.browser.new_page()
                await page.goto(url, wait_until='networkidle')
                html = await page.content()
                await page.close()
            else:
                # Use aiohttp for static content
                async with self.session.get(url) as response:
                    if response.status != 200:
                        logger.warning(f"Failed to fetch {url}: {response.status}")
                        return {}
                    html = await response.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract data using selectors
            data = {
                'url': url,
                'title': self._extract_text(soup, config['selectors']['title']),
                'content': self._extract_text(soup, config['selectors']['content']),
                'published_date': self._extract_date(soup, config['selectors']['date']),
                'organizer': self._extract_text(soup, config['selectors']['organizer']),
                'deadline': self._extract_date(soup, config['selectors']['deadline']),
                'image_url': self._extract_image_url(soup, config['selectors']['image'], url),
                'apply_links': self._extract_links(soup, config['selectors']['links']),
                'organizer_website': self._extract_organizer_website(soup),
                'organizer_logo': self._extract_organizer_logo(soup, url)
            }
            
            return data
            
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return {}

    def _extract_text(self, soup: BeautifulSoup, selector: str) -> str:
        """Extract text using CSS selector"""
        selectors = selector.split(', ')
        for sel in selectors:
            elements = soup.select(sel)
            if elements:
                text = elements[0].get_text(strip=True)
                if text:
                    return text
        return ""

    def _extract_date(self, soup: BeautifulSoup, selector: str) -> Optional[str]:
        """Extract and parse date"""
        text = self._extract_text(soup, selector)
        if text:
            # Simple date extraction - can be enhanced with dateparser
            date_patterns = [
                r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}',
                r'\d{4}[/-]\d{1,2}[/-]\d{1,2}',
                r'\d{1,2}\s+\w+\s+\d{4}',
                r'\w+\s+\d{1,2},?\s+\d{4}'
            ]
            
            for pattern in date_patterns:
                date_match = re.search(pattern, text)
                if date_match:
                    return date_match.group()
        return None

    def _extract_image_url(self, soup: BeautifulSoup, selector: str, base_url: str) -> str:
        """Extract image URL"""
        selectors = selector.split(', ')
        for sel in selectors:
            elements = soup.select(sel)
            if elements:
                img_url = elements[0].get('src') or elements[0].get('data-src') or elements[0].get('data-lazy-src')
                if img_url:
                    return urljoin(base_url, img_url)
        return ""

    def _extract_links(self, soup: BeautifulSoup, selector: str) -> List[str]:
        """Extract application/registration links"""
        elements = soup.select(selector)
        links = []
        for element in elements:
            href = element.get('href')
            if href and href not in links:
                links.append(href)
        return links

    def _extract_organizer_website(self, soup: BeautifulSoup) -> str:
        """Extract organizer website from content"""
        # Look for links that might be organizer websites
        links = soup.find_all('a', href=True)
        for link in links:
            href = link.get('href')
            if href and any(domain in href for domain in ['.org', '.com', '.net', '.edu']):
                if not any(social in href for social in ['facebook', 'twitter', 'linkedin', 'instagram']):
                    return href
        return ""

    def _extract_organizer_logo(self, soup: BeautifulSoup, base_url: str) -> str:
        """Extract organizer logo"""
        # Look for logo images
        logo_selectors = [
            'img[alt*="logo"]', 'img[class*="logo"]', 
            '.logo img', '.brand img', '.organizer img'
        ]
        
        for selector in logo_selectors:
            elements = soup.select(selector)
            if elements:
                img_url = elements[0].get('src') or elements[0].get('data-src')
                if img_url:
                    return urljoin(base_url, img_url)
        return ""

    async def enrich_with_llm(self, scraped_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich scraped data with Gemini-generated content"""
        if not self.gemini_model:
            logger.warning("Gemini model not configured, skipping LLM enrichment")
            return self._create_basic_enrichment(scraped_data)
        
        try:
            content = scraped_data.get('content', '')
            title = scraped_data.get('title', '')
            
            prompt = f"""
            Analysez cette opportunité et fournissez des informations structurées en JSON :
            
            Titre: {title}
            Contenu: {content[:2000]}...
            
            Veuillez fournir UNIQUEMENT un JSON valide avec ces clés :
            - subtitle: Un sous-titre accrocheur (max 100 caractères)
            - meta_title: Titre optimisé SEO (max 60 caractères)  
            - meta_description: Description meta (max 160 caractères)
            - slug: URL slug (minuscules, tirets)
            - regions: Liste des régions (choisir parmi: ["Africa", "North Africa", "West Africa", "East Africa", "Southern Africa", "Central Africa", "Global"])
            - sectors: Liste des secteurs (ex: ["FinTech", "AgriTech", "HealthTech", "EdTech", "CleanTech", "E-commerce"])
            - stages: Liste des étapes (choisir parmi: ["Idea", "Early-stage", "Growth", "Scale-up", "Any"])
            - categories: Liste des catégories (choisir parmi: ["Grant", "Fellowship", "Accelerator", "Incubator", "Competition", "Award", "Scholarship", "Funding"])
            - draft_summary: Résumé naturel en 2-3 lignes
            - main_image_alt: Texte alternatif pour l'image principale
            - organizer_logo_alt: Texte alternatif pour le logo de l'organisateur
            
            Répondez UNIQUEMENT avec le JSON, sans texte supplémentaire.
            """
            
            response = await asyncio.to_thread(
                self.gemini_model.generate_content,
                prompt
            )
            
            content_text = response.text
            
            # Clean the response to extract JSON
            content_text = content_text.strip()
            if content_text.startswith('```json'):
                content_text = content_text[7:]
            if content_text.endswith('```'):
                content_text = content_text[:-3]
            content_text = content_text.strip()
            
            # Parse JSON response
            try:
                enriched_data = json.loads(content_text)
                return enriched_data
            except json.JSONDecodeError:
                logger.error(f"Failed to parse Gemini response as JSON: {content_text}")
                return self._create_basic_enrichment(scraped_data)
                
        except Exception as e:
            logger.error(f"Error in Gemini enrichment: {e}")
            return self._create_basic_enrichment(scraped_data)

    def _create_basic_enrichment(self, scraped_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create basic enrichment when LLM is not available"""
        title = scraped_data.get('title', '')
        
        return {
            'subtitle': title[:100] if title else 'Opportunity in Africa',
            'meta_title': title[:60] if title else 'African Opportunity',
            'meta_description': f"Learn about this opportunity: {title}"[:160],
            'slug': re.sub(r'[^\w\s-]', '', title.lower()).replace(' ', '-')[:50],
            'regions': ['Africa'],
            'sectors': ['General'],
            'stages': ['Any'],
            'categories': ['Opportunity'],
            'draft_summary': f"This is an opportunity for African entrepreneurs and professionals.",
            'main_image_alt': f"Image for {title}",
            'organizer_logo_alt': f"Logo of {scraped_data.get('organizer', 'organizer')}"
        }

    def create_opportunity_object(self, scraped_data: Dict[str, Any], enriched_data: Dict[str, Any]) -> OpportunityData:
        """Create the final opportunity object"""
        return OpportunityData(
            opportunity_id=str(uuid.uuid4()),
            title=scraped_data.get('title', ''),
            subtitle=enriched_data.get('subtitle', ''),
            meta_title=enriched_data.get('meta_title', ''),
            meta_description=enriched_data.get('meta_description', ''),
            slug=enriched_data.get('slug', ''),
            organizer_name=scraped_data.get('organizer', ''),
            organizer_website=scraped_data.get('organizer_website', ''),
            organizer_logo=scraped_data.get('organizer_logo', ''),
            organizer_logo_alt=enriched_data.get('organizer_logo_alt', ''),
            program_url=scraped_data.get('url', ''),
            main_image=scraped_data.get('image_url', ''),
            main_image_alt=enriched_data.get('main_image_alt', ''),
            regions=enriched_data.get('regions', []),
            sectors=enriched_data.get('sectors', []),
            stages=enriched_data.get('stages', []),
            categories=enriched_data.get('categories', []),
            published_date=scraped_data.get('published_date'),
            application_deadline=scraped_data.get('deadline'),
            description=scraped_data.get('content', ''),
            draft_summary=enriched_data.get('draft_summary', ''),
            status="draft"
        )

    async def process_opportunities(self, urls: List[str]) -> List[OpportunityData]:
        """Process multiple opportunity URLs"""
        opportunities = []
        
        for i, url in enumerate(urls, 1):
            logger.info(f"Processing {i}/{len(urls)}: {url}")
            
            try:
                # Scrape content
                scraped_data = await self.scrape_opportunity_content(url)
                
                if not scraped_data.get('title'):
                    logger.warning(f"No title found for {url}, trying with Playwright")
                    # Retry with Playwright for dynamic content
                    scraped_data = await self.scrape_opportunity_content(url, use_playwright=True)
                    
                    if not scraped_data.get('title'):
                        logger.warning(f"Still no title found for {url}, skipping")
                        continue
                
                # Enrich with LLM
                enriched_data = await self.enrich_with_llm(scraped_data)
                
                # Create opportunity object
                opportunity = self.create_opportunity_object(scraped_data, enriched_data)
                opportunities.append(opportunity)
                
                logger.info(f"Successfully processed: {opportunity.title}")
                
                # Add delay to be respectful
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Error processing {url}: {e}")
                continue
        
        return opportunities

    def save_to_json(self, opportunities: List[OpportunityData], filename: str):
        """Save opportunities to JSON file"""
        data = [asdict(opportunity) for opportunity in opportunities]
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        
        logger.info(f"Saved {len(opportunities)} opportunities to {filename}")

async def main():
    """Main execution function"""
    # Configuration avec votre clé API Gemini depuis le fichier config.env
    API_KEY = os.getenv("GEMINI_API_KEY")
    
    if not API_KEY:
        logger.error("❌ GEMINI_API_KEY non trouvée dans config.env")
        logger.info("📝 Créez un fichier config.env avec: GEMINI_API_KEY=votre_clé_ici")
        return
    
    logger.info(f"✅ Clé API chargée depuis config.env")
    
    # URLs cibles
    target_urls = [
        "https://disruptafrica.com/category/events/",
        "https://disruptafrica.com/category/hubs/",
        "https://vc4a.com/programs/",
        "https://www.opportunitiesforafricans.com/",
        "https://msmeafricaonline.com/category/opportunities/",
        "https://opportunitydesk.org/category/search-by-region/africa/"
    ]
    
    all_opportunities = []
    
    logger.info("Démarrage du scraping des opportunités africaines...")
    
    async with OpportunityScraper(API_KEY) as scraper:
        for base_url in target_urls:
            logger.info(f"Processing: {base_url}")
            
            try:
                # Crawl category pages
                opportunity_urls = await scraper.crawl_category_urls(base_url, max_pages=3)
                
                if not opportunity_urls:
                    logger.warning(f"No opportunities found for {base_url}")
                    continue
                
                # Process opportunities (limit to 10 per site)
                opportunities = await scraper.process_opportunities(opportunity_urls[:10])
                all_opportunities.extend(opportunities)
                
                logger.info(f"Processed {len(opportunities)} opportunities from {base_url}")
                
            except Exception as e:
                logger.error(f"Error processing {base_url}: {e}")
                continue
    
    # Save results
    if all_opportunities:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"african_opportunities_{timestamp}.json"
        
        # Create scraper instance just for saving
        scraper = OpportunityScraper()
        scraper.save_to_json(all_opportunities, filename)
        
        logger.info(f"🎉 Scraping terminé! Trouvé {len(all_opportunities)} opportunités")
        logger.info(f"📁 Fichier sauvegardé: {filename}")
        
        # Print sample data
        if all_opportunities:
            sample = all_opportunities[0]
            logger.info(f" Exemple d'opportunité: {sample.title}")
            logger.info(f" Organisateur: {sample.organizer_name}")
            logger.info(f" Régions: {', '.join(sample.regions)}")
            logger.info(f" URL: {sample.program_url}")
        
    else:
        logger.warning(" Aucune opportunité trouvée")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Arrêté par l'utilisateur")
    except Exception as e:
        logger.error(f" Erreur fatale: {e}")