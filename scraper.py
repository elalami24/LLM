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
        
        # Site-specific configurations - AMÉLIORÉES
        self.site_configs = {
            'disruptafrica.com': {
                'selectors': {
                    'title': 'h1.entry-title, h1.post-title, .title, h1, .headline',
                    'content': '.entry-content, .post-content, .content, article, .post-body, .article-content',
                    'date': '.entry-date, .post-date, .date, time, .published, .created, .post-meta time',
                    'organizer': '.organizer, .company, .organization, .author, .sponsor, .partner',
                    'deadline': '.deadline, .apply-by, .application-deadline, .closing-date, .due-date',
                    'image': '.featured-image img, .post-image img, .wp-post-image, .article-image img',
                    'links': 'a[href*="apply"], a[href*="register"], a[href*="submit"], a[href*="participate"]'
                },
                'content_selectors': [
                    '.entry-content', '.post-content', '.content', 'article',
                    '.post-body', '.article-body', '.description', '.summary',
                    '.program-details', '.opportunity-details', '.event-details',
                    '.main-content', '.single-content', '.page-content'
                ]
            },
            'vc4a.com': {
                'selectors': {
                    'title': 'h1, .program-title, .title, .opportunity-title',
                    'content': '.program-description, .content, .description, .opportunity-content',
                    'date': '.date, .published, .created, .post-date, time',
                    'organizer': '.organizer, .partner, .company, .sponsor',
                    'deadline': '.deadline, .apply-deadline, .closing-date, .submission-deadline',
                    'image': '.program-image img, .featured-image img, .opportunity-image img',
                    'links': 'a[href*="apply"], a[href*="join"], a[href*="register"]'
                },
                'content_selectors': [
                    '.program-description', '.opportunity-content', '.content',
                    '.description', '.details', '.about', '.info'
                ]
            },
            'opportunitiesforafricans.com': {
                'selectors': {
                    'title': 'h1.entry-title, .post-title, h1, .opportunity-title',
                    'content': '.entry-content, .post-content, .content, .opportunity-content',
                    'date': '.entry-date, .post-date, time, .published, .created',
                    'organizer': '.organizer, .sponsor, .author, .partner',
                    'deadline': '.deadline, .closing-date, .apply-by, .submission-deadline',
                    'image': '.featured-image img, .wp-post-image, .opportunity-image img',
                    'links': 'a[href*="apply"], a[href*="link"], a[href*="register"]'
                },
                'content_selectors': [
                    '.entry-content', '.post-content', '.content',
                    '.opportunity-content', '.description', '.details'
                ]
            },
            'msmeafricaonline.com': {
                'selectors': {
                    'title': 'h1.entry-title, h1, .title, .post-title',
                    'content': '.entry-content, .content, article, .post-content',
                    'date': '.entry-date, .date, time, .published, .post-date',
                    'organizer': '.organizer, .author, .sponsor, .partner',
                    'deadline': '.deadline, .closing-date, .apply-by',
                    'image': '.wp-post-image, .featured-image img, .post-image img',
                    'links': 'a[href*="apply"], a[href*="register"]'
                },
                'content_selectors': [
                    '.entry-content', '.content', 'article', '.post-content',
                    '.description', '.details', '.info'
                ]
            },
            'opportunitydesk.org': {
                'selectors': {
                    'title': 'h1.entry-title, .post-title, h1, .opportunity-title',
                    'content': '.entry-content, .post-content, .content, .opportunity-content',
                    'date': '.entry-date, .post-date, time, .published, .created',
                    'organizer': '.organizer, .sponsor, .author, .partner',
                    'deadline': '.deadline, .application-deadline, .closing-date',
                    'image': '.featured-image img, .wp-post-image, .opportunity-image img',
                    'links': 'a[href*="apply"], a[href*="register"], a[href*="submit"]'
                },
                'content_selectors': [
                    '.entry-content', '.post-content', '.content',
                    '.opportunity-content', '.description', '.details'
                ]
            }
        }

    async def __aenter__(self):
        # Configure session with headers and timeout
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        # Configure timeout and connection settings
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        connector = aiohttp.TCPConnector(limit=10, limit_per_host=2)
        
        self.session = aiohttp.ClientSession(
            headers=headers, 
            timeout=timeout,
            connector=connector
        )
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

    async def crawl_category_urls(self, base_url: str, max_pages: int = 5, max_retries: int = 3) -> List[str]:
        """Crawl category pages to extract opportunity URLs with retry logic"""
        opportunity_urls = []
        domain = urlparse(base_url).netloc
        
        for page in range(1, max_pages + 1):
            retries = 0
            success = False
            
            while retries < max_retries and not success:
                try:
                    # Construct paginated URL
                    if page == 1:
                        url = base_url
                    else:
                        url = f"{base_url}page/{page}/" if base_url.endswith('/') else f"{base_url}/page/{page}/"
                    
                    logger.info(f"Crawling page {page} (attempt {retries + 1}): {url}")
                    
                    # Add delay between requests to be respectful
                    if retries > 0:
                        await asyncio.sleep(5 * retries)  # Increasing delay for retries
                    
                    async with self.session.get(url) as response:
                        if response.status == 200:
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
                            success = True
                            
                            # If no opportunities found, we might have reached the end
                            if not page_urls and page > 1:
                                logger.info(f"No more opportunities found, stopping at page {page}")
                                return opportunity_urls
                                
                        elif response.status == 524:
                            logger.warning(f"Server timeout (524) for {url}, attempt {retries + 1}/{max_retries}")
                            retries += 1
                        elif response.status == 503:
                            logger.warning(f"Service unavailable (503) for {url}, attempt {retries + 1}/{max_retries}")
                            retries += 1
                        elif response.status == 429:
                            logger.warning(f"Rate limited (429) for {url}, waiting longer...")
                            await asyncio.sleep(30)  # Wait 30 seconds for rate limiting
                            retries += 1
                        else:
                            logger.warning(f"HTTP {response.status} for {url}")
                            retries += 1
                            
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout error for {url}, attempt {retries + 1}/{max_retries}")
                    retries += 1
                except aiohttp.ClientError as e:
                    logger.warning(f"Client error for {url}: {e}, attempt {retries + 1}/{max_retries}")
                    retries += 1
                except Exception as e:
                    logger.error(f"Unexpected error crawling {url}: {e}")
                    break
            
            if not success:
                logger.error(f"Failed to crawl page {page} after {max_retries} attempts, skipping...")
                # Try with Playwright as fallback for difficult sites
                try:
                    logger.info(f"Trying Playwright fallback for page {page}")
                    page_urls = await self._crawl_with_playwright(url, domain, base_url)
                    opportunity_urls.extend(page_urls)
                    logger.info(f"Playwright found {len(page_urls)} opportunities on page {page}")
                except Exception as e:
                    logger.error(f"Playwright fallback also failed: {e}")
                
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
        
        for pattern in opportunity_patterns:
            if pattern in href.lower():
                return True
                
        return False

    async def _crawl_with_playwright(self, url: str, domain: str, base_url: str) -> List[str]:
        """Fallback crawling method using Playwright for problematic sites"""
        try:
            page = await self.browser.new_page()
            
            # Set longer timeout and user agent
            page.set_default_timeout(30000)  # 30 seconds
            await page.set_extra_http_headers({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            # Navigate with network idle wait
            await page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait a bit more for dynamic content
            await page.wait_for_timeout(3000)
            
            # Extract links
            links = await page.evaluate('''
                () => {
                    const anchors = Array.from(document.querySelectorAll('a[href]'));
                    return anchors.map(a => a.href).filter(href => href && href.length > 0);
                }
            ''')
            
            await page.close()
            
            # Filter opportunity URLs
            opportunity_urls = []
            for href in links:
                if self._is_opportunity_url(href, domain):
                    full_url = urljoin(base_url, href)
                    if full_url not in opportunity_urls:
                        opportunity_urls.append(full_url)
            
            return opportunity_urls
            
        except Exception as e:
            logger.error(f"Playwright crawling failed for {url}: {e}")
            return []

    async def scrape_opportunity_content(self, url: str, use_playwright: bool = False, max_retries: int = 2) -> Dict[str, Any]:
        """Scrape content from an opportunity page with retry logic"""
        domain = urlparse(url).netloc
        config = self.site_configs.get(domain, self.site_configs['disruptafrica.com'])
        
        for attempt in range(max_retries):
            try:
                if use_playwright:
                    # Use Playwright for dynamic content
                    page = await self.browser.new_page()
                    page.set_default_timeout(30000)
                    await page.goto(url, wait_until='networkidle', timeout=30000)
                    await page.wait_for_timeout(2000)  # Wait for dynamic content
                    html = await page.content()
                    await page.close()
                else:
                    # Add delay between requests
                    if attempt > 0:
                        await asyncio.sleep(3 * attempt)
                    
                    # Use aiohttp for static content
                    async with self.session.get(url) as response:
                        if response.status == 200:
                            html = await response.text()
                        elif response.status in [524, 503, 429]:
                            logger.warning(f"Server error {response.status} for {url}, attempt {attempt + 1}")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(10)  # Wait before retry
                                continue
                            else:
                                logger.warning(f"Switching to Playwright for {url}")
                                return await self.scrape_opportunity_content(url, use_playwright=True, max_retries=1)
                        else:
                            logger.warning(f"HTTP {response.status} for {url}")
                            return {}
                
                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract data using selectors
                data = {
                    'url': url,
                    'title': self._extract_text(soup, config['selectors']['title']),
                    'content': self._extract_comprehensive_content(soup, config),
                    'published_date': self._extract_date(soup, config['selectors']['date']),
                    'organizer': self._extract_text(soup, config['selectors']['organizer']),
                    'deadline': self._extract_deadline(soup, config['selectors']['deadline']),
                    'image_url': self._extract_image_url(soup, config['selectors']['image'], url),
                    'apply_links': self._extract_links(soup, config['selectors']['links']),
                    'organizer_website': self._extract_organizer_website(soup),
                    'organizer_logo': self._extract_organizer_logo(soup, url)
                }
                
                return data
                
            except asyncio.TimeoutError:
                logger.warning(f"Timeout for {url}, attempt {attempt + 1}")
                if attempt == max_retries - 1:
                    logger.error(f"Final timeout for {url}")
                    return {}
            except Exception as e:
                logger.error(f"Error scraping {url}, attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    return {}
        
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

    def _extract_comprehensive_content(self, soup: BeautifulSoup, config: Dict) -> str:
        """AMÉLIORATION: Extract comprehensive content from multiple sources"""
        content_parts = []
        
        # 1. Primary content selectors from config
        primary_content = self._extract_text(soup, config['selectors']['content'])
        if primary_content:
            content_parts.append(primary_content)
        
        # 2. Site-specific content selectors
        if 'content_selectors' in config:
            for selector in config['content_selectors']:
                elements = soup.select(selector)
                for element in elements:
                    text = element.get_text(strip=True)
                    if text and len(text) > 50 and text not in content_parts:
                        content_parts.append(text)
        
        # 3. Generic content selectors (fallback)
        generic_selectors = [
            'main .content, main article, main .post',
            '.post-body, .article-body, .entry-body',
            '.description, .summary, .excerpt',
            '.details, .info, .about',
            '.program-details, .opportunity-details, .event-details',
            '.main-content, .single-content, .page-content',
            '[class*="content"], [class*="description"], [class*="details"]'
        ]
        
        for selector in generic_selectors:
            elements = soup.select(selector)
            for element in elements:
                text = element.get_text(strip=True)
                if text and len(text) > 100 and text not in content_parts:
                    content_parts.append(text)
        
        # 4. Extract all meaningful paragraphs as fallback
        if not content_parts:
            paragraphs = soup.find_all(['p', 'div'], string=True)
            for p in paragraphs:
                text = p.get_text(strip=True)
                if text and len(text) > 50:
                    # Filter out navigation, footer, header content
                    parent_classes = ' '.join(p.get('class', []))
                    if not any(exclude in parent_classes.lower() for exclude in 
                              ['nav', 'footer', 'header', 'sidebar', 'menu', 'widget']):
                        content_parts.append(text)
        
        # 5. Extract structured data (lists, tables)
        lists = soup.find_all(['ul', 'ol'])
        for lst in lists:
            list_text = lst.get_text(strip=True)
            if list_text and len(list_text) > 50:
                content_parts.append(f"Liste: {list_text}")
        
        tables = soup.find_all('table')
        for table in tables:
            table_text = table.get_text(strip=True)
            if table_text and len(table_text) > 50:
                content_parts.append(f"Tableau: {table_text}")
        
        # Combine all content
        full_content = '\n\n'.join(content_parts)
        
        # Clean up the content
        full_content = re.sub(r'\s+', ' ', full_content)  # Multiple spaces to single
        full_content = re.sub(r'\n+', '\n', full_content)  # Multiple newlines to single
        full_content = re.sub(r'[\r\t]+', ' ', full_content)  # Remove tabs and carriage returns
        
        # Remove duplicate sentences
        sentences = full_content.split('.')
        unique_sentences = []
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and sentence not in unique_sentences and len(sentence) > 20:
                unique_sentences.append(sentence)
        
        full_content = '. '.join(unique_sentences)
        
        logger.info(f"Extracted content length: {len(full_content)} characters")
        return full_content.strip()

    def _extract_date(self, soup: BeautifulSoup, selector: str) -> Optional[str]:
        """Extract and parse date"""
        # Try datetime attributes first
        time_elements = soup.find_all(['time', 'span', 'div'], attrs={'datetime': True})
        for element in time_elements:
            datetime_value = element.get('datetime')
            if datetime_value:
                return datetime_value
        
        # Try text extraction with selectors
        text = self._extract_text(soup, selector)
        if text:
            return self._extract_date_from_text(text)
        
        # Search in meta tags
        meta_date = soup.find('meta', attrs={'property': 'article:published_time'})
        if meta_date:
            return meta_date.get('content')
        
        meta_date = soup.find('meta', attrs={'name': 'date'})
        if meta_date:
            return meta_date.get('content')
        
        return None

    def _extract_deadline(self, soup: BeautifulSoup, selector: str) -> Optional[str]:
        """AMÉLIORATION: Extract deadline with improved patterns"""
        # First try specific deadline selectors
        deadline_text = self._extract_text(soup, selector)
        if deadline_text:
            extracted_date = self._extract_date_from_text(deadline_text)
            if extracted_date:
                return extracted_date
        
        # Search in all text for deadline patterns (improved)
        all_text = soup.get_text()
        deadline_patterns = [
            r'deadline[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'deadline[:\s]*(\d{4}[/-]\d{1,2}[/-]\d{1,2})',
            r'deadline[:\s]*(\d{1,2}\s+\w+\s+\d{4})',
            r'deadline[:\s]*(\w+\s+\d{1,2},?\s+\d{4})',
            r'apply\s+by[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'apply\s+by[:\s]*(\w+\s+\d{1,2},?\s+\d{4})',
            r'closing\s+date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'closing\s+date[:\s]*(\w+\s+\d{1,2},?\s+\d{4})',
            r'due\s+date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'due\s+date[:\s]*(\w+\s+\d{1,2},?\s+\d{4})',
            r'submission\s+deadline[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'submission\s+deadline[:\s]*(\w+\s+\d{1,2},?\s+\d{4})',
            r'expires?\s+on[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'expires?\s+on[:\s]*(\w+\s+\d{1,2},?\s+\d{4})',
            r'until[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'until[:\s]*(\w+\s+\d{1,2},?\s+\d{4})',
            r'before[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'before[:\s]*(\w+\s+\d{1,2},?\s+\d{4})'
        ]
        
        for pattern in deadline_patterns:
            match = re.search(pattern, all_text, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None

    def _extract_date_from_text(self, text: str) -> Optional[str]:
        """Extract date from text using various patterns"""
        if not text:
            return None
            
        date_patterns = [
            r'\d{4}-\d{1,2}-\d{1,2}',  # ISO format
            r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}',
            r'\d{4}[/-]\d{1,2}[/-]\d{1,2}',
            r'\d{1,2}\s+\w+\s+\d{4}',
            r'\w+\s+\d{1,2},?\s+\d{4}',
            r'\d{1,2}\.\d{1,2}\.\d{2,4}'  # Dot format
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

    async def extract_dates_with_llm(self, title: str, content: str) -> Dict[str, Optional[str]]:
        """AMÉLIORATION: Use LLM to extract both published_date and application_deadline when not found in HTML"""
        if not self.gemini_model:
            return {'published_date': None, 'application_deadline': None}
            
        try:
            prompt = f"""
            Analysez le titre et le contenu suivant pour extraire les dates importantes.
            
            Titre: {title}
            Contenu: {content[:4000]}...
            
            Recherchez et extrayez:
            1. Date de publication (published date, post date, created date, published on, date de création, date de publication)
            2. Date limite de candidature (deadline, application deadline, closing date, due date, apply by, submission deadline, date limite, date de clôture, échéance)
            
            Analysez tout le contenu en cherchant des patterns comme:
            - "Deadline: [date]"
            - "Apply by: [date]"
            - "Closing date: [date]"
            - "Published on: [date]"
            - "Date limite: [date]"
            - "Échéance: [date]"
            - "Applications must be submitted by [date]"
            - "The deadline for applications is [date]"
            - "Published: [date]"
            - "Created: [date]"
            
            Répondez UNIQUEMENT avec un JSON contenant:
            {{
                "published_date": "date trouvée ou null",
                "application_deadline": "date trouvée ou null"
            }}
            
            Formats de date acceptés: "YYYY-MM-DD", "DD/MM/YYYY", "Month DD, YYYY", "DD Month YYYY"
            Si aucune date n'est trouvée pour un champ, utilisez null.
            
            Ne fournissez aucune explication, seulement le JSON.
            """
            
            response = await asyncio.to_thread(
                self.gemini_model.generate_content,
                prompt
            )
            
            result = response.text.strip()
            
            # Clean the response to extract JSON
            if result.startswith('```json'):
                result = result[7:]
            if result.endswith('```'):
                result = result[:-3]
            result = result.strip()
            
            try:
                dates = json.loads(result)
                return {
                    'published_date': dates.get('published_date'),
                    'application_deadline': dates.get('application_deadline')
                }
            except json.JSONDecodeError:
                logger.error(f"Failed to parse LLM date response: {result}")
                return {'published_date': None, 'application_deadline': None}
            
        except Exception as e:
            logger.error(f"Error in LLM date extraction: {e}")
            return {'published_date': None, 'application_deadline': None}

    async def enrich_with_llm(self, scraped_data: Dict[str, Any]) -> Dict[str, Any]:
        """AMÉLIORATION: Enrich scraped data with Gemini-generated content including date extraction with two-step approach"""
        if not self.gemini_model:
            logger.warning("Gemini model not configured, skipping LLM enrichment")
            return self._create_basic_enrichment(scraped_data)
    
        try:
            content = scraped_data.get('content', '')
            title = scraped_data.get('title', '')
            organizer_website = scraped_data.get('organizer_website', '')
        
            # PREMIÈRE ÉTAPE: Enrichissement principal avec extraction de dates
            main_prompt = f"""
            Analysez cette opportunité et fournissez des informations structurées en JSON :
            
            Titre: {title}
            Contenu: {content[:4000]}...
            
            IMPORTANT: Analysez le contenu pour extraire les dates si elles n'ont pas été trouvées:
            - Date de publication (published date, post date, created date, published on)
            - Date limite de candidature (deadline, application deadline, closing date, due date, apply by)
            
            Veuillez fournir UNIQUEMENT un JSON valide avec ces clés :
            - subtitle: Une description détaillée en 2-3 lignes qui explique et approfondit le titre principal
            - meta_title: Titre optimisé SEO (max 100 caractères)  
            - meta_description: Description meta (max 160 caractères)
            - slug: URL slug (minuscules, tirets)
            - regions: Liste des régions (choisir parmi: ["Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi", "Cabo Verde", "Cameroon", "Central African Republic", "Chad", "Comoros", "Congo", "Côte d'Ivoire", "DR Congo", "Djibouti", "Egypt", "Equatorial Guinea", "Eritrea", "Eswatini", "Ethiopia", "Gabon", "Guinea", "Guinea-Bissau", "Kenya", "Lesotho", "Liberia", "Libya", "Madagascar", "Malawi", "Mali", "Mauritania", "Mauritius", "Morocco", "Mozambique", "Namibia", "Niger", "Nigeria", "Rwanda", "Sao Tome & Principe", "Senegal", "Seychelles", "Sierra Leone", "Somalia", "South Africa", "South Sudan", "Sudan", "Tanzania", "Togo", "Tunisia", "Uganda", "Zambia", "Zimbabwe"])
            - sectors: Liste des secteurs (choisir parmi: ["Regulatory Tech", "Spatial Computing", "AgriTech", "Agribusiness", "Artificial Intelligence", "Banking", "Blockchain", "Business Process Outsourcing (BPO)", "CleanTech", "Creative", "Cryptocurrencies", "Cybersecurity & Digital ID", "Data Aggregation", "Debt Management", "DeepTech", "Design & Applied Arts", "Digital & Interactive", "E-commerce and Retail", "Economic Development", "EdTech", "Energy", "Environmental Social Governance (ESG)", "FinTech", "Gaming", "HealthTech", "InsurTech", "Logistics", "ManuTech", "Manufacturing", "Media & Communication", "Mobility and Transportation", "Performing & Visual Arts", "Sector Agnostic", "Sport Management", "Sustainability", "Technology", "Tourism Innovation", "Transformative Digital Technologies", "Wearables"])
            - stages: Liste des étapes (choisir parmi: ["Not Applicable", "Pre-Series A", "Pre-seed", "Seed", "Series A", "Series B", "Series C", "Series D", "Series E", "Series F", "Stage Agnostic"])
            - categories: Liste des catégories (choisir parmi: ["Accelerator", "Bootcamp", "Competition", "Conference", "Event", "Funding Opportunity", "Hackathon", "Incubator", "Other", "Summit"])
            - draft_summary: Résumé naturel en 2-3 lignes
            - main_image_alt: Texte alternatif pour l'image principale
            - organizer_logo_alt: Texte alternatif pour le logo de l'organisateur
            - extracted_published_date: Date de publication extraite du contenu (format YYYY-MM-DD ou null)
            - extracted_deadline: Date limite d'application extraite du contenu (format YYYY-MM-DD ou null)

            Répondez UNIQUEMENT avec le JSON, sans texte supplémentaire.
            """
            
            # Première requête Gemini
            response = await asyncio.to_thread(
                self.gemini_model.generate_content,
                main_prompt
            )
            
            content_text = response.text.strip()
            
            # Clean the response to extract JSON
            if content_text.startswith('```json'):
                content_text = content_text[7:]
            if content_text.endswith('```'):
                content_text = content_text[:-3]
            content_text = content_text.strip()
            
            # Parse JSON response
            try:
                enriched_data = json.loads(content_text)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse first Gemini response as JSON: {content_text}")
                enriched_data = self._create_basic_enrichment(scraped_data)
            
            # Mettre à jour les données avec les dates extraites du premier prompt
            original_published_date = scraped_data.get('published_date')
            original_deadline = scraped_data.get('deadline')
            
            if enriched_data.get('extracted_published_date') and not original_published_date:
                scraped_data['published_date'] = enriched_data['extracted_published_date']
                logger.info(f"LLM extracted published date from main enrichment: {enriched_data['extracted_published_date']}")
            
            if enriched_data.get('extracted_deadline') and not original_deadline:
                scraped_data['deadline'] = enriched_data['extracted_deadline']
                logger.info(f"LLM extracted deadline from main enrichment: {enriched_data['extracted_deadline']}")
            
            # DEUXIÈME ÉTAPE: Prompt spécialisé pour les dates manquantes
            missing_dates = []
            if not scraped_data.get('published_date') and not enriched_data.get('extracted_published_date'):
                missing_dates.append('published_date')
            if not scraped_data.get('deadline') and not enriched_data.get('extracted_deadline'):
                missing_dates.append('deadline')
            
            if missing_dates:
                logger.info(f"Dates manquantes détectées: {missing_dates}. Lancement du prompt spécialisé...")
                
                specialized_prompt = f"""
                faire une recherche spécifiquement de cette opportunité pour extraire les dates manquantes :
                
                Titre: {title}
                Site web de l'organisateur: {organizer_website}
                Contenu complet: {content}
                
                MISSION SPÉCIALISÉE :
                {"- Trouvez la date limite de candidature (application deadline) pour cette opportunité" if 'deadline' in missing_dates else ""}
                {"- Trouvez la date de publication de cette opportunité" if 'published_date' in missing_dates else ""}
                
                
                Répondez UNIQUEMENT avec un JSON contenant :
                {{
                    {"\"application_deadline\": \"date trouvée ou null\"" if 'deadline' in missing_dates else ""}
                    {"," if len(missing_dates) == 2 else ""}
                    {"\"published_date\": \"date trouvée ou null\"" if 'published_date' in missing_dates else ""}
                }}
                
                Format de date: YYYY-MM-DD uniquement. Si aucune date n'est trouvée, utilisez null.
                Soyez très précis dans votre analyse du contenu.
                """
                
                try:
                    # Deuxième requête Gemini pour les dates manquantes
                    specialized_response = await asyncio.to_thread(
                        self.gemini_model.generate_content,
                        specialized_prompt
                    )
                    
                    specialized_content = specialized_response.text.strip()
                    
                    # Clean the response
                    if specialized_content.startswith('```json'):
                        specialized_content = specialized_content[7:]
                    if specialized_content.endswith('```'):
                        specialized_content = specialized_content[:-3]
                    specialized_content = specialized_content.strip()
                    
                    # Parse specialized response
                    try:
                        specialized_dates = json.loads(specialized_content)
                        
                        # Mettre à jour avec les dates trouvées par le prompt spécialisé
                        if specialized_dates.get('application_deadline') and not scraped_data.get('deadline'):
                            scraped_data['deadline'] = specialized_dates['application_deadline']
                            enriched_data['extracted_deadline'] = specialized_dates['application_deadline']
                            logger.info(f" Prompt spécialisé a trouvé la deadline: {specialized_dates['application_deadline']}")
                        
                        if specialized_dates.get('published_date') and not scraped_data.get('published_date'):
                            scraped_data['published_date'] = specialized_dates['published_date']
                            enriched_data['extracted_published_date'] = specialized_dates['published_date']
                            logger.info(f" Prompt spécialisé a trouvé la date de publication: {specialized_dates['published_date']}")
                            
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse specialized date response: {specialized_content}")
                        
                except Exception as e:
                    logger.error(f"Error in specialized date extraction: {e}")
            
            return enriched_data
            
        except Exception as e:
            logger.error(f"Error in Gemini enrichment: {e}")
            return self._create_basic_enrichment(scraped_data)
    def _create_basic_enrichment(self, scraped_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create basic enrichment when LLM is not available"""
        title = scraped_data.get('title', '')
        
        return {
            'subtitle': f"Cette opportunité offre aux entrepreneurs et professionnels africains une chance unique de développer leurs compétences et d'accéder à des ressources précieuses pour leur croissance.",
            'meta_title': title[:60] if title else 'African Opportunity',
            'meta_description': f"Découvrez cette opportunité: {title}"[:160],
            'slug': re.sub(r'[^\w\s-]', '', title.lower()).replace(' ', '-')[:50],
            'regions': ['Nigeria'],
            'sectors': ['Sector Agnostic'],
            'stages': ['Stage Agnostic'],
            'categories': ['Other'],
            'draft_summary': f"Cette opportunité représente une excellente occasion pour les entrepreneurs et professionnels africains de développer leurs projets.",
            'main_image_alt': f"Image pour {title}",
            'organizer_logo_alt': f"Logo de {scraped_data.get('organizer', 'organisateur')}"
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
                if opportunity.application_deadline:
                    logger.info(f"Deadline found: {opportunity.application_deadline}")
                if opportunity.published_date:
                    logger.info(f"Published date: {opportunity.published_date}")
                logger.info(f"Content length: {len(scraped_data.get('content', ''))} characters")
                
                # Add delay to be respectful and avoid rate limiting
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
    """Main execution function"""
    # Configuration avec votre clé API Gemini depuis le fichier config.env
    API_KEY = os.getenv("GEMINI_API_KEY")
    
    if not API_KEY:
        logger.error(" GEMINI_API_KEY non trouvée dans config.env")
        logger.info(" Créez un fichier config.env avec: GEMINI_API_KEY=votre_clé_ici")
        return
    
    logger.info(f" Clé API chargée depuis config.env")
    
    # URLs cibles
    target_urls = [
        "https://disruptafrica.com/category/events/",
        "https://disruptafrica.com/category/hubs/",
        "https://www.opportunitiesforafricans.com/",
        "https://msmeafricaonline.com/category/opportunities/",
        "https://opportunitydesk.org/category/search-by-region/africa/"
    ]
    
    all_opportunities = []
    
    logger.info(" Démarrage du scraping des opportunités africaines...")
    
    async with OpportunityScraper(API_KEY) as scraper:
        for base_url in target_urls:
            logger.info(f"🔍 Processing: {base_url}")
            
            try:
                # Crawl category pages
                opportunity_urls = await scraper.crawl_category_urls(base_url, max_pages=3)
                
                if not opportunity_urls:
                    logger.warning(f"No opportunities found for {base_url}")
                    continue
                
                # Process opportunities (limit to 10 per site)
                opportunities = await scraper.process_opportunities(opportunity_urls[:10])
                all_opportunities.extend(opportunities)
                
                logger.info(f" Processed {len(opportunities)} opportunities from {base_url}")
                
            except Exception as e:
                logger.error(f" Error processing {base_url}: {e}")
                continue
    
    # Save results
    if all_opportunities:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"african_opportunities_{timestamp}.json"
        
        # Create scraper instance just for saving
        scraper = OpportunityScraper()
        scraper.save_to_json(all_opportunities, filename)
        
        logger.info(f" Scraping terminé! Trouvé {len(all_opportunities)} opportunités")
        logger.info(f" Fichier sauvegardé: {filename}")
        
        # Print sample data
        if all_opportunities:
            sample = all_opportunities[0]
            logger.info(f"Exemple d'opportunité: {sample.title}")
            logger.info(f" Organisateur: {sample.organizer_name}")
            logger.info(f" Régions: {', '.join(sample.regions)}")
            logger.info(f" Secteurs: {', '.join(sample.sectors)}")
            logger.info(f" Catégories: {', '.join(sample.categories)}")
            logger.info(f" Published date: {sample.published_date}")
            logger.info(f" Deadline: {sample.application_deadline}")
            logger.info(f" Content length: {len(sample.description)} characters")
            logger.info(f" URL: {sample.program_url}")
        
    else:
        logger.warning(" Aucune opportunité trouvée")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info(" Arrêté par l'utilisateur")
    except Exception as e:
        logger.error(f" Erreur fatale: {e}")