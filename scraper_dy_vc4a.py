#!/usr/bin/env python3
"""
VC4A Comprehensive Scraper
Découverte exhaustive + Extraction détaillée + Enrichissement IA + Extraction de logos
"""

import asyncio
import json
import csv
import requests
import base64
import re
import os
from datetime import datetime
from typing import Set, List, Dict, Optional
from urllib.parse import urljoin, urlparse
from collections import Counter

import google.generativeai as genai
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv('config.env')


class ConfigManager:
    """Gestionnaire de configuration centralisé"""
    
    def __init__(self):
        self.base_url = "https://vc4a.com/programs/"
        self.debug_mode = True
        self.page_timeout = 30000
        self.scroll_delay = 1000
        self.request_delay = 2
        
        # Configuration navigateur
        self.browser_config = {
            'headless': False,
            'slow_mo': 1000,
            'user_agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            'viewport': {"width": 1920, "height": 1080}
        }


class URLValidator:
    """Validateur d'URLs pour les opportunités"""
    
    @staticmethod
    def is_valid_opportunity_url(url: str) -> bool:
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
    
    @staticmethod
    def normalize_url(href: str) -> Optional[str]:
        """Normalise une URL"""
        if not href:
            return None
        
        if href.startswith('http'):
            return href
        elif href.startswith('/'):
            return f"https://vc4a.com{href}"
        else:
            return f"https://vc4a.com/{href}"


class LLMAnalyzer:
    """Analyseur LLM pour enrichir les données avec Gemini AI"""
    
    def __init__(self):
        self._setup_gemini()
    
    def _setup_gemini(self):
        """Configure Gemini AI"""
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("Clé API Gemini non trouvée. Vérifiez votre fichier config.env")
        
        genai.configure(api_key=api_key)
        
        try:
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            print("✓ Configuration Gemini AI réussie avec gemini-1.5-flash")
        except Exception as e:
            try:
                self.model = genai.GenerativeModel('gemini-1.5-pro')
                print("✓ Configuration Gemini AI réussie avec gemini-1.5-pro")
            except Exception as e2:
                print(f"Erreur de configuration Gemini: {e}")
                raise ValueError("Impossible de configurer Gemini AI")
    
    def _get_llm_prompt(self) -> str:
        """Configure le prompt pour l'extraction LLM"""
        return """
        Analysez le contenu suivant d'une opportunité d'affaires et extrayez les informations demandées.
        
        Titre: {title}
        Sous-titre: {subtitle}
        Description: {description}
        Organisation: {organization}
        Secteurs détectés: {detected_sectors}
        
        Veuillez fournir UNIQUEMENT un JSON valide avec ces clés :
        - meta_title: Titre optimisé SEO (max 100 caractères)
        - meta_description: Based on the title and subtitle, create an SEO-optimized meta description, no longer than 130 characters.
        - slug: URL slug (minuscules, tirets)
        - sectors: Liste des secteurs (choisir parmi: ["Regulatory Tech", "Spatial Computing", "AgriTech", "Agribusiness", "Artificial Intelligence", "Banking", "Blockchain", "Business Process Outsourcing (BPO)", "CleanTech", "Creative", "Cryptocurrencies", "Cybersecurity & Digital ID", "Data Aggregation", "Debt Management", "DeepTech", "Design & Applied Arts", "Digital & Interactive", "E-commerce and Retail", "Economic Development", "EdTech", "Energy", "Environmental Social Governance (ESG)", "FinTech", "Gaming", "HealthTech", "InsurTech", "Logistics", "ManuTech", "Manufacturing", "Media & Communication", "Mobility and Transportation", "Performing & Visual Arts", "Sector Agnostic", "Sport Management", "Sustainability", "Technology", "Tourism Innovation", "Transformative Digital Technologies", "Wearables"])
        - stages: Liste des étapes (choisir parmi: ["Not Applicable", "Pre-Series A", "Pre-seed", "Seed", "Series A", "Series B", "Series C", "Series D", "Series E", "Series F", "Stage Agnostic"])
        - categories: Liste des catégories (choisir parmi: ["Accelerator", "Bootcamp", "Competition", "Conference", "Event", "Funding Opportunity", "Hackathon", "Incubator", "Other", "Summit"])
        - draft_summary: Please craft a fully structured, rephrased article from the provided information in bullet-point format. Begin with an introduction, continue with a detailed body under clear headings, and finish with a compelling closing statement. The piece must remain neutral—treat it as a media listing that simply highlights incubator and accelerator programs and their application details, without suggesting these are our own initiatives or that we accept applications.
        - main_image_alt: Texte alternatif pour l'image principale approprié au contenu
        """
    
    async def analyze_opportunity(self, opportunity_data: Dict) -> Dict:
        """Analyse le contenu avec Gemini AI pour extraire les métadonnées"""
        try:
            prompt = self._get_llm_prompt().format(
                title=opportunity_data.get('title', '')[:200],
                subtitle=opportunity_data.get('subtitle', '')[:300],
                description=opportunity_data.get('description', '')[:1000],
                organization=opportunity_data.get('organization', ''),
                detected_sectors=opportunity_data.get('sectors', '')[:500]
            )
            
            response = self.model.generate_content(prompt)
            
            json_text = response.text.strip()
            if json_text.startswith('```json'):
                json_text = json_text[7:-3]
            elif json_text.startswith('```'):
                json_text = json_text[3:-3]
            
            llm_result = json.loads(json_text)
            
            print(f" LLM - Métadonnées générées pour: {opportunity_data.get('title', 'Sans titre')}")
            
            return llm_result
            
        except Exception as e:
            print(f" Erreur LLM: {e}")
            return self._get_fallback_result(opportunity_data)
    
    def _get_fallback_result(self, opportunity_data: Dict) -> Dict:
        """Retourne un résultat de secours en cas d'erreur LLM"""
        return {
            'meta_title': opportunity_data.get('title', '')[:100],
            'meta_description': opportunity_data.get('subtitle', '')[:130],
            'slug': self._create_slug(opportunity_data.get('title', '')),
            'sectors': [],
            'stages': [],
            'categories': [],
            'draft_summary': opportunity_data.get('description', ''),
            'main_image_alt': f"Image for {opportunity_data.get('title', 'opportunity')}"
        }
    
    def _create_slug(self, title: str) -> str:
        """Crée un slug URL à partir du titre"""
        if not title:
            return ""
        
        slug = title.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug)
        slug = slug.strip('-')
        return slug


class LogoExtractor:
    """Extracteur de logos d'organisations"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
    
    async def extract_logo(self, organization_website: str) -> Optional[str]:
        """Extrait le logo de l'organisation depuis son site web"""
        if not organization_website:
            return None
            
        try:
            print(f" Extraction logo depuis: {organization_website}")
            
            if not organization_website.startswith(('http://', 'https://')):
                organization_website = 'https://' + organization_website
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/svg+xml,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            }
            
            response = self.session.get(organization_website, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            header_elements = self._find_header_elements(soup)
            
            # Application des stratégies d'extraction de logo
            strategies = [
                self._find_logo_by_alt_attribute,
                self._find_logo_svg_elements,
                self._find_logo_in_containers,
                self._find_logo_by_src_content,
                self._find_logo_by_data_attributes,
                self._find_logo_by_context_analysis,
                self._find_logo_intelligent_fallback
            ]
            
            for strategy in strategies:
                logo_url = strategy(header_elements, organization_website)
                if logo_url:
                    print(f" Logo trouvé: {logo_url}")
                    return logo_url
            
            print(f" Aucun logo trouvé")
            return None
            
        except Exception as e:
            print(f" Erreur extraction logo: {e}")
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
        
        return unique_headers
    
    def _find_logo_by_alt_attribute(self, header_elements, base_url):
        """STRATÉGIE 1: Recherche d'images avec attribut alt contenant 'logo'"""
        logo_keywords = ['logo', 'brand', 'company', 'organization', 'site']
        
        for header in header_elements:
            images = header.find_all('img', alt=True)
            
            for img in images:
                alt_text = img.get('alt', '').lower()
                src = img.get('src')
                
                if any(keyword in alt_text for keyword in logo_keywords):
                    if src:
                        logo_url = self._normalize_logo_url(src, base_url)
                        if self._is_valid_logo_candidate(logo_url, img):
                            return logo_url
        
        return None
    
    def _find_logo_svg_elements(self, header_elements, base_url):
        """STRATÉGIE 2: Recherche d'éléments SVG avec classes ou IDs logo"""
        for header in header_elements:
            # SVG avec class contenant "logo"
            svg_elements = header.find_all('svg', class_=re.compile('logo', re.I))
            for svg in svg_elements:
                svg_url = self._extract_svg_as_logo(svg, base_url)
                if svg_url:
                    return svg_url
            
            # SVG avec ID contenant "logo"
            svg_elements = header.find_all('svg', id=re.compile('logo', re.I))
            for svg in svg_elements:
                svg_url = self._extract_svg_as_logo(svg, base_url)
                if svg_url:
                    return svg_url
        
        return None
    
    def _find_logo_in_containers(self, header_elements, base_url):
        """STRATÉGIE 3: Recherche dans containers avec class/id 'logo'"""
        container_selectors = [
            '[class*="logo" i]', '[id*="logo" i]', '[class*="brand" i]', 
            '[id*="brand" i]', '.site-title', '.site-logo', '.brand-logo', '.company-logo'
        ]
        
        for header in header_elements:
            for selector in container_selectors:
                containers = header.select(selector)
                
                for container in containers:
                    img = container.find('img')
                    if img and img.get('src'):
                        logo_url = self._normalize_logo_url(img.get('src'), base_url)
                        if self._is_valid_logo_candidate(logo_url, img):
                            return logo_url
        
        return None
    
    def _find_logo_by_src_content(self, header_elements, base_url):
        """STRATÉGIE 4: Images avec src contenant 'logo'"""
        for header in header_elements:
            images = header.find_all('img', src=True)
            
            for img in images:
                src = img.get('src', '').lower()
                
                if 'logo' in src and not any(exclude in src for exclude in ['icon', 'avatar', 'profile']):
                    logo_url = self._normalize_logo_url(img.get('src'), base_url)
                    if self._is_valid_logo_candidate(logo_url, img):
                        return logo_url
        
        return None
    
    def _find_logo_by_data_attributes(self, header_elements, base_url):
        """STRATÉGIE 5: Images avec attributs data-* contenant 'logo'"""
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
                                if self._is_valid_logo_candidate(logo_url, img):
                                    return logo_url
        
        return None
    
    def _find_logo_by_context_analysis(self, header_elements, base_url):
        """STRATÉGIE 6: Analyse contextuelle"""
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
                        if self._is_valid_logo_candidate(logo_url, img):
                            return logo_url
        
        return None
    
    def _find_logo_intelligent_fallback(self, header_elements, base_url):
        """STRATÉGIE 7: Fallback intelligent"""
        for header in header_elements:
            images = header.find_all('img', src=True)
            
            for img in images[:3]:  # Limiter aux 3 premières images
                src = img.get('src', '').lower()
                
                # Exclure les images clairement non-logo
                exclude_patterns = [
                    'icon', 'arrow', 'menu', 'search', 'close', 'burger', 'hamburger',
                    'facebook', 'twitter', 'linkedin', 'instagram', 'youtube', 'social'
                ]
                
                if any(pattern in src for pattern in exclude_patterns):
                    continue
                
                logo_url = self._normalize_logo_url(img.get('src'), base_url)
                if self._is_valid_logo_candidate(logo_url, img):
                    return logo_url
        
        return None
    
    def _extract_svg_as_logo(self, svg_element, base_url):
        """Extrait un SVG comme logo"""
        try:
            svg_content = str(svg_element)
            if len(svg_content) > 100 and ('path' in svg_content or 'circle' in svg_content or 'rect' in svg_content):
                # Créer une data URL pour le SVG
                svg_bytes = svg_content.encode('utf-8')
                svg_base64 = base64.b64encode(svg_bytes).decode('utf-8')
                return f"data:image/svg+xml;base64,{svg_base64}"
            
            return None
            
        except Exception as e:
            return None
    
    def _normalize_logo_url(self, logo_src, base_url):
        """Normalise l'URL du logo"""
        if not logo_src:
            return None
        
        if logo_src.startswith(('http://', 'https://')):
            return logo_src
        
        if logo_src.startswith('/'):
            parsed_url = urlparse(base_url)
            return f"{parsed_url.scheme}://{parsed_url.netloc}{logo_src}"
        
        return urljoin(base_url, logo_src)
    
    def _is_valid_logo_candidate(self, logo_url, img_element):
        """Vérifie si une URL d'image est un bon candidat pour être un logo"""
        if not logo_url:
            return False
        
        if logo_url.startswith('data:image/'):
            return True
        
        valid_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']
        has_valid_ext = any(ext in logo_url.lower() for ext in valid_extensions)
        
        if not has_valid_ext:
            return False
        
        # Vérifier que l'image existe
        try:
            head_response = self.session.head(logo_url, timeout=5)
            if head_response.status_code == 200:
                content_type = head_response.headers.get('content-type', '')
                return 'image' in content_type
        except:
            pass
        
        return True


class OpportunityExtractor:
    """Extracteur de détails des opportunités"""
    
    def __init__(self, config: ConfigManager, debug_mode: bool = True):
        self.config = config
        self.debug_mode = debug_mode
    
    async def extract_title(self, page, opportunity: Dict):
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
    
    async def extract_subtitle(self, page, opportunity: Dict):
        """Extrait la subtitle (anciennement tagline)"""
        subtitle_selectors = [
            '.partner-content-header__tagline', 'h2', '.subtitle', '.tagline'
        ]
        
        for selector in subtitle_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    subtitle = await element.inner_text()
                    if subtitle and len(subtitle.strip()) > 5:
                        opportunity['subtitle'] = subtitle.strip()
                        return
            except:
                continue
        
        opportunity['subtitle'] = ""
    
    async def extract_description(self, page, opportunity: Dict):
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
    
    async def extract_overview_details(self, page, opportunity: Dict):
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
                await self._parse_overview_content(overview_text, opportunity)
            
            # Extraction alternative via les éléments de liste
            await self._extract_detail_rows(page, opportunity)
            
        except Exception as e:
            if self.debug_mode:
                print(f"Erreur extraction overview: {e}")
    
    async def _parse_overview_content(self, text: str, opportunity: Dict):
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
    
    async def _extract_detail_rows(self, page, opportunity: Dict):
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
    
    async def extract_links(self, page, opportunity: Dict):
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
                            opportunity['application_link'] = URLValidator.normalize_url(href)
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
    
    async def extract_dates(self, page, opportunity: Dict):
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


class DataSaver:
    """Gestionnaire de sauvegarde des données"""
    
    @staticmethod
    def clean_opportunity_data(data: Dict) -> Dict:
        """Nettoie et organise les données avec les nouveaux champs LLM"""
        return {
            # Données originales
            'title': data.get('title', ''),
            'subtitle': data.get('subtitle', ''),
            'description': data.get('description', ''),
            'organization': data.get('organization', ''),
            'organization_website': data.get('organization_website', ''),
            'organization_logo': data.get('organization_logo', ''),
            'opportunity_url': data.get('opportunity_url', ''),
            'application_link': data.get('application_link', ''),
            'deadline': data.get('deadline', ''),
            'days_left': data.get('days_left', ''),
            'program_dates': data.get('program_dates', ''),
            'sectors': data.get('sectors', ''),
            'targets': data.get('targets', ''),
            'scraped_at': data.get('scraped_at', ''),
            
            # Nouveaux champs LLM
            'meta_title': data.get('meta_title', ''),
            'meta_description': data.get('meta_description', ''),
            'slug': data.get('slug', ''),
            'llm_sectors': data.get('sectors', []) if isinstance(data.get('sectors'), list) else [],
            'stages': data.get('stages', []),
            'categories': data.get('categories', []),
            'draft_summary': data.get('draft_summary', ''),
            'main_image_alt': data.get('main_image_alt', '')
        }
    
    @staticmethod
    def save_partial_results(opportunities: List[Dict]):
        """Sauvegarde partielle"""
        try:
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"vc4a_enhanced_partial_{timestamp}.json"
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(opportunities, f, indent=2, ensure_ascii=False)
            
            print(f"    Sauvegarde partielle: {filename}")
        except Exception as e:
            print(f"    Erreur sauvegarde: {e}")
    
    @staticmethod
    def save_final_results(opportunities: List[Dict]):
        """Sauvegarde finale avec les nouveaux champs"""
        if not opportunities:
            print(" Aucune opportunité à sauvegarder")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # JSON
        json_filename = f"vc4a_enhanced_final_{timestamp}.json"
        try:
            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump(opportunities, f, indent=2, ensure_ascii=False)
            print(f" JSON: {json_filename}")
        except Exception as e:
            print(f" Erreur JSON: {e}")
        
        # CSV
        csv_filename = f"vc4a_enhanced_final_{timestamp}.csv"
        try:
            with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
                fieldnames = list(opportunities[0].keys())
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for opp in opportunities:
                    writer.writerow(opp)
            print(f" CSV: {csv_filename}")
        except Exception as e:
            print(f" Erreur CSV: {e}")
        
        # Rapport détaillé
        DataSaver.generate_enhanced_report(opportunities, timestamp)
    
    @staticmethod
    def generate_enhanced_report(opportunities: List[Dict], timestamp: str):
        """Génère un rapport détaillé avec les nouvelles métriques LLM"""
        try:
            report_filename = f"vc4a_enhanced_report_{timestamp}.txt"
            
            with open(report_filename, 'w', encoding='utf-8') as f:
                f.write("=== RAPPORT SCRAPING VC4A ENRICHI LLM ===\n\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Opportunités extraites: {len(opportunities)}\n\n")
                
                # Statistiques de qualité
                DataSaver._write_quality_stats(f, opportunities)
                
                # Statistiques LLM
                DataSaver._write_llm_stats(f, opportunities)
                
                # Analyses détaillées
                DataSaver._write_detailed_analysis(f, opportunities)
                
            print(f" Rapport enrichi sauvegardé: {report_filename}")
        except Exception as e:
            print(f" Erreur rapport: {e}")
    
    @staticmethod
    def _write_quality_stats(f, opportunities: List[Dict]):
        """Écrit les statistiques de qualité"""
        total = len(opportunities)
        stats = {
            'with_org': len([o for o in opportunities if o.get('organization')]),
            'with_deadline': len([o for o in opportunities if o.get('deadline')]),
            'with_website': len([o for o in opportunities if o.get('organization_website')]),
            'with_logo': len([o for o in opportunities if o.get('organization_logo')]),
            'with_apply': len([o for o in opportunities if o.get('application_link')]),
            'with_subtitle': len([o for o in opportunities if o.get('subtitle')]),
            'with_sectors': len([o for o in opportunities if o.get('sectors')])
        }
        
        f.write("=== STATISTIQUES DE QUALITÉ ===\n")
        for key, count in stats.items():
            percentage = count/total*100 if total > 0 else 0
            f.write(f"{key.replace('_', ' ').title()}: {count}/{total} ({percentage:.1f}%)\n")
        f.write("\n")
    
    @staticmethod
    def _write_llm_stats(f, opportunities: List[Dict]):
        """Écrit les statistiques LLM"""
        total = len(opportunities)
        llm_stats = {
            'with_llm_sectors': len([o for o in opportunities if o.get('llm_sectors')]),
            'with_meta_title': len([o for o in opportunities if o.get('meta_title')]),
            'with_meta_desc': len([o for o in opportunities if o.get('meta_description')]),
            'with_draft_summary': len([o for o in opportunities if o.get('draft_summary')])
        }
        
        f.write("=== STATISTIQUES ENRICHISSEMENT LLM ===\n")
        for key, count in llm_stats.items():
            percentage = count/total*100 if total > 0 else 0
            f.write(f"{key.replace('_', ' ').title()}: {count}/{total} ({percentage:.1f}%)\n")
        f.write("\n")
    
    @staticmethod
    def _write_detailed_analysis(f, opportunities: List[Dict]):
        """Écrit l'analyse détaillée par catégories"""
        # Analyse des secteurs LLM
        llm_sectors_flat = []
        for opp in opportunities:
            sectors = opp.get('llm_sectors', [])
            if isinstance(sectors, list):
                llm_sectors_flat.extend(sectors)
        
        unique_llm_sectors = list(set(llm_sectors_flat))
        f.write(f"=== SECTEURS DÉTECTÉS PAR LLM ({len(unique_llm_sectors)}) ===\n")
        for sector in sorted(unique_llm_sectors):
            count = llm_sectors_flat.count(sector)
            f.write(f"  - {sector}: {count} occurrences\n")
        f.write("\n")
        
        # Analyse des catégories et stages (similaire...)
        # [Le reste du code d'analyse...]


class VC4AScraper:
    """Scraper principal VC4A"""
    
    def __init__(self):
        self.config = ConfigManager()
        self.url_validator = URLValidator()
        self.llm_analyzer = LLMAnalyzer()
        self.logo_extractor = LogoExtractor()
        self.opportunity_extractor = OpportunityExtractor(self.config)
        self.data_saver = DataSaver()
        
        self.found_urls = set()
    
    async def setup_browser(self, playwright):
        """Configure le navigateur"""
        browser = await playwright.chromium.launch(
            headless=self.config.browser_config['headless'],
            slow_mo=self.config.browser_config['slow_mo'],
        )
        
        context = await browser.new_context(
            user_agent=self.config.browser_config['user_agent'],
            viewport=self.config.browser_config['viewport'],
        )
        
        page = await context.new_page()
        return browser, page
    
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
                        print(f"    Clic sur 'Load More'")
                        await button.click()
                        await page.wait_for_timeout(3000)
                        break
                except:
                    continue
            
            # Revenir en haut
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(1000)
            
        except Exception as e:
            if self.config.debug_mode:
                print(f"    Erreur smart load: {e}")
    
    async def discover_all_opportunity_urls(self, page) -> Set[str]:
        """Découverte EXHAUSTIVE de toutes les URLs d'opportunités"""
        all_urls = set()
        
        try:
            # Debug: analyser la page
            if self.config.debug_mode:
                stats = await page.evaluate("""
                    () => {
                        return {
                            total_links: document.querySelectorAll('a[href]').length,
                            program_links: document.querySelectorAll('a[href*="program"]').length,
                            cards: document.querySelectorAll('.card, [class*="card"], .item').length
                        };
                    }
                """)
                print(f"    Page: {stats['total_links']} liens, {stats['program_links']} avec 'program', {stats['cards']} cartes")
            
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
                        if href and self.url_validator.is_valid_opportunity_url(href):
                            normalized = self.url_validator.normalize_url(href)
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
                            if href and self.url_validator.is_valid_opportunity_url(href):
                                normalized = self.url_validator.normalize_url(href)
                                if normalized:
                                    all_urls.add(normalized)
                except:
                    continue
            
            # STRATÉGIE 3: TOUS les liens (analyse exhaustive)
            try:
                all_links = await page.query_selector_all('a[href]')
                
                for link in all_links:
                    href = await link.get_attribute('href')
                    if href and self.url_validator.is_valid_opportunity_url(href):
                        normalized = self.url_validator.normalize_url(href)
                        if normalized:
                            all_urls.add(normalized)
            
            except Exception as e:
                print(f"    Erreur analyse exhaustive: {e}")
            
            return all_urls
            
        except Exception as e:
            print(f"    Erreur découverte: {e}")
            return set()
    
    async def discover_total_pages(self, page) -> int:
        """Découvre le nombre total de pages"""
        try:
            await page.goto(self.config.base_url, wait_until="networkidle", timeout=self.config.page_timeout)
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
            
            # Méthode 2: Test manuel si peu de pages trouvées
            if max_page <= 3:
                print(" Test manuel de pagination...")
                for test_page in range(2, 12):
                    test_url = f"{self.config.base_url}page/{test_page}/"
                    
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
                                    print(f"    Page {test_page} valide")
                                else:
                                    break
                            else:
                                break
                        else:
                            break
                            
                    except:
                        break
            
            print(f" Total: {max_page} pages détectées")
            return max_page
            
        except Exception as e:
            print(f" Erreur découverte pagination: {e}")
            return 5
    
    async def extract_opportunity_details(self, page, opportunity_url: str) -> Optional[Dict]:
        """Extrait TOUS les détails d'une opportunité avec enrichissement LLM"""
        try:
            print(f" Extraction: {opportunity_url}")
            
            response = await page.goto(opportunity_url, wait_until="networkidle", timeout=30000)
            
            if response.status == 404:
                print(f"    Page 404: {opportunity_url}")
                return None
            
            await page.wait_for_timeout(2000)
            
            page_title = await page.title()
            if 'not found' in page_title.lower() or 'error' in page_title.lower():
                print(f"    Page d'erreur: {opportunity_url}")
                return None
            
            opportunity = {
                'opportunity_url': opportunity_url,
                'scraped_at': datetime.now().isoformat()
            }
            
            # Extraire TOUS les détails
            await self.opportunity_extractor.extract_title(page, opportunity)
            await self.opportunity_extractor.extract_subtitle(page, opportunity)
            await self.opportunity_extractor.extract_description(page, opportunity)
            await self.opportunity_extractor.extract_overview_details(page, opportunity)
            await self.opportunity_extractor.extract_links(page, opportunity)
            await self.opportunity_extractor.extract_dates(page, opportunity)
            
            # FILTRAGE FINAL : Vérifier si c'est une vraie opportunité
            title = opportunity.get('title', '').lower()
            
            # Exclure les pages génériques par titre
            generic_titles = [
                'explore programs', 'explore ventures', 'explorar programas',
                'programmes d\'exploration', 'sign up or log in', 'log in required',
                'accelerate your business venture'
            ]
            
            if any(generic in title for generic in generic_titles):
                print(f"    Page générique filtrée: {title}")
                return None
            
            # Vérifier qu'il y a un minimum de contenu
            if (not opportunity.get('title') or 
                len(opportunity.get('title', '')) < 3 or
                not opportunity.get('description')):
                print(f"    Contenu insuffisant")
                return None
            
            # ENRICHISSEMENT avec LLM
            print(f" Enrichissement LLM...")
            llm_data = await self.llm_analyzer.analyze_opportunity(opportunity)
            opportunity.update(llm_data)
            
            # EXTRACTION du logo de l'organisation
            org_website = opportunity.get('organization_website')
            if org_website:
                print(f" Extraction logo organisation...")
                organization_logo = await self.logo_extractor.extract_logo(org_website)
                if organization_logo:
                    opportunity['organization_logo'] = organization_logo
            
            print(f"    Extrait: {opportunity.get('title', 'Sans titre')}")
            return opportunity
            
        except Exception as e:
            print(f"    Erreur extraction {opportunity_url}: {e}")
            return None
    
    async def run_complete_scraping(self) -> List[Dict]:
        """Méthode principale - découverte exhaustive + extraction complète + LLM"""
        async with async_playwright() as playwright:
            browser, page = await self.setup_browser(playwright)
            
            try:
                print(" === SCRAPER VC4A COMPLET AVEC LLM ===")
                print("Découverte exhaustive + Extraction détaillée + Enrichissement IA\n")
                
                # PHASE 1: Découverte de toutes les URLs
                print(" PHASE 1: Découverte des opportunités...")
                
                total_pages = await self.discover_total_pages(page)
                all_opportunity_urls = set()
                
                # Explorer toutes les pages
                for page_num in range(1, total_pages + 1):
                    print(f"\n Page {page_num}/{total_pages}")
                    
                    page_url = self.config.base_url if page_num == 1 else f"{self.config.base_url}page/{page_num}/"
                    
                    try:
                        print(f" Navigation: {page_url}")
                        await page.goto(page_url, wait_until="networkidle", timeout=30000)
                        
                        if page_num == 1:
                            await self.handle_popups(page)
                        
                        await self.smart_page_load(page)
                        
                        # Découvrir les opportunités sur cette page
                        page_urls = await self.discover_all_opportunity_urls(page)
                        new_urls = page_urls - all_opportunity_urls
                        all_opportunity_urls.update(page_urls)
                        
                        print(f" Page {page_num}: {len(page_urls)} trouvées, {len(new_urls)} nouvelles")
                        print(f" Total cumulé: {len(all_opportunity_urls)} opportunités")
                        
                    except Exception as e:
                        print(f" Erreur page {page_num}: {e}")
                        continue
                
                print(f"\nPHASE 1 TERMINÉE: {len(all_opportunity_urls)} opportunités découvertes")
                
                # PHASE 2: Extraction détaillée avec enrichissement LLM
                print(f"\n PHASE 2: Extraction des détails + Enrichissement LLM...")
                
                extracted_opportunities = []
                
                for i, url in enumerate(sorted(all_opportunity_urls), 1):
                    print(f"\n[{i}/{len(all_opportunity_urls)}] {url}")
                    
                    details = await self.extract_opportunity_details(page, url)
                    
                    if details and details.get('title'):
                        clean_opp = self.data_saver.clean_opportunity_data(details)
                        extracted_opportunities.append(clean_opp)
                        
                        # Sauvegarde progressive
                        if len(extracted_opportunities) % 5 == 0:
                            print(f" Sauvegarde progressive: {len(extracted_opportunities)} opportunités")
                            self.data_saver.save_partial_results(extracted_opportunities)
                    
                    # Pause entre requêtes
                    await asyncio.sleep(self.config.request_delay)
                
                return extracted_opportunities
                
            finally:
                await browser.close()


# Script principal
async def main():
    scraper = VC4AScraper()
    
    try:
        # Lancer le scraping complet avec enrichissement LLM
        opportunities = await scraper.run_complete_scraping()
        
        if opportunities:
            print(f"\n === SCRAPING COMPLET ENRICHI TERMINÉ ===")
            print(f" {len(opportunities)} opportunités extraites avec enrichissement LLM!")
            
            # Sauvegarde finale
            scraper.data_saver.save_final_results(opportunities)
            
            # Statistiques rapides
            print(f"\n STATISTIQUES RAPIDES:")
            print(f"  • Avec organisation: {len([o for o in opportunities if o.get('organization')])}")
            print(f"  • Avec deadline: {len([o for o in opportunities if o.get('deadline')])}")
            print(f"  • Avec subtitle: {len([o for o in opportunities if o.get('subtitle')])}")
            print(f"  • Avec lien d'application: {len([o for o in opportunities if o.get('application_link')])}")
            print(f"  • Avec logo organisation: {len([o for o in opportunities if o.get('organization_logo')])}")
            print(f"  • Avec métadonnées LLM: {len([o for o in opportunities if o.get('meta_title')])}")
            print(f"  • Avec secteurs LLM: {len([o for o in opportunities if o.get('llm_sectors') and len(o.get('llm_sectors', [])) > 0])}")
            
            # Aperçu des résultats enrichis
            print(f"\n🔍 APERÇU DES OPPORTUNITÉS ENRICHIES (3 premières):")
            for i, opp in enumerate(opportunities[:3], 1):
                print(f"\n{i}. {opp.get('title', 'Sans titre')}")
                print(f"   Meta Title: {opp.get('meta_title', 'N/A')}")
                print(f"   Organisation: {opp.get('organization', 'N/A')}")
                print(f"   Secteurs LLM: {', '.join(opp.get('llm_sectors', [])[:3])}")
                print(f"   Logo organisation: {'yes' if opp.get('organization_logo') else 'no'}")
                
            if len(opportunities) > 3:
                print(f"\n... et {len(opportunities) - 3} autres opportunités enrichies")
            
            # Statistiques détaillées par secteur LLM
            print(f"\n TOP 5 SECTEURS DÉTECTÉS PAR LLM:")
            llm_sectors_flat = []
            for opp in opportunities:
                sectors = opp.get('llm_sectors', [])
                if isinstance(sectors, list):
                    llm_sectors_flat.extend(sectors)
            
            sector_counts = Counter(llm_sectors_flat)
            for sector, count in sector_counts.most_common(5):
                print(f"  • {sector}: {count} opportunités")
            
        else:
            print(" Aucune opportunité extraite")
            
    except KeyboardInterrupt:
        print("\nArrêt demandé par l'utilisateur")
    except Exception as e:
        print(f" Erreur fatale: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())