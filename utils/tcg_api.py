import os
import requests
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv
import re
import shutil
from pathlib import Path

load_dotenv()

SETCODE_MAP = None

def load_setcode_map() -> Dict[str, str]:
    """Load set code mappings from assets/setcodes.txt."""
    mapping = {}
    setcodes_path = os.path.join(os.path.dirname(__file__), '../assets/setcodes.txt')
    try:
        with open(setcodes_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or '(' not in line or ')' not in line:
                    continue
                
                # Parse the new format: "Set Name (CODE) - setid"
                parts = line.split(' - ')
                if len(parts) != 2:
                    continue
                    
                name_code_part = parts[0].strip()
                set_id = parts[1].strip()
                
                # Extract name and code from "Set Name (CODE)"
                match = re.match(r'(.+)\s+\(([^)]+)\)', name_code_part)
                if not match:
                    continue
                    
                name, code = match.groups()
                name = name.strip()
                code = code.upper()
                
                # Map in both directions
                mapping[code] = set_id  # Map 3-letter code to official set ID
                mapping[name.lower()] = set_id  # Map set name to official set ID
                mapping[set_id] = name  # Map official set ID to set name
                
                # Add special subset mappings with proper set ID suffixes
                if code == "CRZ":  # Crown Zenith - Needed for testing/standard set cards
                    mapping["CRZ-GG"] = f"{set_id}gg"  # Galarian Gallery
                elif code == "SHF":  # Shining Fates -  This most likely is not needed as these cards were not standard set cards
                    mapping["SHF-SV"] = f"{set_id}sv"  # Shining Vault
                elif code == "HIF":  # Hidden Fates -  This most likely is not needed as these cards were not standard set cards
                    mapping["HIF-SV"] = f"{set_id}sv"  # Shining Vault
                # Trainer Gallery
                if code == "LOR":
                    mapping["LOR-TG"] = f"{set_id}tg"  # Lost Origin
                elif code == "BRS":
                    mapping["BRS-TG"] = f"{set_id}tg"  # Brilliant Stars
                elif code == "ASR":
                    mapping["ASR-TG"] = f"{set_id}tg"  # Astral Radiance
                elif code == "SIT":
                    mapping["SIT-TG"] = f"{set_id}tg"  # Silver Tempest
                    
    except Exception as e:
        print(f"Error loading setcodes.txt: {e}")
    return mapping

class TCGApi:
    BASE_URL = "https://api.pokemontcg.io/v2"
    API_KEY = os.getenv("POKEMON_TCG_API_KEY")

    @classmethod
    def get_card_by_name(
        cls, card_name: str, set_code: Optional[str] = None, number: Optional[str] = None
    ) -> Optional[Dict]:
        """Fetch card data by name, optionally set code and number, from the Pokémon TCG API."""
        global SETCODE_MAP
        if SETCODE_MAP is None:
            SETCODE_MAP = load_setcode_map()
            
        headers = {"X-Api-Key": cls.API_KEY} if cls.API_KEY else {}
        api_set_code = None
        api_number = number
        
        if set_code:
            # Try to map user set code to official set ID
            api_set_code = SETCODE_MAP.get(set_code.upper(), set_code)
            # Special handling for Galarian Gallery (CRZ-GG)
            if set_code.upper() == "CRZ-GG" and number and not number.upper().startswith("GG"):
                api_number = f"GG{number}"
            # Special handling for Trainer Gallery (TG) subsets
            if set_code.upper().endswith("-TG") and number:
                # Pad number to two digits and prefix with TG if not already
                if not number.upper().startswith("TG"):
                    api_number = f"TG{int(number):02d}"
        
        if api_set_code and api_number:
            params = {"q": f'name:"{card_name}" set.id:"{api_set_code}" number:"{api_number}"'}
        else:
            params = {"q": f'name:"{card_name}"'}
            
        try:
            response = requests.get(f"{cls.BASE_URL}/cards", headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            if data["data"]:
                return data["data"][0]
            # Fallback: try by name only if set/number not found
            if api_set_code and api_number:
                params = {"q": f'name:"{card_name}"'}
                response = requests.get(f"{cls.BASE_URL}/cards", headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                if data["data"]:
                    return data["data"][0]
            return None
        except Exception as e:
            print(f"Error fetching card {card_name}: {str(e)}")
            return None

    @classmethod
    def is_basic_pokemon(cls, card_data: Dict) -> bool:
        """Check if a card is a Basic Pokémon."""
        return (
            card_data.get("supertype") == "Pokémon" and
            "Basic" in card_data.get("subtypes", [])
        )

    @classmethod
    def get_card_image_url(cls, card_data: Dict) -> Optional[str]:
        """Get the image URL for a card."""
        if not card_data:
            return None
            
        # Handle basic energy cards
        if card_data.get("supertype") == "Energy" and "Basic" in card_data.get("subtypes", []):
            return card_data.get("images", {}).get("large")
            
        return card_data.get("images", {}).get("large")

    @classmethod
    def get_cards_by_names(
        cls, card_names: List[str]
    ) -> List[Tuple[str, Optional[Dict]]]:
        """Fetch multiple cards by name and return (card_name, card_data) pairs.
        card_names can be tuples (name, set_code, number) or just names.
        """
        results = []
        for entry in card_names:
            if isinstance(entry, tuple):
                name, set_code, number = entry
                card_data = cls.get_card_by_name(name, set_code, number)
                results.append((name, card_data))
            else:
                card_data = cls.get_card_by_name(entry)
                results.append((entry, card_data))
        return results

    @staticmethod
    def parse_card_line(card_line: str) -> Tuple[str, Optional[str], Optional[str]]:
        """Parse a card line to extract name, set code, and number."""
        # Remove count at the start
        match = re.match(r'^\s*(\d+)\s+(.+)$', card_line.strip())
        if not match:
            return card_line.strip(), None, None
        full_name = match.group(2).strip()

        # Normalize basic energy cards: only keep 'Basic [Type] Energy'
        if "Basic" in full_name and "Energy" in full_name:
            words = full_name.split()
            try:
                basic_idx = words.index("Basic")
                energy_idx = words.index("Energy", basic_idx)
                # Only keep from 'Basic' to 'Energy' (inclusive)
                normalized_name = " ".join(words[basic_idx:energy_idx+1])
                return normalized_name, None, None
            except ValueError:
                pass

        # Try to extract set code and number at the end
        set_match = re.search(r'(.+?)\s+([A-Z]+(?:-[A-Z]+)?)\s+(\d+)(?:\s|$)', full_name)
        if set_match:
            name = set_match.group(1).strip()
            set_code = set_match.group(2).strip()
            number = set_match.group(3).strip()
            return name, set_code, number
        return full_name, None, None 