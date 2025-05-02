import re
from typing import List

def normalize_text(text: str) -> str:
    """
    Normalize card names by:
    - Converting to lowercase
    - Removing set codes (any extra words after the first two)
    - Stripping extra spaces
    """
    text = text.lower().strip()
    words = text.split()
    return words[0] if words else ""

def extract_card_names(deck_content: str) -> List[str]:
    """
    Extract full Pokémon card names while ignoring set codes.
    Example input: "1 Roaring Moon ex PRE 162"
    Returns: ["roaring"]
    """
    matches = re.findall(r'\d+\s+([A-Za-z\s-]+?)(?:\s+\w+\s*\d+)?$', deck_content, re.MULTILINE)
    return [normalize_text(match) for match in matches]

def identify_archetype(cards: List[str], archetypes: List[dict]) -> str:
    """
    Identify the deck archetype based on the cards and known archetypes.
    Returns "Others" if no matching archetype is found.
    """
    for archetype in archetypes:
        archetype_cards = [normalize_text(card.strip()) for card in archetype['key_cards'].split(',')]
        match_count = sum(1 for ac in archetype_cards if ac in cards)
        
        if match_count >= 3:
            return archetype['name']
    
    return "Others"

def format_decklist(deck_data: dict) -> str:
    """
    Format a deck data dictionary into a readable string.
    """
    response = f"📜 **{deck_data['name']}** - {deck_data['archetype']} 📜\n"
    response += f"🕒 Last Modified: {deck_data['last_modified']}\n"
    response += "```" + "\n".join(deck_data["cards"]) + "```"
    return response 