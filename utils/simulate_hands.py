import random
from collections import Counter
from typing import List, Dict, Tuple, Optional
import json
from utils.tcg_api import TCGApi
from utils.image_builder import ImageBuilder
import io
from PIL import Image
import requests

class HandSimulator:
    def __init__(self, decklist: List[Tuple[str, Optional[str], Optional[str]]], tcg_api: TCGApi, archetype_name: Optional[str] = None):
        """
        Initialize the simulator with a decklist.
        Each card in decklist should be a tuple of (name, set_code, number)
        archetype_name: Optional name of the deck's archetype (e.g., "Roaring Moon ex")
        """
        if not decklist:
            raise ValueError("Decklist cannot be empty")
            
        self.decklist = decklist
        self.tcg_api = tcg_api
        self.archetype_name = archetype_name
        self.ctx = None  # Will store Discord context for progress updates
        
        # Pre-process decklist to identify basic Pokémon
        self.basic_pokemon = set()
        unique_cards = set((card[0], card[1], card[2]) for card in decklist)  # Get unique cards
        
        # Do one API call per unique card to identify Basic Pokémon
        for name, set_code, number in unique_cards:
            try:
                # Convert Poke to Poké for API lookup
                api_name = name.replace('Poke', 'Poké')
                card_data = self.tcg_api.get_card_by_name(api_name, set_code, number)
                if card_data and card_data.get('supertype') == 'Pokémon' and 'Basic' in card_data.get('subtypes', []):
                    self.basic_pokemon.add(name)
            except Exception as e:
                print(f"Error checking if {name} is a Basic Pokémon: {e}")
                # If we can't verify, assume it's not a Basic Pokémon
                continue

        if not self.basic_pokemon:
            raise ValueError("No Basic Pokémon found in decklist. Please ensure your deck contains Basic Pokémon.")

    def set_context(self, ctx):
        """Set the Discord context for progress updates."""
        self.ctx = ctx

    async def send_progress(self, current: int, total: int):
        """Send a progress update to the user."""
        if self.ctx:
            progress = current / total
            bar_length = 20
            filled_length = int(bar_length * progress)
            bar = '█' * filled_length + '░' * (bar_length - filled_length)
            percentage = int(progress * 100)
            await self.ctx.send(f"Simulating hands... [{bar}] {percentage}% ({current}/{total})")

    def shuffle_deck(self) -> List[Tuple[str, Optional[str], Optional[str]]]:
        """Shuffle the deck and return a copy."""
        if not self.decklist:
            raise ValueError("Cannot shuffle empty decklist")
        deck_copy = self.decklist.copy()
        random.shuffle(deck_copy)
        return deck_copy

    def draw_cards(self, deck: List[Tuple[str, Optional[str], Optional[str]]], count: int) -> Tuple[List[Tuple[str, Optional[str], Optional[str]]], List[Tuple[str, Optional[str], Optional[str]]]]:
        """Draw n cards from the deck and return (drawn_cards, remaining_deck)."""
        drawn = deck[:count]
        remaining = deck[count:]
        return drawn, remaining

    def has_basic_pokemon(self, cards: List[Tuple[str, Optional[str], Optional[str]]]) -> bool:
        """Check if any of the drawn cards is a Basic Pokémon using our pre-computed set."""
        return any(card[0] in self.basic_pokemon for card in cards)

    def simulate_hand(self) -> Dict:
        """Simulate one complete hand setup."""
        try:
            deck = self.shuffle_deck()
            mulligans = 0
            
            # Setup hand (7 cards)
            while True:
                setup_hand, deck = self.draw_cards(deck, 7)
                if self.has_basic_pokemon(setup_hand):
                    break
                mulligans += 1
                if mulligans > 10:  # Safety limit
                    raise ValueError("Too many mulligans - deck may not have enough basic Pokémon")
                deck = self.shuffle_deck()
            
            # Prize cards (6 cards)
            prize_cards, deck = self.draw_cards(deck, 6)
            
            # Draw for turn (1 card)
            draw_for_turn, deck = self.draw_cards(deck, 1)

            # Squak/Iono draw (6 cards)
            squak_draw, deck = self.draw_cards(deck, 6)

            # Professor Research draw (1 card)
            prof_draw, _ = self.draw_cards(deck, 1)
            
            return {
                'mulligans': mulligans,
                'setup_hand': setup_hand,
                'prize_cards': prize_cards,
                'draw_for_turn': draw_for_turn,
                'squak_draw': squak_draw,
                'prof_draw': prof_draw
            }
        except Exception as e:
            print(f"Error in simulate_hand: {e}")
            raise

    async def run_simulations(self, num_simulations: int) -> Dict:
        """Run multiple simulations and aggregate results."""
        if num_simulations <= 0:
            raise ValueError("Number of simulations must be positive")
            
        total_mulligans = 0
        games_with_mulligan = 0
        card_appearances = {
            "setup_hand": Counter(),
            "prize_cards": Counter(),
            "draw_for_turn": Counter(),
            "squak_draw": Counter(),
            "prof_draw": Counter()
        }
        
        # Send initial progress message
        await self.send_progress(0, num_simulations)
        
        try:
            for i in range(num_simulations):
                sim_result = self.simulate_hand()
                total_mulligans += sim_result["mulligans"]
                if sim_result["mulligans"] > 0:
                    games_with_mulligan += 1
                
                # Update card appearances
                for category in card_appearances:
                    card_appearances[category].update(card[0] for card in sim_result[category])
                
                # Send progress update every 100 simulations or on the last one
                if (i + 1) % 100 == 0 or i == num_simulations - 1:
                    await self.send_progress(i + 1, num_simulations)
            
            return {
                "total_simulations": num_simulations,
                "total_mulligans": total_mulligans,
                "games_with_mulligan": games_with_mulligan,
                "card_appearances": card_appearances
            }
        except Exception as e:
            print(f"Error in run_simulations: {e}")
            raise

    def generate_report(self, results: Dict, top_n: int = 10, deck_name: str = None) -> Tuple[str, Optional[Image.Image]]:
        """Generate a formatted report of the simulation results.
        Returns a tuple of (report_text, archetype_image)"""
        report = []
        report.append(f"=== Pokémon TCG Hand Simulation Report ===")
        if self.archetype_name:
            report.append(f"Archetype: {self.archetype_name}")
        if deck_name:
            report.append(f"Deck: {deck_name}")
        report.append(f"Total Simulations: {results['total_simulations']}")
        # Show Mulligan Rate as a percentage
        mulligan_rate = (results.get('games_with_mulligan', 0) / results['total_simulations']) * 100
        report.append(f"Mulligan Rate: {mulligan_rate:.1f}%")
        
        # Helper function to format card frequency
        def format_card_freq(counter: Counter, title: str):
            report.append(f"\n{title}:")
            for card, count in counter.most_common(top_n):
                percentage = (count / results['total_simulations']) * 100
                report.append(f"{card}: {count} times ({percentage:.1f}%)")
        
        format_card_freq(results['card_appearances']['setup_hand'], 'Setup Hand')
        format_card_freq(results['card_appearances']['prize_cards'], 'Prize Cards')
        format_card_freq(results['card_appearances']['draw_for_turn'], 'Draw for Turn')
        format_card_freq(results['card_appearances']['squak_draw'], 'Squawkabilly/Iono Draw')
        format_card_freq(results['card_appearances']['prof_draw'], 'Draw 1 if You Used Professor Research')
        
        # Get archetype image if available
        archetype_image = None
        if self.archetype_name:
            card_data = self.tcg_api.get_card_by_name(self.archetype_name)
            if card_data:
                image_url = self.tcg_api.get_card_image_url(card_data)
                if image_url:
                    try:
                        response = requests.get(image_url)
                        if response.status_code == 200:
                            archetype_image = Image.open(io.BytesIO(response.content))
                            archetype_image = archetype_image.resize((100, 140))
                    except Exception as e:
                        print(f"Error loading archetype image: {e}")
        return "\n".join(report), archetype_image 