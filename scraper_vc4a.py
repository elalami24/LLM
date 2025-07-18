import asyncio
import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from urllib.parse import urljoin, urlparse, parse_qs
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

class VC4AImprovedScraper:
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

    async def __aenter__(self):
        # Configure session with headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        self.session = aiohttp.ClientSession(headers=headers)
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=False)  # Set to False for debugging
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def discover_vc4a_opportunities(self) -> List[str]:
        """Discover VC4A opportunities using multiple strategies"""
        opportunity_urls = set()
        
        # Strategy 1: Direct program URLs from sitemap/API
        direct_urls = await self._get_direct_program_urls()
        opportunity_urls.update(direct_urls)
        
        # Strategy 2: Scrape main programs page with Playwright
        main_page_urls = await self._scrape_programs_page()
        opportunity_urls.update(main_page_urls)
        
        # Strategy 3: Search for specific program types
        search_urls = await self._search_specific_programs()
        opportunity_urls.update(search_urls)
        
        return list(opportunity_urls)

    async def _get_direct_program_urls(self) -> List[str]:
        """Try to get direct program URLs from known patterns"""
        urls = []
        
        # Known VC4A program URL patterns
        base_patterns = [
            "https://vc4a.com/programs/",
            "https://vc4a.com/ventures/",
            "https://vc4a.com/blog/category/programs/",
            "https://vc4a.com/blog/category/opportunities/",
        ]
        
        for base_url in base_patterns:
            try:
                async with self.session.get(base_url) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Look for specific program links
                        links = soup.find_all('a', href=True)
                        for link in links:
                            href = link.get('href')
                            if self._is_valid_vc4a_opportunity(href):
                                full_url = urljoin(base_url, href)
                                urls.append(full_url)
                                
            except Exception as e:
                logger.error(f"Error fetching {base_url}: {e}")
        
        return urls

    async def _scrape_programs_page(self) -> List[str]:
        """Scrape the main programs page with Playwright for dynamic content"""
        urls = []
        
        try:
            page = await self.browser.new_page()
            
            # Go to programs page
            await page.goto("https://vc4a.com/programs/", wait_until='networkidle')
            
            # Wait for dynamic content to load
            await asyncio.sleep(5)
            
            # Look for program cards, links, or listings
            program_selectors = [
                'a[href*="/programs/"]',
                'a[href*="/ventures/"]',
                '.program-card a',
                '.opportunity-card a',
                '.program-listing a',
                '.venture-card a',
                'a[href*="apply"]',
                'a[href*="competition"]',
                'a[href*="accelerator"]',
                'a[href*="incubator"]',
            ]
            
            for selector in program_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for element in elements:
                        href = await element.get_attribute('href')
                        if href and self._is_valid_vc4a_opportunity(href):
                            full_url = urljoin("https://vc4a.com/", href)
                            urls.append(full_url)
                except Exception as e:
                    logger.debug(f"Error with selector {selector}: {e}")
            
            # Try to find pagination or "load more" buttons
            try:
                load_more_button = await page.query_selector('button:has-text("Load More"), .load-more, .pagination a')
                if load_more_button:
                    await load_more_button.click()
                    await asyncio.sleep(3)
                    
                    # Re-scrape after loading more content
                    for selector in program_selectors:
                        try:
                            elements = await page.query_selector_all(selector)
                            for element in elements:
                                href = await element.get_attribute('href')
                                if href and self._is_valid_vc4a_opportunity(href):
                                    full_url = urljoin("https://vc4a.com/", href)
                                    urls.append(full_url)
                        except Exception as e:
                            logger.debug(f"Error with selector {selector} after load more: {e}")
            except Exception as e:
                logger.debug(f"No load more button found: {e}")
            
            await page.close()
            
        except Exception as e:
            logger.error(f"Error scraping programs page with Playwright: {e}")
        
        return list(set(urls))

    async def _search_specific_programs(self) -> List[str]:
        """Search for specific program types and organizations"""
        urls = []
        
        # Known programs and organizations on VC4A
        search_terms = [
            "accelerator",
            "incubator", 
            "competition",
            "grant",
            "funding",
            "pitch",
            "startup",
            "entrepreneur",
            "innovation",
            "tech",
            "africa",
        ]
        
        for term in search_terms:
            try:
                search_url = f"https://vc4a.com/?s={term}"
                async with self.session.get(search_url) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        links = soup.find_all('a', href=True)
                        for link in links:
                            href = link.get('href')
                            if self._is_valid_vc4a_opportunity(href):
                                full_url = urljoin(search_url, href)
                                urls.append(full_url)
                                
            except Exception as e:
                logger.error(f"Error searching for {term}: {e}")
        
        return urls

    def _is_valid_vc4a_opportunity(self, href: str) -> bool:
        """Check if URL is a valid VC4A opportunity"""
        if not href:
            return False
        
        # Skip unwanted URLs
        skip_patterns = [
            '/login', '/register', '/wp-admin', '/wp-content',
            '/category/', '/tag/', '/author/', '/page/',
            '#', 'javascript:', 'mailto:', 'tel:',
            '/about', '/contact', '/privacy', '/terms',
            'facebook.com', 'twitter.com', 'linkedin.com',
            '.pdf', '.doc', '.png', '.jpg', '.gif'
        ]
        
        for pattern in skip_patterns:
            if pattern in href.lower():
                return False
        
        # Check for opportunity indicators
        opportunity_indicators = [
            '/programs/',
            '/ventures/',
            '/competitions/',
            '/accelerators/',
            '/incubators/',
            'program',
            'opportunity',
            'competition',
            'accelerator',
            'incubator',
            'grant',
            'funding',
            'apply',
            'pitch'
        ]
        
        href_lower = href.lower()
        has_indicator = any(indicator in href_lower for indicator in opportunity_indicators)
        
        # Must be from VC4A domain and have opportunity indicators
        is_vc4a = 'vc4a.com' in href_lower or href.startswith('/')
        
        return is_vc4a and has_indicator

    async def scrape_vc4a_opportunity(self, url: str) -> Dict[str, Any]:
        """Scrape individual VC4A opportunity page"""
        try:
            page = await self.browser.new_page()
            await page.goto(url, wait_until='networkidle')
            await asyncio.sleep(3)
            
            # Extract data using VC4A-specific selectors
            data = {
                'url': url,
                'title': await self._extract_with_fallback(page, [
                    'h1',
                    '.program-title',
                    '.opportunity-title',
                    '.post-title',
                    '.entry-title',
                    'title'
                ]),
                'content': await self._extract_content(page),
                'organizer': await self._extract_with_fallback(page, [
                    '.organizer',
                    '.partner',
                    '.company',
                    '.author',
                    '.organization'
                ]),
                'deadline': await self._extract_deadline(page),
                'published_date': await self._extract_date(page),
                'image_url': await self._extract_image(page, url),
                'organizer_logo': await self._extract_organizer_logo(page, url),
                'organizer_website': await self._extract_organizer_website(page),
                'apply_links': await self._extract_apply_links(page)
            }
            
            await page.close()
            return data
            
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return {}

    async def _extract_with_fallback(self, page, selectors: List[str]) -> str:
        """Extract text with multiple selector fallbacks"""
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue
        return ""

    async def _extract_content(self, page) -> str:
        """Extract comprehensive content from VC4A page"""
        content_parts = []
        
        content_selectors = [
            '.program-description',
            '.opportunity-description', 
            '.post-content',
            '.entry-content',
            '.content',
            '.description',
            'article',
            '.program-details',
            '.details'
        ]
        
        for selector in content_selectors:
            try:
                elements = await page.query_selector_all(selector)
                for element in elements:
                    text = await element.inner_text()
                    if text and len(text.strip()) > 50:
                        content_parts.append(text.strip())
            except Exception:
                continue
        
        # If no structured content found, get all paragraphs
        if not content_parts:
            try:
                paragraphs = await page.query_selector_all('p')
                for p in paragraphs:
                    text = await p.inner_text()
                    if text and len(text.strip()) > 30:
                        content_parts.append(text.strip())
            except Exception:
                pass
        
        full_content = ' '.join(content_parts)
        return re.sub(r'\s+', ' ', full_content).strip()

    async def _extract_deadline(self, page) -> Optional[str]:
        """Extract application deadline"""
        deadline_selectors = [
            '.deadline',
            '.application-deadline',
            '.closing-date',
            '.due-date',
            '.apply-by',
            '.submission-deadline'
        ]
        
        # First try specific selectors
        for selector in deadline_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    date = self._extract_date_from_text(text)
                    if date:
                        return date
            except Exception:
                continue
        
        # Then search in all text for deadline patterns
        try:
            page_text = await page.evaluate('document.body.innerText')
            deadline_patterns = [
                r'deadline[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
                r'deadline[:\s]*(\w+\s+\d{1,2},?\s+\d{4})',
                r'apply\s+by[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
                r'apply\s+by[:\s]*(\w+\s+\d{1,2},?\s+\d{4})',
                r'closing\s+date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
                r'closing\s+date[:\s]*(\w+\s+\d{1,2},?\s+\d{4})',
                r'due\s+date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
                r'due\s+date[:\s]*(\w+\s+\d{1,2},?\s+\d{4})',
            ]
            
            for pattern in deadline_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    return match.group(1)
        except Exception:
            pass
        
        return None

    async def _extract_date(self, page) -> Optional[str]:
        """Extract published date"""
        date_selectors = [
            '.published-date',
            '.post-date',
            '.entry-date',
            '.created-date',
            'time[datetime]',
            '.date'
        ]
        
        for selector in date_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    # Try datetime attribute first
                    datetime_attr = await element.get_attribute('datetime')
                    if datetime_attr:
                        return datetime_attr
                    
                    # Then try inner text
                    text = await element.inner_text()
                    date = self._extract_date_from_text(text)
                    if date:
                        return date
            except Exception:
                continue
        
        return None

    def _extract_date_from_text(self, text: str) -> Optional[str]:
        """Extract date from text using various patterns"""
        if not text:
            return None
            
        date_patterns = [
            r'\d{4}-\d{2}-\d{2}',  # 2024-12-31
            r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}',  # 12/31/2024 or 31/12/24
            r'\d{1,2}\s+\w+\s+\d{4}',  # 31 December 2024
            r'\w+\s+\d{1,2},?\s+\d{4}',  # December 31, 2024
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group()
        return None

    async def _extract_image(self, page, base_url: str) -> str:
        """Extract main image"""
        image_selectors = [
            '.program-image img',
            '.opportunity-image img',
            '.featured-image img',
            '.post-image img',
            '.wp-post-image',
            'meta[property="og:image"]'
        ]
        
        for selector in image_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    if 'meta' in selector:
                        img_url = await element.get_attribute('content')
                    else:
                        img_url = await element.get_attribute('src') or await element.get_attribute('data-src')
                    
                    if img_url:
                        return urljoin(base_url, img_url)
            except Exception:
                continue
        
        return ""

    async def _extract_organizer_logo(self, page, base_url: str) -> str:
        """Extract organizer logo"""
        logo_selectors = [
            '.organizer-logo img',
            '.partner-logo img',
            '.company-logo img',
            '.logo img',
            'img[alt*="logo"]',
            'img[class*="logo"]'
        ]
        
        for selector in logo_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    img_url = await element.get_attribute('src') or await element.get_attribute('data-src')
                    if img_url:
                        return urljoin(base_url, img_url)
            except Exception:
                continue
        
        return ""

    async def _extract_organizer_website(self, page) -> str:
        """Extract organizer website"""
        try:
            links = await page.query_selector_all('a[href*="http"]')
            for link in links:
                href = await link.get_attribute('href')
                if href and not any(social in href for social in ['facebook', 'twitter', 'linkedin', 'instagram']):
                    if any(domain in href for domain in ['.org', '.com', '.net', '.edu']):
                        return href
        except Exception:
            pass
        
        return ""

    async def _extract_apply_links(self, page) -> List[str]:
        """Extract application/registration links"""
        links = []
        apply_selectors = [
            'a[href*="apply"]',
            'a[href*="register"]',
            'a[href*="submit"]',
            'a:has-text("Apply")',
            'a:has-text("Register")',
            'a:has-text("Submit")',
            '.apply-button',
            '.register-button'
        ]
        
        for selector in apply_selectors:
            try:
                elements = await page.query_selector_all(selector)
                for element in elements:
                    href = await element.get_attribute('href')
                    if href and href not in links:
                        links.append(href)
            except Exception:
                continue
        
        return links

    async def enrich_with_llm(self, scraped_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich scraped data with Gemini-generated content"""
        if not self.gemini_model:
            logger.warning("Gemini model not configured, skipping LLM enrichment")
            return self._create_basic_enrichment(scraped_data)
        
        try:
            content = scraped_data.get('content', '')
            title = scraped_data.get('title', '')
            
            # If we have very little content, this might not be a real opportunity
            if len(content) < 100 and not title:
                logger.warning("Insufficient content for LLM enrichment")
                return None
            
            prompt = f"""
            Analysez cette opportunité et fournissez des informations structurées en JSON :
            
            Titre: {title}
            Contenu: {content[:3000]}...
            
            Veuillez fournir UNIQUEMENT un JSON valide avec ces clés :
            - subtitle: Une description détaillée en 2-3 lignes qui explique et approfondit le titre principal
            - meta_title: Titre optimisé SEO (max 60 caractères)  
            - meta_description: Description meta (max 160 caractères)
            - slug: URL slug (minuscules, tirets)
            - regions: Liste des régions africaines concernées
            - sectors: Liste des secteurs concernés
            - stages: Liste des étapes de développement concernées
            - categories: Liste des catégories (Accelerator, Competition, Funding Opportunity, etc.)
            - draft_summary: Résumé naturel en 2-3 lignes
            - main_image_alt: Texte alternatif pour l'image principale
            - organizer_logo_alt: Texte alternatif pour le logo de l'organisateur
            
            Répondez UNIQUEMENT avec le JSON, sans texte supplémentaire.
            """
            
            response = await asyncio.to_thread(
                self.gemini_model.generate_content,
                prompt
            )
            
            content_text = response.text.strip()
            if content_text.startswith('```json'):
                content_text = content_text[7:]
            if content_text.endswith('```'):
                content_text = content_text[:-3]
            content_text = content_text.strip()
            
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
            'subtitle': f"Cette opportunité offre aux entrepreneurs et professionnels africains une chance unique de développer leurs compétences.",
            'meta_title': title[:60] if title else 'African Opportunity',
            'meta_description': f"Découvrez cette opportunité: {title}"[:160],
            'slug': re.sub(r'[^\w\s-]', '', title.lower()).replace(' ', '-')[:50],
            'regions': ['Africa'],
            'sectors': ['Sector Agnostic'],
            'stages': ['Stage Agnostic'],
            'categories': ['Other'],
            'draft_summary': f"Cette opportunité représente une excellente occasion pour les entrepreneurs africains.",
            'main_image_alt': f"Image pour {title}",
            'organizer_logo_alt': f"Logo de l'organisateur"
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

    async def process_vc4a_opportunities(self) -> List[OpportunityData]:
        """Process VC4A opportunities with improved discovery"""
        opportunities = []
        
        # Discover opportunity URLs
        logger.info("Discovering VC4A opportunities...")
        opportunity_urls = await self.discover_vc4a_opportunities()
        
        if not opportunity_urls:
            logger.warning("No VC4A opportunities discovered")
            return opportunities
        
        logger.info(f"Found {len(opportunity_urls)} potential opportunities")
        
        # Remove duplicates and filter
        unique_urls = list(set(opportunity_urls))
        filtered_urls = [url for url in unique_urls if self._is_valid_vc4a_opportunity(url)]
        
        logger.info(f"Processing {len(filtered_urls)} filtered opportunities")
        
        for i, url in enumerate(filtered_urls[:20], 1):  # Limit to 20 for testing
            logger.info(f"Processing {i}/{min(len(filtered_urls), 20)}: {url}")
            
            try:
                # Scrape content
                scraped_data = await self.scrape_vc4a_opportunity(url)
                
                if not scraped_data.get('title') or len(scraped_data.get('content', '')) < 100:
                    logger.warning(f"Insufficient content for {url}, skipping")
                    continue
                
                # Enrich with LLM
                enriched_data = await self.enrich_with_llm(scraped_data)
                
                if not enriched_data:
                    logger.warning(f"Failed to enrich {url}, skipping")
                    continue
                
                # Create opportunity object
                opportunity = self.create_opportunity_object(scraped_data, enriched_data)
                opportunities.append(opportunity)
                
                logger.info(f"✓ Successfully processed: {opportunity.title}")
                
                # Add delay to be respectful
                await asyncio.sleep(3)
                
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
    """Main execution function for VC4A scraping"""
    API_KEY = os.getenv("GEMINI_API_KEY")
    
    if not API_KEY:
        logger.error("GEMINI_API_KEY non trouvée dans config.env")
        return
    
    logger.info("Démarrage du scraping VC4A amélioré...")
    
    async with VC4AImprovedScraper(API_KEY) as scraper:
        opportunities = await scraper.process_vc4a_opportunities()
        
        if opportunities:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"vc4a_opportunities_{timestamp}.json"
            scraper.save_to_json(opportunities, filename)
            
            logger.info(f"✅ Scraping terminé! Trouvé {len(opportunities)} opportunités")
            logger.info(f"📁 Fichier sauvegardé: {filename}")
            
            # Print sample data
            if opportunities:
                sample = opportunities[0]
                logger.info(f"📋 Exemple: {sample.title}")
                logger.info(f"🏢 Organisateur: {sample.organizer_name}")
                logger.info(f"📅 Deadline: {sample.application_deadline}")
        else:
            logger.warning("❌ Aucune opportunité trouvée")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Arrêté par l'utilisateur")
    except Exception as e:
        logger.error(f"Erreur fatale: {e}")