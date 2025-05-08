from typing import Optional, List, Dict, Any
from datetime import datetime
import json
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

# Singleton Supabase client
_supabase_client = None

def get_supabase():
    """Get or create the Supabase client singleton."""
    global _supabase_client
    if not _supabase_client:
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client

class UserRepository:
    """Handle user-related database operations."""
    
    @staticmethod
    def get_user(discord_id: str) -> Optional[dict]:
        """Get a user by their Discord ID."""
        response = get_supabase().table('users').select("*").eq('discord_id', discord_id).execute()
        return response.data[0] if response.data else None
    
    @staticmethod
    def create_user(discord_id: str, username: str) -> dict:
        """Create a new user."""
        response = get_supabase().table('users').insert({"discord_id": discord_id, "username": username}).execute()
        return response.data[0]
    
    @staticmethod
    def get_all_users() -> List[dict]:
        """Get all users from the database."""
        response = get_supabase().table('users').select("*").execute()
        return response.data

class DeckRepository:
    """Handle deck-related database operations."""
    
    @staticmethod
    def get_user_decks(user_id: int) -> List[dict]:
        """Get all decks for a user."""
        response = get_supabase().table('decks').select("*").eq('user_id', user_id).execute()
        return response.data
    
    @staticmethod
    def get_deck(deck_id: int, user_id: int) -> Optional[dict]:
        """Get a specific deck by ID and user ID."""
        response = get_supabase().table('decks').select("*").eq('id', deck_id).eq('user_id', user_id).execute()
        return response.data[0] if response.data else None
    
    @staticmethod
    def create_deck(user_id: int, name: str, archetype_id: int, decklist: Dict[str, Any]) -> dict:
        """Create a new deck."""
        deck_data = {
            "user_id": user_id,
            "name": name,
            "archetype_id": archetype_id,
            "decklist": json.dumps(decklist)
        }
        response = get_supabase().table('decks').insert(deck_data).execute()
        return response.data[0]
    
    @staticmethod
    def update_deck(deck_id: int, user_id: int, updates: Dict[str, Any]) -> Optional[dict]:
        """Update an existing deck."""
        response = get_supabase().table('decks').update(updates).eq('id', deck_id).eq('user_id', user_id).execute()
        return response.data[0] if response.data else None
    
    @staticmethod
    def get_decks_by_archetype(archetype_id: int) -> List[dict]:
        """Get all decks of a specific archetype."""
        response = get_supabase().table('decks').select("*").eq('archetype_id', archetype_id).execute()
        return response.data

class ArchetypeRepository:
    """Handle archetype-related database operations."""
    
    @staticmethod
    def get_all_archetypes() -> List[dict]:
        """Get all archetypes."""
        response = get_supabase().table('deck_archetypes').select("*").execute()
        return response.data
    
    @staticmethod
    def get_archetype(archetype_id: int) -> Optional[dict]:
        """Get a specific archetype by ID."""
        response = get_supabase().table('deck_archetypes').select("*").eq('id', archetype_id).execute()
        return response.data[0] if response.data else None
    
    @staticmethod
    def create_archetype(name: str, key_cards: str) -> dict:
        """Create a new archetype."""
        response = get_supabase().table('deck_archetypes').insert({
            "name": name,
            "key_cards": ','.join(key_cards)
        }).execute()
        return response.data[0]

class MatchRepository:
    """Handle match-related database operations."""
    
    @staticmethod
    def create_match(deck_id: int, result: str, opponent_archetype: str, player: str, notes: Optional[str] = None) -> dict:
        """Create a new match record."""
        match_data = {
            "deck_id": deck_id,
            "result": result,
            "opponent_archetype": opponent_archetype,
            "player": player,
            "date": datetime.now().strftime('%Y-%m-%d'),
            "notes": notes
        }
        response = get_supabase().table('matches').insert(match_data).execute()
        return response.data[0]
    
    @staticmethod
    def get_matches_by_deck(deck_id: int) -> List[dict]:
        """Get all matches for a specific deck."""
        response = get_supabase().table('matches').select("*").eq('deck_id', deck_id).execute()
        return response.data
    
    @staticmethod
    def get_matches_by_archetype(archetype_id: int) -> List[dict]:
        """Get all matches for decks of a specific archetype."""
        # First get all decks of this archetype
        decks_response = get_supabase().table('decks').select("id").eq('archetype_id', archetype_id).execute()
        deck_ids = [deck['id'] for deck in decks_response.data]
        
        if not deck_ids:
            return []
        
        # Then get all matches for these decks
        matches_response = get_supabase().table('matches').select("*").in_('deck_id', deck_ids).execute()
        return matches_response.data 