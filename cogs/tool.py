import discord
from discord.ext import commands
import random
import json
from typing import List, Tuple, Optional
import re

from database.supabase import UserRepository, DeckRepository, ArchetypeRepository
from utils.tcg_api import TCGApi
from utils.image_builder import ImageBuilder

class ToolCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group()
    async def tool(self, ctx):
        """Tool commands for Pokémon TCG utilities."""
        if ctx.invoked_subcommand is None:
            await ctx.send('Please specify a subcommand for tool, e.g., "!tool mully".')

    @tool.command(name='mully')
    async def mully(self, ctx):
        """Simulate opening hands for a deck."""
        # Check if user is registered
        discord_id = str(ctx.author.id)
        user = UserRepository.get_user(discord_id)
        if not user:
            await ctx.send('You need to register first.')
            return

        # Get user's decks using their user_id
        decks = DeckRepository.get_user_decks(user['id'])
        if not decks:
            await ctx.send('You have no saved decks.')
            return

        # Format deck list with archetypes
        deck_list = []
        for deck in decks:
            archetype = ArchetypeRepository.get_archetype(deck['archetype_id'])
            archetype_name = archetype['name'] if archetype else "Unknown"
            deck_list.append(f"{deck['id']}: {deck['name']} [{archetype_name}]")

        # Send formatted deck list
        deck_list_text = "\n".join(deck_list)
        await ctx.send(f"Please enter the deck ID number:\n```\n{deck_list_text}\n```")

        def check(msg):
            return msg.author == ctx.author and msg.channel == ctx.channel and msg.content.isdigit()

        try:
            # Wait for user to input deck ID
            msg = await self.bot.wait_for('message', check=check, timeout=60.0)
            deck_id = int(msg.content)
        except TimeoutError:
            await ctx.send("You took too long to respond. Please try again.")
            return

        # Find the specified deck
        deck = next((d for d in decks if d['id'] == deck_id), None)
        if not deck:
            await ctx.send('Deck not found.')
            return

        # Parse decklist
        try:
            deck_data = json.loads(deck['decklist'])
            cards = []
            card_entries = []  # For (name, set_code, number)
            # Energy symbol mapping
            energy_map = {
                '{D}': 'Darkness', '{F}': 'Fighting', '{P}': 'Psychic', '{W}': 'Water', '{G}': 'Grass',
                '{L}': 'Lightning', '{M}': 'Metal', '{R}': 'Fire'
            }
            # Process each card line
            for card_line in deck_data['cards']:
                # Skip empty lines or section headers
                if not card_line.strip() or ':' in card_line:
                    continue
                # Use regex to find the count at the start of the line
                match = re.match(r'^\s*(\d+)\s+(.+)$', card_line.strip())
                if match:
                    count = int(match.group(1))
                    # Extract just the card name without set code and number
                    full_name = match.group(2).strip()
                    # Replace energy symbol with full name
                    for symbol, full in energy_map.items():
                        if symbol in full_name:
                            full_name = full_name.replace(symbol, full)
                    # Parse for set code and number
                    name, set_code, number = TCGApi.parse_card_line(f"1 {full_name}")
                    for _ in range(count):
                        cards.append(name)
                        card_entries.append((name, set_code, number))
        except Exception as e:
            await ctx.send(f'Error parsing decklist: {str(e)}')
            return

        if not cards:
            await ctx.send('No valid cards found in the decklist.')
            return

        # Simulate mulligans
        mulligans = 0
        while True:
            # Shuffle and draw 7 cards
            random.shuffle(card_entries)
            hand_entries = card_entries[:7]
            hand = [entry[0] for entry in hand_entries]
            # Check for Basic Pokémon
            hand_cards = TCGApi.get_cards_by_names(hand_entries)
            hand_basics = [
                card_data and card_data.get('supertype') == 'Pokémon' and 'Basic' in card_data.get('subtypes', [])
                for _, card_data in hand_cards
            ]
            has_basic = any(hand_basics)
            
            if has_basic:
                break
            
            mulligans += 1
            if mulligans > 10:  # Safety limit
                await ctx.send("Too many mulligans! Something might be wrong with the deck.")
                return
            else:
                hand_urls = [TCGApi.get_card_image_url(card_data) for _, card_data in hand_cards if card_data]
                image = ImageBuilder.create_hand_image(hand_urls, [], 0, hand_basics)
                if image:
                    img_bytes = ImageBuilder.save_to_bytes(image)
                    await ctx.send(
                        f"Mulligan {mulligans} was done. Setting up again. These were your 7 cards:",
                        file=discord.File(img_bytes, f'mulligan_{mulligans}.png')
                    )
                else:
                    await ctx.send(f"Mulligan {mulligans} was done. (Could not generate image)")

        # Draw 6 prize cards
        prize_entries = card_entries[7:13]
        prize_cards = [entry[0] for entry in prize_entries]
        prize_card_data = TCGApi.get_cards_by_names(prize_entries)

        # Get image URLs or card names for placeholders, always 6
        missing_cards = []
        prize_urls = []
        for i, (card_name, card_data) in enumerate(prize_card_data):
            if card_data:
                url = TCGApi.get_card_image_url(card_data)
                prize_urls.append(url if url else card_name)
                if not url:
                    missing_cards.append(card_name)
            else:
                prize_urls.append(card_name)
                missing_cards.append(card_name)
        while len(prize_urls) < 6:
            prize_urls.append('Unknown')

        # Get hand image URLs (show card name if not found)
        hand_urls = []
        for card_name, card_data in hand_cards:
            if card_data:
                url = TCGApi.get_card_image_url(card_data)
                hand_urls.append(url if url else card_name)
                if not url:
                    missing_cards.append(card_name)
            else:
                hand_urls.append(card_name)
                missing_cards.append(card_name)

        # Notify user of missing cards
        if missing_cards:
            unique_missing = list(set(missing_cards))
            await ctx.send(f"The following cards could not be found in the database and will be shown as text placeholders: {', '.join(unique_missing)}")

        # Create and send image
        image = ImageBuilder.create_hand_image(hand_urls, prize_urls, mulligans, hand_basics)
        if image:
            img_bytes = ImageBuilder.save_to_bytes(image)
            await ctx.send(
                f"Starting hand and prize cards. Took {mulligans} mulligan(s).",
                file=discord.File(img_bytes, 'hand.png')
            )
        else:
            await ctx.send("Error creating image. Please try again.")

async def setup(bot):
    await bot.add_cog(ToolCommands(bot)) 