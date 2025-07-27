#!/usr/bin/env python3
"""
Scraper VC4A Complet - Découverte exhaustive + Extraction détaillée
Trouve TOUTES les opportunités ET extrait toutes les informations
"""

import asyncio
import json
import csv
from datetime import datetime
from playwright.async_api import async_playwright
import re
from urllib.parse import urljoin, urlparse

class VC4ACompleteScraper:
    def __init__(self):
        self.base_url = "https://vc4a.com/programs/"
        self.found_urls = set()
        self.debug_mode = True
        
    async def setup_browser(self, playwright):
        """Configure le navigateur"""
        browser = await playwright.chromium.launch(
            headless=False,
            slow_mo=1000,
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        
        page = await context.new_page()
        return browser, page
    
    def is_opportunity_url_ultra_permissive(self, url):
        """Validation ULTRA PERMISSIVE - accepte presque tout SAUF les pages génériques"""
        if not url or len(url) < 5:
            return False
        
        url_lower = url.lower()
        
        # Exclusions MINIMALES (vraiment nécessaires)
        hard_excludes = [
            'javascript:', 'mailto:', 'tel:', '#',
            '/login', '/register', '/wp-admin', '/wp-content',
            'facebook.com', 'twitter.com', 'linkedin.com', 'youtube.com',
            '.pdf', '.doc', '.png', '.jpg', '.gif', '.zip',
            '/about', '/contact', '/privacy/', '/terms/',
            '__trashed', 'forms.office.com', 'airtable.com'
        ]
        
        for exclude in hard_excludes:
            if exclude in url_lower:
                return False
        
        # EXCLUSIONS SPÉCIALES pour éviter les pages génériques VC4A
        generic_excludes = [
            '/programs/',  # Page listing principale
            '/programs/page/',  # Pages de pagination
            '/programs/add/',  # Page d'ajout
            '/programs?',  # Pages avec paramètres
            '/ventures/',  # Page ventures principale
            '/ventures/add/',  # Page d'ajout ventures
            '/entrepreneurs/',  # Page entrepreneurs générique
            '/ventureready-hacks/',  # Page générale
        ]
        
        # Vérifier les exclusions spéciales
        for exclude in generic_excludes:
            if exclude in url_lower:
                return False
        
        # Exclure les URLs qui finissent par des patterns génériques
        if (url_lower.endswith('/programs/') or 
            url_lower.endswith('/ventures/') or
            url_lower.endswith('/entrepreneurs/') or
            url_lower == 'https://vc4a.com/programs' or
            url_lower == 'https://vc4a.com/ventures' or
            url_lower == 'https://vc4a.com/entrepreneurs'):
            return False
        
        # Exclure les pages de pagination
        if re.search(r'/page/\d+/?($|\?)', url_lower):
            return False
        
        # Inclusions TRÈS LARGES
        good_patterns = [
            '/program', '/accelerator', '/challenge', '/incubator',
            '/competition', '/opportunity', '/cohort', '/grant',
            '/funding', '/startup', '/entrepreneur', '/innovation',
            '/apply', '/join', '/pitch', '/venture', '/investment'
        ]
        
        # Si ça contient un bon pattern, on l'accepte
        if any(pattern in url_lower for pattern in good_patterns):
            return True
        
        # Accepter aussi les URLs avec structure VC4A spécifique
        if 'vc4a.com' in url_lower or url.startswith('/'):
            clean_url = url_lower.replace('https://vc4a.com/', '').strip('/')
            parts = clean_url.split('/')
            
            # Structure: /something/something-else/ (au moins 2 parties significatives)
            if len(parts) >= 2 and all(len(part) > 2 for part in parts):
                # Éviter les URLs système et génériques
                if not any(sys in parts[0] for sys in [
                    'wp-', 'admin', 'api', 'ajax', 'blog', 'category', 
                    'tag', 'author', 'search', 'page', 'programs', 'ventures'
                ]):
                    return True
        
        return False
    
    def normalize_url(self, href):
        """Normalise une URL"""
        if not href:
            return None
        
        if href.startswith('http'):
            return href
        elif href.startswith('/'):
            return f"https://vc4a.com{href}"
        else:
            return f"https://vc4a.com/{href}"
    
    async def smart_page_load(self, page):
        """Chargement intelligent avec scroll et attente"""
        try:
            await page.wait_for_load_state('domcontentloaded', timeout=15000)
            await page.wait_for_timeout(2000)
            
            # Scroll progressif pour lazy loading
            for i in range(5):
                await page.evaluate(f"window.scrollTo(0, {i * 600})")
                await page.wait_for_timeout(1000)
            
            # Scroll jusqu'en bas
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            
            # Chercher boutons "Load More"
            load_more_selectors = [
                'button:has-text("Load More")', 'button:has-text("Load more")',
                'a:has-text("Load More")', '.load-more', '.load-more-btn'
            ]
            
            for selector in load_more_selectors:
                try:
                    button = await page.query_selector(selector)
                    if button:
                        print(f"   🔄 Clic sur 'Load More'")
                        await button.click()
                        await page.wait_for_timeout(3000)
                        break
                except:
                    continue
            
            # Revenir en haut
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(1000)
            
        except Exception as e:
            if self.debug_mode:
                print(f"   ⚠️ Erreur smart load: {e}")
    
    async def discover_all_opportunity_urls(self, page):
        """Découverte EXHAUSTIVE de toutes les URLs d'opportunités"""
        all_urls = set()
        
        try:
            # Debug: analyser la page
            if self.debug_mode:
                stats = await page.evaluate("""
                    () => {
                        return {
                            total_links: document.querySelectorAll('a[href]').length,
                            program_links: document.querySelectorAll('a[href*="program"]').length,
                            cards: document.querySelectorAll('.card, [class*="card"], .item').length
                        };
                    }
                """)
                print(f"   📊 Page: {stats['total_links']} liens, {stats['program_links']} avec 'program', {stats['cards']} cartes")
            
            # STRATÉGIE 1: Sélecteurs spécifiques très larges
            specific_selectors = [
                'a[href*="/program"]', 'a[href*="/accelerator"]', 'a[href*="/challenge"]',
                'a[href*="/incubator"]', 'a[href*="/competition"]', 'a[href*="/opportunity"]',
                'a[href*="/cohort"]', 'a[href*="/grant"]', 'a[href*="/funding"]',
                'a[href*="/startup"]', 'a[href*="/entrepreneur"]', 'a[href*="/innovation"]',
                '.program-card a', '.opportunity-card a', '.venture-card a',
                '.card a', '.item a', 'article a', '.post a',
                'a:has-text("Learn more")', 'a:has-text("Apply")', 'a:has-text("Join")',
                'a:has-text("Read more")', 'a:has-text("View details")',
                'a:has-text("Register")', 'a:has-text("Submit")'
            ]
            
            for selector in specific_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for element in elements:
                        href = await element.get_attribute('href')
                        if href and self.is_opportunity_url_ultra_permissive(href):
                            normalized = self.normalize_url(href)
                            if normalized:
                                all_urls.add(normalized)
                except:
                    continue
            
            # STRATÉGIE 2: Analyse par containers
            container_selectors = [
                '.card', '.item', '.post', '.entry', 'article', 'section',
                '[class*="program"]', '[class*="opportunity"]', '[class*="listing"]',
                '.grid-item', '.list-item', '.row > div', '.col > div',
                '[class*="card"]', '[class*="item"]'
            ]
            
            for selector in container_selectors:
                try:
                    containers = await page.query_selector_all(selector)
                    for container in containers:
                        links = await container.query_selector_all('a[href]')
                        for link in links:
                            href = await link.get_attribute('href')
                            if href and self.is_opportunity_url_ultra_permissive(href):
                                normalized = self.normalize_url(href)
                                if normalized:
                                    all_urls.add(normalized)
                except:
                    continue
            
            # STRATÉGIE 3: TOUS les liens (analyse exhaustive)
            try:
                all_links = await page.query_selector_all('a[href]')
                
                for link in all_links:
                    href = await link.get_attribute('href')
                    if href and self.is_opportunity_url_ultra_permissive(href):
                        normalized = self.normalize_url(href)
                        if normalized:
                            all_urls.add(normalized)
            
            except Exception as e:
                print(f"   ❌ Erreur analyse exhaustive: {e}")
            
            return all_urls
            
        except Exception as e:
            print(f"   ❌ Erreur découverte: {e}")
            return set()
    
    async def discover_total_pages(self, page):
        """Découvre le nombre total de pages"""
        try:
            await page.goto(self.base_url, wait_until="networkidle", timeout=30000)
            await self.handle_popups(page)
            await page.wait_for_timeout(2000)
            
            max_page = 1
            
            # Méthode 1: Pagination visible
            pagination_selectors = [
                '.pagination a', '.page-numbers a', 'a[href*="/page/"]',
                '.nav-links a', '.wp-pagenavi a'
            ]
            
            for selector in pagination_selectors:
                try:
                    links = await page.query_selector_all(selector)
                    for link in links:
                        href = await link.get_attribute('href')
                        text = await link.inner_text()
                        
                        if href and '/page/' in href:
                            page_match = re.search(r'/page/(\d+)/', href)
                            if page_match:
                                page_num = int(page_match.group(1))
                                max_page = max(max_page, page_num)
                        
                        if text and text.isdigit():
                            page_num = int(text)
                            if 1 <= page_num <= 15:
                                max_page = max(max_page, page_num)
                
                except:
                    continue
            
            # Méthode 2: Test manuel
            if max_page <= 3:  # Si peu de pages trouvées, tester manuellement
                print("🔍 Test manuel de pagination...")
                for test_page in range(2, 12):
                    test_url = f"{self.base_url}page/{test_page}/"
                    
                    try:
                        print(f"   Test page {test_page}...")
                        response = await page.goto(test_url, wait_until="domcontentloaded", timeout=15000)
                        
                        if response and response.status == 200:
                            await page.wait_for_timeout(2000)
                            page_text = await page.inner_text('body')
                            
                            content_ok = (len(page_text) > 1000 and 
                                        'not found' not in page_text.lower())
                            
                            if content_ok:
                                relevant_links = await page.query_selector_all('a[href*="program"], a[href*="challenge"]')
                                if len(relevant_links) > 0:
                                    max_page = test_page
                                    print(f"   ✅ Page {test_page} valide")
                                else:
                                    break
                            else:
                                break
                        else:
                            break
                            
                    except:
                        break
            
            print(f"📖 Total: {max_page} pages détectées")
            return max_page
            
        except Exception as e:
            print(f"❌ Erreur découverte pagination: {e}")
            return 5
    
    async def handle_popups(self, page):
        """Gestion des popups"""
        try:
            popup_selectors = [
                'button:has-text("Accept")', 'button:has-text("OK")',
                'button:has-text("Close")', '.cookie-accept'
            ]
            
            for selector in popup_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        await element.click()
                        await page.wait_for_timeout(1000)
                        break
                except:
                    continue
        except:
            pass
    
    async def extract_opportunity_details(self, page, opportunity_url):
        """Extrait TOUS les détails d'une opportunité (comme votre code original)"""
        try:
            print(f"🔍 Extraction: {opportunity_url}")
            
            response = await page.goto(opportunity_url, wait_until="networkidle", timeout=30000)
            
            if response.status == 404:
                print(f"   ❌ Page 404: {opportunity_url}")
                return None
            
            await page.wait_for_timeout(2000)
            
            page_title = await page.title()
            if 'not found' in page_title.lower() or 'error' in page_title.lower():
                print(f"   ❌ Page d'erreur: {opportunity_url}")
                return None
            
            opportunity = {
                'opportunity_url': opportunity_url,
                'scraped_at': datetime.now().isoformat()
            }
            
            # Extraire TOUS les détails comme dans votre code original
            await self.extract_title(page, opportunity)
            await self.extract_tagline(page, opportunity)
            await self.extract_description(page, opportunity)
            await self.extract_overview_details(page, opportunity)
            await self.extract_links(page, opportunity)
            await self.extract_dates(page, opportunity)
            
            # FILTRAGE FINAL : Vérifier si c'est une vraie opportunité
            title = opportunity.get('title', '').lower()
            
            # Exclure les pages génériques par titre
            generic_titles = [
                'explore programs', 'explore ventures', 'explorar programas',
                'programmes d\'exploration', 'sign up or log in', 'log in required',
                'accelerate your business venture'
            ]
            
            if any(generic in title for generic in generic_titles):
                print(f"   ❌ Page générique filtrée: {title}")
                return None
            
            # Vérifier qu'il y a un minimum de contenu
            if (not opportunity.get('title') or 
                len(opportunity.get('title', '')) < 3 or
                not opportunity.get('description')):
                print(f"   ❌ Contenu insuffisant")
                return None
            
            print(f"   ✅ Extrait: {opportunity.get('title', 'Sans titre')}")
            return opportunity
            
        except Exception as e:
            print(f"   ❌ Erreur extraction {opportunity_url}: {e}")
            return None
    
    # === MÉTHODES D'EXTRACTION DÉTAILLÉE (copiées de votre code original) ===
    
    async def extract_title(self, page, opportunity):
        """Extrait le titre principal"""
        title_selectors = [
            'h1', '.partner-content-header__title', '.title', '.program-title'
        ]
        
        for selector in title_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    title = await element.inner_text()
                    if title and len(title.strip()) > 2:
                        opportunity['title'] = title.strip()
                        return
            except:
                continue
        
        opportunity['title'] = ""
    
    async def extract_tagline(self, page, opportunity):
        """Extrait la tagline/sous-titre"""
        tagline_selectors = [
            '.partner-content-header__tagline', 'h2', '.subtitle', '.tagline'
        ]
        
        for selector in tagline_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    tagline = await element.inner_text()
                    if tagline and len(tagline.strip()) > 5:
                        opportunity['tagline'] = tagline.strip()
                        return
            except:
                continue
        
        opportunity['tagline'] = ""
    
    async def extract_description(self, page, opportunity):
        """Extrait la description complète"""
        description_selectors = [
            '.partner-content-header__content', '.description', '.content', '.overview-content'
        ]
        
        description_parts = []
        
        for selector in description_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    desc = await element.inner_text()
                    if desc and len(desc.strip()) > 20:
                        description_parts.append(desc.strip())
            except:
                continue
        
        # Chercher aussi dans les paragraphes principaux
        try:
            paragraphs = await page.query_selector_all('p')
            for p in paragraphs[:3]:
                text = await p.inner_text()
                if text and len(text.strip()) > 50:
                    if not any(skip in text.lower() for skip in ['navigation', 'menu', 'footer', 'cookie']):
                        description_parts.append(text.strip())
        except:
            pass
        
        opportunity['description'] = ' | '.join(description_parts) if description_parts else ""
    
    async def extract_overview_details(self, page, opportunity):
        """Extrait les détails de la section Overview"""
        try:
            # Chercher la section Overview
            overview_selectors = [
                '.overview', '[class*="overview"]', '.details', '.program-details'
            ]
            
            overview_section = None
            for selector in overview_selectors:
                overview_section = await page.query_selector(selector)
                if overview_section:
                    break
            
            if overview_section:
                overview_text = await overview_section.inner_text()
                await self.parse_overview_content(overview_text, opportunity)
            
            # Extraction alternative via les éléments de liste
            await self.extract_detail_rows(page, opportunity)
            
        except Exception as e:
            if self.debug_mode:
                print(f"Erreur extraction overview: {e}")
    
    async def parse_overview_content(self, text, opportunity):
        """Parse le contenu de l'overview pour extraire les informations"""
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            line_lower = line.lower().strip()
            
            if 'days left' in line_lower or 'closes' in line_lower:
                if i + 1 < len(lines):
                    opportunity['deadline'] = lines[i + 1].strip()
                elif 'closes' in line:
                    match = re.search(r'closes\s+(.+)', line, re.IGNORECASE)
                    if match:
                        opportunity['deadline'] = match.group(1).strip()
            
            elif 'program dates' in line_lower:
                if i + 1 < len(lines):
                    opportunity['program_dates'] = lines[i + 1].strip()
            
            elif 'organizer' in line_lower:
                if i + 1 < len(lines):
                    opportunity['organization'] = lines[i + 1].strip()
            
            elif 'targets' in line_lower or 'target' in line_lower:
                if i + 1 < len(lines):
                    opportunity['targets'] = lines[i + 1].strip()
            
            elif any(keyword in line_lower for keyword in ['sector', 'industry', 'category']):
                if i + 1 < len(lines):
                    opportunity['sectors'] = lines[i + 1].strip()
    
    async def extract_detail_rows(self, page, opportunity):
        """Extrait les détails via regex"""
        try:
            all_text = await page.inner_text('body')
            
            patterns = {
                'deadline': r'(?:deadline|closes|due)[:\s]*([^\n]+)',
                'organization': r'(?:organizer|organization)[:\s]*([^\n]+)',
                'targets': r'(?:targets?)[:\s]*([^\n]+)',
                'sectors': r'(?:sectors?|industry)[:\s]*([^\n]+)',
                'program_dates': r'(?:program dates?)[:\s]*([^\n]+)'
            }
            
            for field, pattern in patterns.items():
                if field not in opportunity or not opportunity.get(field):
                    match = re.search(pattern, all_text, re.IGNORECASE)
                    if match:
                        value = match.group(1).strip()
                        if len(value) > 1:
                            opportunity[field] = value
            
        except Exception as e:
            if self.debug_mode:
                print(f"Erreur extraction detail rows: {e}")
    
    async def extract_links(self, page, opportunity):
        """Extrait les liens importants"""
        try:
            # Lien d'application
            apply_selectors = [
                'a:has-text("Apply")', 'a[href*="apply"]', 'a[href*="application"]',
                'a:has-text("Register")', 'a:has-text("Join")', '.btn-apply', '.apply-button'
            ]
            
            for selector in apply_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        href = await element.get_attribute('href')
                        if href:
                            opportunity['application_link'] = self.normalize_url(href)
                            break
                except:
                    continue
            
            # Website de l'organisation
            website_selectors = [
                'a:has-text("Visit website")', 'a:has-text("Website")',
                'a[href*="http"]:not([href*="vc4a.com"])'
            ]
            
            for selector in website_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        href = await element.get_attribute('href')
                        if href and href.startswith('http') and 'vc4a.com' not in href:
                            opportunity['organization_website'] = href
                            break
                except:
                    continue
            
        except Exception as e:
            if self.debug_mode:
                print(f"Erreur extraction liens: {e}")
    
    async def extract_dates(self, page, opportunity):
        """Extrait les dates importantes"""
        try:
            page_text = await page.inner_text('body')
            
            # Pattern pour "X days left"
            days_left_match = re.search(r'(\d+)\s+days?\s+left', page_text, re.IGNORECASE)
            if days_left_match:
                opportunity['days_left'] = f"{days_left_match.group(1)} days left"
            
            # Patterns pour les dates
            date_patterns = [
                r'(?:closes?|deadline|due)[:\s]*([A-Za-z]+ \d{1,2}, \d{4})',
                r'(?:closes?|deadline|due)[:\s]*(\d{1,2} [A-Za-z]+ \d{4})',
                r'(\d{1,2}/\d{1,2}/\d{4})',
                r'(\d{1,2}-\d{1,2}-\d{4})'
            ]
            
            for pattern in date_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    if 'deadline' not in opportunity or not opportunity.get('deadline'):
                        opportunity['deadline'] = match.group(1).strip()
                    break
            
        except Exception as e:
            if self.debug_mode:
                print(f"Erreur extraction dates: {e}")
    
    def clean_opportunity_data(self, data):
        """Nettoie et organise les données (format exact comme votre original)"""
        return {
            'title': data.get('title', ''),
            'tagline': data.get('tagline', ''),
            'description': data.get('description', ''),
            'organization': data.get('organization', ''),
            'organization_website': data.get('organization_website', ''),
            'opportunity_url': data.get('opportunity_url', ''),
            'application_link': data.get('application_link', ''),
            'deadline': data.get('deadline', ''),
            'days_left': data.get('days_left', ''),
            'program_dates': data.get('program_dates', ''),
            'sectors': data.get('sectors', ''),
            'targets': data.get('targets', ''),
            'scraped_at': data.get('scraped_at', '')
        }
    
    async def run_complete_scraping(self):
        """Méthode principale - découverte exhaustive + extraction complète"""
        async with async_playwright() as playwright:
            browser, page = await self.setup_browser(playwright)
            
            try:
                print("🚀 === SCRAPER VC4A COMPLET ===")
                print("Découverte exhaustive + Extraction détaillée\n")
                
                # PHASE 1: Découverte de toutes les URLs
                print("📍 PHASE 1: Découverte des opportunités...")
                
                total_pages = await self.discover_total_pages(page)
                all_opportunity_urls = set()
                
                # Explorer toutes les pages
                for page_num in range(1, total_pages + 1):
                    print(f"\n📄 Page {page_num}/{total_pages}")
                    
                    page_url = self.base_url if page_num == 1 else f"{self.base_url}page/{page_num}/"
                    
                    try:
                        print(f"🌐 Navigation: {page_url}")
                        await page.goto(page_url, wait_until="networkidle", timeout=30000)
                        
                        if page_num == 1:
                            await self.handle_popups(page)
                        
                        await self.smart_page_load(page)
                        
                        # Découvrir les opportunités sur cette page
                        page_urls = await self.discover_all_opportunity_urls(page)
                        new_urls = page_urls - all_opportunity_urls
                        all_opportunity_urls.update(page_urls)
                        
                        print(f"📊 Page {page_num}: {len(page_urls)} trouvées, {len(new_urls)} nouvelles")
                        print(f"📈 Total cumulé: {len(all_opportunity_urls)} opportunités")
                        
                    except Exception as e:
                        print(f"❌ Erreur page {page_num}: {e}")
                        continue
                
                print(f"\n🎯 PHASE 1 TERMINÉE: {len(all_opportunity_urls)} opportunités découvertes")
                
                # PHASE 2: Extraction détaillée
                print(f"\n📝 PHASE 2: Extraction des détails...")
                
                extracted_opportunities = []
                
                for i, url in enumerate(sorted(all_opportunity_urls), 1):
                    print(f"\n[{i}/{len(all_opportunity_urls)}] {url}")
                    
                    details = await self.extract_opportunity_details(page, url)
                    
                    if details and details.get('title'):
                        clean_opp = self.clean_opportunity_data(details)
                        extracted_opportunities.append(clean_opp)
                        
                        # Sauvegarde progressive
                        if len(extracted_opportunities) % 10 == 0:
                            print(f"💾 Sauvegarde progressive: {len(extracted_opportunities)} opportunités")
                            self.save_partial_results(extracted_opportunities)
                    
                    # Pause entre requêtes
                    await asyncio.sleep(1.5)
                
                return extracted_opportunities
                
            finally:
                await browser.close()
    
    def save_partial_results(self, opportunities):
        """Sauvegarde partielle"""
        try:
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"vc4a_complete_partial_{timestamp}.json"
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(opportunities, f, indent=2, ensure_ascii=False)
            
            print(f"   💾 Sauvegarde partielle: {filename}")
        except Exception as e:
            print(f"   ❌ Erreur sauvegarde: {e}")
    
    def save_final_results(self, opportunities):
        """Sauvegarde finale (format exact comme votre original)"""
        if not opportunities:
            print("❌ Aucune opportunité à sauvegarder")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # JSON
        json_filename = f"vc4a_complete_final_{timestamp}.json"
        try:
            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump(opportunities, f, indent=2, ensure_ascii=False)
            print(f"📄 JSON: {json_filename}")
        except Exception as e:
            print(f"❌ Erreur JSON: {e}")
        
        # CSV
        csv_filename = f"vc4a_complete_final_{timestamp}.csv"
        try:
            with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
                fieldnames = list(opportunities[0].keys())
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for opp in opportunities:
                    writer.writerow(opp)
            print(f"📄 CSV: {csv_filename}")
        except Exception as e:
            print(f"❌ Erreur CSV: {e}")
        
        # Rapport détaillé
        self.generate_report(opportunities, timestamp)
    
    def generate_report(self, opportunities, timestamp):
        """Génère un rapport détaillé"""
        try:
            report_filename = f"vc4a_complete_report_{timestamp}.txt"
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                f.write("=== RAPPORT SCRAPING VC4A COMPLET ===\n\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Opportunités extraites: {len(opportunities)}\n\n")
                
                # Statistiques de qualité
                with_org = len([o for o in opportunities if o.get('organization')])
                with_deadline = len([o for o in opportunities if o.get('deadline')])
                with_website = len([o for o in opportunities if o.get('organization_website')])
                with_apply = len([o for o in opportunities if o.get('application_link')])
                with_tagline = len([o for o in opportunities if o.get('tagline')])
                with_sectors = len([o for o in opportunities if o.get('sectors')])
                with_targets = len([o for o in opportunities if o.get('targets')])
                
                f.write("=== STATISTIQUES DE QUALITÉ ===\n")
                f.write(f"Avec organisation: {with_org}/{len(opportunities)} ({with_org/len(opportunities)*100:.1f}%)\n")
                f.write(f"Avec deadline: {with_deadline}/{len(opportunities)} ({with_deadline/len(opportunities)*100:.1f}%)\n")
                f.write(f"Avec website organisation: {with_website}/{len(opportunities)} ({with_website/len(opportunities)*100:.1f}%)\n")
                f.write(f"Avec lien application: {with_apply}/{len(opportunities)} ({with_apply/len(opportunities)*100:.1f}%)\n")
                f.write(f"Avec tagline: {with_tagline}/{len(opportunities)} ({with_tagline/len(opportunities)*100:.1f}%)\n")
                f.write(f"Avec secteurs: {with_sectors}/{len(opportunities)} ({with_sectors/len(opportunities)*100:.1f}%)\n")
                f.write(f"Avec targets: {with_targets}/{len(opportunities)} ({with_targets/len(opportunities)*100:.1f}%)\n\n")
                
                # Analyse des deadlines
                deadlines = [o.get('deadline', '') for o in opportunities if o.get('deadline')]
                f.write(f"=== ANALYSE DES DEADLINES ===\n")
                f.write(f"Deadlines trouvées: {len(deadlines)}\n")
                for d in deadlines:
                    f.write(f"  - {d}\n")
                f.write("\n")
                
                # Organisations trouvées
                organizations = list(set([o.get('organization', '') for o in opportunities if o.get('organization')]))
                f.write(f"=== ORGANISATIONS ({len(organizations)}) ===\n")
                for org in sorted(organizations):
                    f.write(f"  - {org}\n")
                f.write("\n")
                
                # Pays/régions ciblés
                targets = list(set([o.get('targets', '') for o in opportunities if o.get('targets')]))
                f.write(f"=== RÉGIONS CIBLÉES ({len(targets)}) ===\n")
                for target in sorted(targets):
                    f.write(f"  - {target}\n")
                f.write("\n")
                
                f.write("=== DÉTAILS COMPLETS ===\n\n")
                for i, opp in enumerate(opportunities, 1):
                    f.write(f"{i}. {opp.get('title', 'Sans titre')}\n")
                    f.write(f"   Organisation: {opp.get('organization', 'N/A')}\n")
                    f.write(f"   Tagline: {opp.get('tagline', 'N/A')}\n")
                    f.write(f"   Deadline: {opp.get('deadline', 'N/A')}\n")
                    f.write(f"   Days left: {opp.get('days_left', 'N/A')}\n")
                    f.write(f"   Program dates: {opp.get('program_dates', 'N/A')}\n")
                    f.write(f"   Sectors: {opp.get('sectors', 'N/A')[:100]}...\n")
                    f.write(f"   Targets: {opp.get('targets', 'N/A')}\n")
                    f.write(f"   Website org: {opp.get('organization_website', 'N/A')}\n")
                    f.write(f"   Apply link: {opp.get('application_link', 'N/A')}\n")
                    f.write(f"   URL: {opp.get('opportunity_url', 'N/A')}\n\n")
                    
            print(f"📊 Rapport sauvegardé: {report_filename}")
        except Exception as e:
            print(f"❌ Erreur rapport: {e}")

# Script principal
async def main():
    scraper = VC4ACompleteScraper()
    
    try:
        # Lancer le scraping complet
        opportunities = await scraper.run_complete_scraping()
        
        if opportunities:
            print(f"\n🎉 === SCRAPING COMPLET TERMINÉ ===")
            print(f"📊 {len(opportunities)} opportunités extraites avec tous les détails!")
            
            # Sauvegarde finale
            scraper.save_final_results(opportunities)
            
            # Statistiques rapides
            print(f"\n📈 STATISTIQUES RAPIDES:")
            print(f"  • Avec organisation: {len([o for o in opportunities if o.get('organization')])}")
            print(f"  • Avec deadline: {len([o for o in opportunities if o.get('deadline')])}")
            print(f"  • Avec tagline: {len([o for o in opportunities if o.get('tagline')])}")
            print(f"  • Avec lien d'application: {len([o for o in opportunities if o.get('application_link')])}")
            print(f"  • Avec website organisation: {len([o for o in opportunities if o.get('organization_website')])}")
            
            # Aperçu des résultats (format comme votre premier exemple)
            print(f"\n🔍 APERÇU DES OPPORTUNITÉS (5 premières):")
            for i, opp in enumerate(opportunities[:5], 1):
                print(f"\n{i}. {opp.get('title', 'Sans titre')}")
                print(f"   Organisation: {opp.get('organization', 'N/A')}")
                print(f"   Tagline: {opp.get('tagline', 'N/A')}")
                print(f"   Deadline: {opp.get('deadline', 'N/A')}")
                print(f"   Targets: {opp.get('targets', 'N/A')}")
                print(f"   URL: {opp.get('opportunity_url', 'N/A')}")
                
            if len(opportunities) > 5:
                print(f"\n... et {len(opportunities) - 5} autres opportunités avec tous les détails")
            
            print(f"\n📁 FICHIERS GÉNÉRÉS:")
            print(f"  • JSON avec toutes les données détaillées")
            print(f"  • CSV pour analyse")
            print(f"  • Rapport complet avec statistiques")
            
            # Exemple du format de données (comme votre premier exemple)
            if opportunities:
                print(f"\n📝 EXEMPLE DE DONNÉES EXTRAITES:")
                example = opportunities[0]
                print(f"{{")
                for key, value in example.items():
                    if isinstance(value, str) and len(value) > 100:
                        print(f'  "{key}": "{value[:60]}...",')
                    else:
                        print(f'  "{key}": "{value}",')
                print(f"}}")
            
        else:
            print("❌ Aucune opportunité extraite")
            
    except KeyboardInterrupt:
        print("\n⏹️ Arrêt demandé par l'utilisateur")
    except Exception as e:
        print(f"❌ Erreur fatale: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())