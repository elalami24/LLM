#!/usr/bin/env python3
"""
Extracteur de données F6S à partir du HTML récupéré
Analyse et structure les données des programmes
"""

import json
import re
import logging
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
import pandas as pd

# Configuration
OUTPUT_DIR = Path("extracted_data")
LOG_FILE = "extraction.log"

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class F6SDataExtractor:
    def __init__(self, html_content=None, html_file=None):
        """Initialise l'extracteur avec du HTML"""
        self.html_content = html_content
        self.html_file = html_file
        self.soup = None
        self.programs = []
        
        # Créer le dossier de sortie
        OUTPUT_DIR.mkdir(exist_ok=True)
        
        # Charger le HTML
        if html_file and Path(html_file).exists():
            with open(html_file, 'r', encoding='utf-8') as f:
                self.html_content = f.read()
        
        if self.html_content:
            self.soup = BeautifulSoup(self.html_content, 'html.parser')
            logger.info(f"HTML chargé, taille: {len(self.html_content)} caractères")
        else:
            logger.error("Aucun contenu HTML fourni")

    def extract_programs(self):
        """Extrait tous les programmes de la page"""
        if not self.soup:
            logger.error("Aucun contenu HTML à analyser")
            return []
        
        logger.info("Début de l'extraction des programmes...")
        
        # Chercher les éléments de programmes - essayer plusieurs sélecteurs
        program_containers = self.soup.find_all('div', class_='bordered-list-item result-item')
        
        # Si aucun résultat avec ce sélecteur, essayer d'autres variantes
        if not program_containers:
            logger.warning("Aucun programme trouvé avec le sélecteur principal, tentative avec d'autres sélecteurs...")
            program_containers = self.soup.find_all('div', class_='result-item')
            
        if not program_containers:
            program_containers = self.soup.find_all('div', class_='bordered-list-item')
            
        if not program_containers:
            # Essayer de trouver des éléments avec des classes partielles
            program_containers = self.soup.find_all('div', class_=re.compile(r'result.*item'))
        
        logger.info(f"Trouvé {len(program_containers)} conteneurs de programmes")
        
        for i, container in enumerate(program_containers):
            try:
                program = self._extract_single_program(container, i)
                if program and program.get('title'):  # Vérifier que le titre existe
                    self.programs.append(program)
                    logger.debug(f"Programme {i+1} extrait: {program.get('title', 'Sans titre')}")
                else:
                    logger.warning(f"Programme {i+1} ignoré: données incomplètes")
            except Exception as e:
                logger.error(f"Erreur lors de l'extraction du programme {i+1}: {e}")
        
        logger.info(f"Extraction terminée: {len(self.programs)} programmes extraits")
        return self.programs

    def _extract_single_program(self, container, index):
        """Extrait les données d'un seul programme"""
        program = {
            'id': index + 1,
            'title': '',
            'description': '',
            'location': '',
            'deadline': '',
            'date_range': '',
            'apply_url': '',
            'info_url': '',  # Correction: ajout de info_url dans l'initialisation
            'organization_image': '',
            'verified': False,
            'type': '',
            'markets': [],
            'funding_amount': '',  # Correction: ajout des champs manquants
            'equity': '',
            'raw_text': container.get_text(strip=True) if container else ''
        }
        
        try:
            # Extraire le titre
            title_elem = container.find('div', class_='title')
            if title_elem:
                title_link = title_elem.find('a')
                if title_link:
                    program['title'] = title_link.get_text(strip=True)
                    href = title_link.get('href', '')
                    if href:
                        program['info_url'] = href
                    
                    # Vérifier si vérifié
                    if title_elem.find('span', class_='verified-badge'):
                        program['verified'] = True
            
            # Si pas de titre trouvé avec la méthode principale, essayer d'autres sélecteurs
            if not program['title']:
                # Essayer avec d'autres sélecteurs possibles
                title_candidates = [
                    container.find('h3'),
                    container.find('h2'),
                    container.find('a', class_='title'),
                    container.find('div', class_='program-title'),
                    container.find('div', class_='name')
                ]
                
                for candidate in title_candidates:
                    if candidate:
                        program['title'] = candidate.get_text(strip=True)
                        if candidate.get('href'):
                            program['info_url'] = candidate.get('href')
                        break
            
            # Extraire les détails (localisation, dates)
            subtitle_elem = container.find('div', class_='subtitle')
            if subtitle_elem:
                subtitle_text = subtitle_elem.get_text(strip=True)
                
                # Extraire la date et la localisation
                if '•' in subtitle_text:
                    parts = subtitle_text.split('•')
                    if len(parts) >= 2:
                        program['date_range'] = parts[0].strip()
                        program['location'] = parts[1].strip()
                elif subtitle_text:
                    # Si pas de séparateur, c'est probablement juste la localisation
                    program['location'] = subtitle_text
            
            # Extraire la description/détails
            details_elem = container.find('div', class_='details')
            if details_elem:
                details_text = details_elem.get_text(strip=True)
                if details_text:
                    program['description'] = details_text
                    
                    # Extraire les marchés des détails
                    if 'Funds Startups in' in details_text:
                        markets_text = details_text.replace('Funds Startups in', '').strip()
                        if markets_text:
                            program['markets'] = [market.strip() for market in markets_text.split(',') if market.strip()]
            
            # Extraire les informations de financement
            result_extra = container.find('div', class_='result-extra')
            if result_extra:
                # Montant de financement
                funding_spans = result_extra.find_all('span', class_='emphasis')
                for span in funding_spans:
                    text = span.get_text(strip=True)
                    if '$' in text:
                        program['funding_amount'] = text
                    elif '%' in text:
                        program['equity'] = text
            
            # Extraire les URLs d'action
            result_action = container.find('div', class_='result-action')
            if result_action:
                action_links = result_action.find_all('a')
                for link in action_links:
                    href = link.get('href', '')
                    text = link.get_text(strip=True).lower()
                    
                    if 'apply' in text:
                        program['apply_url'] = href
                        program['type'] = 'application'
                    elif 'book' in text:
                        program['apply_url'] = href
                        program['type'] = 'booking'
                    elif 'more info' in text:
                        program['info_url'] = href
            
            # Extraire le deadline depuis le data-overlay
            deadline_elem = container.find('span', class_='data-overlay')
            if deadline_elem:
                deadline_text = deadline_elem.get_text(strip=True)
                if deadline_text.startswith('by'):
                    program['deadline'] = deadline_text
            
            # Extraire l'image de l'organisation
            img_elem = container.find('img', class_='profile')
            if img_elem:
                program['organization_image'] = img_elem.get('src', '')
            
            # Nettoyer les URLs (ajouter le domaine si relatif)
            for url_field in ['apply_url', 'info_url']:  # Correction: 'url' n'existe pas dans program
                if program.get(url_field) and program[url_field].startswith('/'):
                    program[url_field] = 'https://www.f6s.com' + program[url_field]
            
            return program
            
        except Exception as e:
            logger.error(f"Erreur lors de l'extraction détaillée du programme {index+1}: {e}")
            return program

    def extract_page_metadata(self):
        """Extrait les métadonnées de la page"""
        metadata = {
            'extraction_date': datetime.now().isoformat(),
            'page_title': '',
            'page_description': '',
            'total_results': 0,
            'url': '',
            'extraction_method': 'html_parsing'
        }
        
        if not self.soup:
            return metadata
        
        try:
            # Titre de la page
            title_elem = self.soup.find('title')
            if title_elem:
                metadata['page_title'] = title_elem.get_text(strip=True)
            
            # Description
            desc_elem = self.soup.find('meta', attrs={'name': 'description'})
            if desc_elem:
                metadata['page_description'] = desc_elem.get('content', '')
            
            # URL canonique
            canonical_elem = self.soup.find('link', attrs={'rel': 'canonical'})
            if canonical_elem:
                metadata['url'] = canonical_elem.get('href', '')
            
            # Nombre total de résultats (depuis le script)
            script_tags = self.soup.find_all('script')
            for script in script_tags:
                if script.string and 'results' in script.string:
                    # Chercher le pattern "XXXX results"
                    results_match = re.search(r'(\d+)\s+results', script.string)
                    if results_match:
                        metadata['total_results'] = int(results_match.group(1))
                        break
            
        except Exception as e:
            logger.error(f"Erreur lors de l'extraction des métadonnées: {e}")
        
        return metadata

    def save_to_json(self, filename=None):
        """Sauvegarde les données au format JSON"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = OUTPUT_DIR / f"f6s_programs_{timestamp}.json"
        
        data = {
            'metadata': self.extract_page_metadata(),
            'programs': self.programs,
            'summary': {
                'total_extracted': len(self.programs),
                'with_funding': len([p for p in self.programs if p.get('funding_amount')]),
                'verified': len([p for p in self.programs if p.get('verified')]),
                'with_deadline': len([p for p in self.programs if p.get('deadline')]),
                'locations': list(set([p.get('location') for p in self.programs if p.get('location')])),
                'markets': list(set([market for p in self.programs for market in p.get('markets', [])]))
            }
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Données sauvegardées dans {filename}")
        return filename

    def save_to_csv(self, filename=None):
        """Sauvegarde les données au format CSV"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = OUTPUT_DIR / f"f6s_programs_{timestamp}.csv"
        
        if not self.programs:
            logger.warning("Aucun programme à sauvegarder")
            return None
        
        # Préparer les données pour CSV
        csv_data = []
        for program in self.programs:
            row = program.copy()
            # Convertir les listes en chaînes
            row['markets'] = '; '.join(program.get('markets', []))
            csv_data.append(row)
        
        # Créer le DataFrame et sauvegarder
        df = pd.DataFrame(csv_data)
        df.to_csv(filename, index=False, encoding='utf-8')
        
        logger.info(f"Données CSV sauvegardées dans {filename}")
        return filename

    def generate_report(self):
        """Génère un rapport d'extraction"""
        if not self.programs:
            return "Aucun programme extrait"
        
        report = []
        report.append("="*60)
        report.append("RAPPORT D'EXTRACTION F6S")
        report.append("="*60)
        report.append(f"Date d'extraction: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"Nombre total de programmes: {len(self.programs)}")
        report.append("")
        
        # Statistiques
        with_funding = [p for p in self.programs if p.get('funding_amount')]
        verified = [p for p in self.programs if p.get('verified')]
        with_deadline = [p for p in self.programs if p.get('deadline')]
        
        report.append("STATISTIQUES:")
        report.append(f"- Programmes avec financement: {len(with_funding)}")
        report.append(f"- Programmes vérifiés: {len(verified)}")
        report.append(f"- Programmes avec deadline: {len(with_deadline)}")
        report.append("")
        
        # Échantillon des programmes
        report.append("ÉCHANTILLON DES PROGRAMMES:")
        report.append("-" * 40)
        
        for i, program in enumerate(self.programs[:10]):  # Premiers 10
            report.append(f"\n{i+1}. {program.get('title', 'Sans titre')}")
            if program.get('location'):
                report.append(f"    Localisation: {program['location']}")
            if program.get('funding_amount'):
                report.append(f"    Financement: {program['funding_amount']}")
            if program.get('deadline'):
                report.append(f"    Deadline: {program['deadline']}")
            if program.get('verified'):
                report.append(f"    ✓ Vérifié")
        
        if len(self.programs) > 10:
            report.append(f"\n... et {len(self.programs) - 10} autres programmes")
        
        return "\n".join(report)

def main():
    """Fonction principale pour tester l'extraction"""
    print("EXTRACTEUR DE DONNÉES F6S")
    print("="*50)
    
    # Exemple d'utilisation
    html_file = input("Entrez le chemin du fichier HTML (ou appuyez sur Entrée pour utiliser l'exemple): ").strip()
    
    if not html_file:
        print(" Aucun fichier HTML fourni. Veuillez spécifier un fichier HTML valide.")
        return
    else:
        if not Path(html_file).exists():
            print(f" Fichier non trouvé: {html_file}")
            return
        extractor = F6SDataExtractor(html_file=html_file)
    
    # Extraire les programmes
    programs = extractor.extract_programs()
    
    if not programs:
        print(" Aucun programme extrait")
        return
    
    # Sauvegarder les données
    json_file = extractor.save_to_json()
    csv_file = extractor.save_to_csv()
    
    # Générer et afficher le rapport
    report = extractor.generate_report()
    print("\n" + report)
    
    # Sauvegarder le rapport
    report_file = OUTPUT_DIR / f"extraction_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n Fichiers générés:")
    print(f"   - JSON: {json_file}")
    print(f"   - CSV: {csv_file}")
    print(f"   - Rapport: {report_file}")

if __name__ == "__main__":
    main()