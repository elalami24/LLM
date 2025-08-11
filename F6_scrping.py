import os
from dotenv import load_dotenv
from zenrows import ZenRowsClient
from bs4 import BeautifulSoup
import json
import re
import time
import requests
from datetime import datetime

# Charger les variables d'environnement depuis config.env
load_dotenv('config.env')

class EnhancedF6SScraper:
    def __init__(self):
        # Récupérer les clés depuis les variables d'environnement
        self.zenrows_api_key = os.getenv('ZENROWS_API_KEY')
        self.gemini_api_key = os.getenv('GEMINI_API_KEY')
        
        # Vérifier que les clés sont présentes
        if not self.zenrows_api_key:
            raise ValueError(" ZENROWS_API_KEY non trouvée dans le fichier config.env")
        if not self.gemini_api_key:
            raise ValueError(" GEMINI_API_KEY non trouvée dans le fichier config.env")
        
        print(f" Clés API chargées depuis config.env")
        print(f"   ZenRows: {self.zenrows_api_key[:10]}...")
        print(f"   Gemini: {self.gemini_api_key[:10]}...")
        
        self.zenrows_client = ZenRowsClient(self.zenrows_api_key)
        self.opportunities = []
    
    def get_page_content(self, url):
        """Récupère le contenu de la page avec ZenRows"""
        try:
            print(f" Récupération de {url}...")
            params = {
                "premium_proxy": "true",
                "js_render": "true",
                "wait": "3000"
            }
            
            response = self.zenrows_client.get(url, params=params)
            
            if response.status_code == 200:
                print(f" Page récupérée ({len(response.text)} caractères)")
                return response.text
            else:
                print(f" Erreur HTTP: {response.status_code}")
                return None
                
        except Exception as e:
            print(f" Erreur ZenRows: {e}")
            return None
    
    def get_opportunity_details(self, opportunity_url):
        """Récupère les détails d'une opportunité spécifique"""
        try:
            print(f"  Récupération détails: {opportunity_url}")
            params = {"premium_proxy": "true"}
            
            # Ajouter un timeout pour éviter les blocages
            response = self.zenrows_client.get(opportunity_url, params=params, timeout=30)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Chercher le sélecteur spécifique "mw cover-blurb inline"
                subtitle_elem = soup.find('div', class_='mw cover-blurb inline')
                subtitle = ""
                if subtitle_elem:
                    subtitle = subtitle_elem.get_text(strip=True)
                
                # Récupérer tout le contenu de la page pour l'IA
                content_text = soup.get_text()
                
                return {
                    'subtitle': subtitle,
                    'full_content': content_text[:5000]  # Limiter à 5000 caractères
                }
            else:
                print(f"     Erreur détails: {response.status_code}")
                return None
                
        except requests.exceptions.Timeout:
            print(f"     Timeout lors de la récupération des détails")
            return None
        except Exception as e:
            print(f"     Erreur extraction détails: {e}")
            return None
    
    def enhance_with_gemini(self, opportunity_data, full_content):
        """Enrichit les données avec l'API Gemini"""
        try:
            print(f"   Enrichissement IA pour: {opportunity_data.get('title', 'Sans titre')[:30]}...")
            
            prompt = f"""
Analysez ce contenu d'opportunité et fournissez UNIQUEMENT un JSON valide avec ces clés exactes :

Titre: {opportunity_data.get('title', '')}
Subtitle: {opportunity_data.get('subtitle', '')}
Deadline: {opportunity_data.get('deadline', '')}

Contenu complet:
{full_content}

Veuillez fournir UNIQUEMENT un JSON valide avec ces clés :
- meta_title: Titre optimisé SEO (max 100 caractères)
- meta_description: Description SEO optimisée basée sur le titre et sous-titre (max 130 caractères)
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
- organization_name: Identifie précisément le nom de l'organisation responsable ou associée à l'opportunité décrite dans le contenu. Ne retourne que le nom officiel de l'organisation (par exemple : "Milken Institute and Motsepe Foundation"). Si aucune organisation n'est clairement identifiable, retourne "null". Il faut analyser bien le contenu pour trouver le nom de l'organisation qui lance ou soutient l'initiative décrite.
- organization_website: Site web de l'organisation (ou null si non trouvé)

Répondez UNIQUEMENT avec le JSON, sans texte supplémentaire.
"""

            headers = {
                'Content-Type': 'application/json',
            }
            
            data = {
                "contents": [{
                    "parts": [{
                        "text": prompt
                    }]
                }]
            }
            
            # Utilisation du nouveau endpoint Gemini 1.5
            url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.gemini_api_key}'
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and len(result['candidates']) > 0:
                    text_response = result['candidates'][0]['content']['parts'][0]['text']
                    
                    # Nettoyer la réponse (enlever ```json si présent)
                    text_response = text_response.strip()
                    if text_response.startswith('```json'):
                        text_response = text_response[7:]
                    if text_response.endswith('```'):
                        text_response = text_response[:-3]
                    
                    try:
                        ai_data = json.loads(text_response)
                        print(f"     IA enrichissement réussi")
                        return ai_data
                    except json.JSONDecodeError as e:
                        print(f"     Erreur JSON IA: {e}")
                        print(f"     Réponse brute: {text_response[:200]}...")
                        return None
                else:
                    print(f"     Pas de réponse IA valide")
                    return None
            elif response.status_code == 404:
                print(f"     Endpoint Gemini non trouvé - Vérifiez votre clé API")
                print(f"     Réponse: {response.text[:200]}...")
                return None
            else:
                print(f"     Erreur API Gemini: {response.status_code}")
                print(f"     Réponse: {response.text[:200]}...")
                return None
                
        except requests.exceptions.Timeout:
            print(f"     Timeout API Gemini - Requête trop longue")
            return None
        except Exception as e:
            print(f"     Erreur enrichissement IA: {e}")
            return None
    
    def parse_opportunities(self, html_content):
        """Parse le HTML pour extraire les opportunités"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Chercher les conteneurs d'opportunités
            opportunity_selectors = [
                '.bordered-list-item.result-item',
                '.result-item',
                'div[class*="result-item"]',
                'article',
                '.card'
            ]
            
            opportunities_found = []
            
            for selector in opportunity_selectors:
                elements = soup.select(selector)
                if elements:
                    print(f" {len(elements)} opportunités trouvées avec: {selector}")
                    opportunities_found = elements
                    break
                else:
                    print(f" Aucun élément trouvé avec: {selector}")
            
            if not opportunities_found:
                print(" Recherche alternative...")
                all_divs = soup.find_all('div')
                for div in all_divs:
                    text = div.get_text(strip=True)
                    if len(text) > 50 and ('apply' in text.lower() or 'program' in text.lower()):
                        opportunities_found.append(div)
                print(f" {len(opportunities_found)} opportunités potentielles trouvées")
            
            # Traiter TOUTES les opportunités trouvées
            max_opportunities = len(opportunities_found)  # Pas de limite
            print(f" Traitement de TOUTES les {max_opportunities} opportunités trouvées")
            
            # Extraire et enrichir chaque opportunité
            for i, element in enumerate(opportunities_found):  # Toutes les opportunités sans limite
                progress = f"{i+1}/{len(opportunities_found)}"
                percentage = int((i+1) / len(opportunities_found) * 100)
                
                print(f"\n Traitement opportunité {progress} ({percentage}%)")
                
                # Extraction basique
                basic_data = self.extract_basic_data(element)
                if not basic_data:
                    print(f"     Opportunité {progress} ignorée (données insuffisantes)")
                    continue
                
                # Récupérer les détails complets
                if basic_data.get('url'):
                    details = self.get_opportunity_details(basic_data['url'])
                    if details:
                        basic_data['subtitle'] = details['subtitle']
                        
                        # Enrichir avec l'IA
                        ai_data = self.enhance_with_gemini(basic_data, details['full_content'])
                        if ai_data:
                            # Fusionner les données
                            final_opportunity = {
                                'url': basic_data['url'],
                                'title': basic_data['title'],
                                'organization_logo': basic_data.get('organization_logo'),
                                'apply_url': basic_data.get('apply_url'),
                                'deadline': basic_data.get('deadline'),
                                **ai_data  # Ajouter toutes les données IA
                            }
                            
                            self.opportunities.append(final_opportunity)
                            print(f"     Opportunité {progress} complète ajoutée")
                        else:
                            print(f"     Opportunité {progress}: Pas d'enrichissement IA, données basiques sauvées")
                            self.opportunities.append(basic_data)
                    else:
                        print(f"     Opportunité {progress}: Pas de détails, données basiques sauvées")
                        self.opportunities.append(basic_data)
                
                # Sauvegarder périodiquement (tous les 20 éléments)
                if (i + 1) % 20 == 0:
                    print(f"     Sauvegarde intermédiaire ({len(self.opportunities)} opportunités)")
                    self.save_results(f"backup_f6s_{i+1}.json")
                
                # Délai minimal pour éviter d'être bloqué
                time.sleep(1)
            
            print(f"\n {len(self.opportunities)} opportunités traitées avec succès")
            
        except Exception as e:
            print(f" Erreur parsing: {e}")
    
    def extract_basic_data(self, element):
        """Extrait les données de base d'une opportunité"""
        try:
            opportunity = {}
            
            # URL de l'opportunité (priorité absolue)
            url_selectors = [
                'a[href*="/environmental-tech-lab"]',
                'a[href*="program"]',
                'a[href*="apply"]',
                '.result-info a',
                'h1 a', 'h2 a', 'h3 a'
            ]
            
            for selector in url_selectors:
                url_elem = element.select_one(selector)
                if url_elem and url_elem.get('href'):
                    href = url_elem.get('href')
                    if href.startswith('/'):
                        href = 'https://www.f6s.com' + href
                    opportunity['url'] = href
                    break
            
            if not opportunity.get('url'):
                return None  # Pas d'URL = pas d'opportunité valide
            
            # Titre
            title_selectors = ['h1', 'h2', 'h3', 'h4', '.title', '[class*="title"]']
            for selector in title_selectors:
                title_elem = element.select_one(selector)
                if title_elem:
                    title_text = title_elem.get_text(strip=True)
                    if title_text and len(title_text) > 3:
                        opportunity['title'] = title_text
                        break
            
            # Logo organisation (seulement src)
            logo_selectors = [
                'img[class*="profile"]',
                'img[src*="profile"]',
                'img[src*="logo"]',
                'img'
            ]
            
            for selector in logo_selectors:
                img_elem = element.select_one(selector)
                if img_elem and img_elem.get('src'):
                    src = img_elem.get('src')
                    if any(keyword in src.lower() for keyword in ['profile', 'logo']):
                        opportunity['organization_logo'] = src
                        break
            
            # Apply URL
            all_links = element.find_all('a', href=True)
            for link in all_links:
                href = link.get('href', '')
                link_text = link.get_text(strip=True).lower()
                if 'apply' in href.lower() or 'apply' in link_text:
                    if href.startswith('/'):
                        href = 'https://www.f6s.com' + href
                    opportunity['apply_url'] = href
                    break
            
            # Deadline
            full_text = element.get_text()
            deadline_patterns = [
                r'by\s+([A-Za-z]+\s+\d{1,2})',
                r'deadline[:\s]+([A-Za-z]+\s+\d{1,2})',
                r'until\s+([A-Za-z]+\s+\d{1,2})'
            ]
            
            for pattern in deadline_patterns:
                match = re.search(pattern, full_text, re.IGNORECASE)
                if match:
                    opportunity['deadline'] = match.group(0).strip()
                    break
            
            return opportunity if opportunity.get('title') else None
            
        except Exception as e:
            print(f" Erreur extraction basique: {e}")
            return None
    
    def scrape_f6s(self, url=None):
        """Lance le scraping complet"""
        print(" DÉBUT DU SCRAPING F6S AVEC IA")
        print("="*50)
        
        # URL par défaut ou depuis config.env
        if not url:
            url = os.getenv('F6S_URL', 'https://www.f6s.com/programs')
        
        print(f" URL cible: {url}")
        
        # Récupérer le contenu principal
        html_content = self.get_page_content(url)
        if not html_content:
            print(" Impossible de récupérer le contenu")
            return
        
        # Parser les opportunités
        self.parse_opportunities(html_content)
        
        # Sauvegarder
        self.save_results()
        self.print_summary()
    
    def save_results(self, filename=None):
        """Sauvegarde les résultats"""
        try:
            if not filename:
                filename = os.getenv('OUTPUT_FILE', 'enhanced_f6s_opportunities.json')
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.opportunities, f, indent=2, ensure_ascii=False)
            print(f"\n {len(self.opportunities)} opportunités sauvegardées dans {filename}")
        except Exception as e:
            print(f" Erreur sauvegarde: {e}")
    
    def print_summary(self):
        """Affiche un résumé"""
        print(f"\n RÉSUMÉ FINAL")
        print(f"{'='*60}")
        print(f"Total opportunités: {len(self.opportunities)}")
        
        if self.opportunities:
            print(f"\n EXEMPLES:")
            for i, opp in enumerate(self.opportunities[:3], 1):
                print(f"\n{i}. {opp.get('title', 'Sans titre')}")
                print(f"   URL: {opp.get('url', 'N/A')}")
                print(f"   Organisation: {opp.get('organization_name', 'N/A')}")
                print(f"   Deadline: {opp.get('deadline', 'N/A')}")
                if opp.get('regions'):
                    print(f"   Régions: {', '.join(opp['regions'][:3])}...")
                if opp.get('sectors'):
                    print(f"   Secteurs: {', '.join(opp['sectors'][:3])}...")

# UTILISATION
if __name__ == "__main__":
    try:
        # Créer le scraper (les clés sont chargées automatiquement depuis config.env)
        scraper = EnhancedF6SScraper()
        
        # Lancer le scraping
        scraper.scrape_f6s()
        
        print("\n Scraping terminé ! Vérifiez le fichier JSON généré.")
        
    except ValueError as e:
        print(f"\n{e}")
        print("\n Vérifiez votre fichier config.env avec vos clés API :")
        print("ZENROWS_API_KEY=votre_cle_zenrows")
        print("GEMINI_API_KEY=votre_cle_gemini")
    except Exception as e:
        print(f"\n Erreur inattendue: {e}")