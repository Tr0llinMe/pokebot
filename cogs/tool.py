import discord
from discord.ext import commands
import random
import json
from typing import List, Tuple, Optional
import re
from PIL import Image, ImageDraw, ImageFont
import os
import asyncio
import requests
import io

from database.supabase import UserRepository, DeckRepository, ArchetypeRepository
from utils.tcg_api import TCGApi
from utils.image_builder import ImageBuilder
from utils.simulate_hands import HandSimulator
from utils.image import get_sprite

# Add mapping for energy symbols to names (global)
energy_symbol_map = {
    '{R}': 'Fire', '{W}': 'Water', '{G}': 'Grass', '{L}': 'Lightning', '{P}': 'Psychic', '{F}': 'Fighting', '{M}': 'Metal', '{D}': 'Darkness', '{Y}': 'Fairy'
}

class ToolCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_repo = UserRepository()
        self.deck_repo = DeckRepository()
        self.archetype_repo = ArchetypeRepository()
        self.tcg_api = TCGApi()
        self.image_builder = ImageBuilder()

    @commands.group()
    async def tool(self, ctx):
        """Tool commands for Pokémon TCG utilities."""
        if ctx.invoked_subcommand is None:
            await ctx.send('Please specify a subcommand for tool, e.g., "!tool mully".')

    @tool.command(name='mully')
    async def mully(self, ctx):
        """Simulate a single opening hand for a deck, using the modular HandSimulator."""
        # Check if user is registered
        discord_id = str(ctx.author.id)
        user = self.user_repo.get_user(discord_id)
        if not user:
            await ctx.send('You need to register first.')
            return

        # Get user's decks using their user_id
        decks = self.deck_repo.get_user_decks(user['id'])
        if not decks:
            await ctx.send('You have no saved decks.')
            return

        # Format deck list with archetypes
        deck_list = []
        for deck in decks:
            archetype = self.archetype_repo.get_archetype(deck['archetype_id'])
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
        except Exception:
            await ctx.send("You took too long to respond or input was invalid. Please try again.")
            return

        # Find the specified deck
        deck = next((d for d in decks if d['id'] == deck_id), None)
        if not deck:
            await ctx.send('Deck not found.')
            return

        # Parse decklist
        try:
            deck_data = json.loads(deck['decklist'])
            card_entries = []
            # Process each card line
            for card_line in deck_data['cards']:
                # Skip empty lines or section headers
                if not card_line.strip() or ':' in card_line:
                    continue
                # Use regex to find the count at the start of the line
                match = re.match(r'^\s*(\d+)\s+(.+)$', card_line.strip())
                if match:
                    count = int(match.group(1))
                    card_name = match.group(2).strip()
                    # Convert Poké to Poke for storage
                    card_name = card_name.replace('Poké', 'Poke')
                    # Parse for set code and number
                    name, set_code, number = self.tcg_api.parse_card_line(f"1 {card_name}")
                    if name:
                        for _ in range(count):
                            card_entries.append((name, set_code, number))
            if not card_entries:
                await ctx.send('No valid cards found in the decklist.')
                return
        except Exception as e:
            await ctx.send(f'Error parsing decklist: {str(e)}')
            return

        # Simulate a single hand using HandSimulator
        try:
            simulator = HandSimulator(card_entries, self.tcg_api)
            simulator.set_context(ctx)
            sim_result = simulator.simulate_hand()
            mulligans = sim_result['mulligans']
            setup_hand = sim_result['setup_hand']
            prize_cards = sim_result['prize_cards']

            # Get card images for hand and prize cards, using normalization for basic energies and Poké
            hand_urls = []
            for name, set_code, number in setup_hand:
                card_data = None
                display_name = name.replace('Poke', 'Poké')
                # Handle basic energy normalization
                if name.startswith('Basic') and 'Energy' in name:
                    match = re.match(r'Basic \{([A-Z])\} Energy', name)
                    if match:
                        symbol = '{' + match.group(1) + '}'
                        energy_type = energy_symbol_map.get(symbol, None)
                        if energy_type:
                            normalized_name = f'Basic {energy_type} Energy'
                            card_data = self.tcg_api.get_card_by_name(normalized_name)
                            display_name = normalized_name
                        else:
                            # Symbol not found, fallback to original name
                            card_data = self.tcg_api.get_card_by_name(name)
                            display_name = name
                    else:
                        card_data = self.tcg_api.get_card_by_name(name)
                        display_name = name
                else:
                    api_name = name.replace('Poke', 'Poké')
                    card_data = self.tcg_api.get_card_by_name(api_name, set_code, number)
                    # If not found, try API lookup with normalized name only
                    if not card_data:
                        card_data = self.tcg_api.get_card_by_name(api_name)
                url = self.tcg_api.get_card_image_url(card_data) if card_data else None
                hand_urls.append(url if url else display_name)
            prize_urls = []
            for name, set_code, number in prize_cards:
                card_data = None
                display_name = name.replace('Poke', 'Poké')
                if name.startswith('Basic') and 'Energy' in name:
                    match = re.match(r'Basic \{([A-Z])\} Energy', name)
                    if match:
                        symbol = '{' + match.group(1) + '}'
                        energy_type = energy_symbol_map.get(symbol, None)
                        if energy_type:
                            normalized_name = f'Basic {energy_type} Energy'
                            card_data = self.tcg_api.get_card_by_name(normalized_name)
                            display_name = normalized_name
                        else:
                            card_data = self.tcg_api.get_card_by_name(name)
                            display_name = name
                    else:
                        card_data = self.tcg_api.get_card_by_name(name)
                        display_name = name
                else:
                    api_name = name.replace('Poke', 'Poké')
                    card_data = self.tcg_api.get_card_by_name(api_name, set_code, number)
                    if not card_data:
                        card_data = self.tcg_api.get_card_by_name(api_name)
                url = self.tcg_api.get_card_image_url(card_data) if card_data else None
                prize_urls.append(url if url else display_name)
            # Create and send image
            image = ImageBuilder.create_hand_image(hand_urls, prize_urls, mulligans, [name in simulator.basic_pokemon for name, _, _ in setup_hand])
            if image:
                img_bytes = ImageBuilder.save_to_bytes(image)
                await ctx.send(
                    f"Starting hand and prize cards. Took {mulligans} mulligan(s).",
                    file=discord.File(img_bytes, 'hand.png')
                )
            else:
                await ctx.send(f"Starting hand and prize cards. Took {mulligans} mulligan(s). (Could not generate image)")
        except Exception as e:
            await ctx.send(f"Error simulating hand: {str(e)}")

    @tool.command(name="testhands")
    async def test_hands(self, ctx):
        """Simulate opening hands for a deck."""
        # Check if user is registered
        discord_id = str(ctx.author.id)
        user = self.user_repo.get_user(discord_id)
        if not user:
            await ctx.send("You need to register first! Use `!register` to create an account.")
            return

        # Get user's saved decks
        decks = self.deck_repo.get_user_decks(user['id'])
        if not decks:
            await ctx.send("You don't have any saved decks! Use `!deck add` to add a deck first.")
            return

        # Format deck list
        deck_list = "Your saved decks:\n"
        for deck in sorted(decks, key=lambda d: d['id']):
            archetype = self.archetype_repo.get_archetype(deck['archetype_id'])
            archetype_name = archetype['name'] if archetype else "Unknown"
            deck_list += f"{deck['id']}: {deck['name']} [{archetype_name}]\n"

        # Send deck list and ask for selection
        await ctx.send(deck_list + "\nPlease select a deck by ID:")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=30.0)
            deck_id = int(msg.content.strip())
        except (ValueError, asyncio.TimeoutError):
            await ctx.send("Invalid selection or timeout. Please try again.")
            return

        # Get selected deck
        deck = next((d for d in decks if d['id'] == deck_id), None)
        if not deck:
            await ctx.send("Invalid deck selection. Please try again.")
            return

        # Parse decklist
        try:
            deck_data = json.loads(deck['decklist'])
            card_entries = []
            
            # Process each card line
            for card_line in deck_data['cards']:
                # Skip empty lines or section headers
                if not card_line.strip() or ':' in card_line:
                    continue
                    
                # Use regex to find the count at the start of the line
                match = re.match(r'^\s*(\d+)\s+(.+)$', card_line.strip())
                if match:
                    count = int(match.group(1))
                    card_name = match.group(2).strip()
                    
                    # Convert Poké to Poke for storage
                    card_name = card_name.replace('Poké', 'Poke')
                    
                    # Parse for set code and number
                    name, set_code, number = self.tcg_api.parse_card_line(f"1 {card_name}")
                    if name:  # Only add if we got a valid card name
                        for _ in range(count):
                            card_entries.append((name, set_code, number))
            
            if not card_entries:
                await ctx.send("No valid cards found in the decklist.")
                return
                
        except json.JSONDecodeError:
            await ctx.send("Error: Invalid decklist format.")
            return
        except Exception as e:
            await ctx.send(f"Error parsing decklist: {str(e)}")
            return

        # Create simulator and run simulations
        try:
            simulator = HandSimulator(card_entries, self.tcg_api)
            simulator.deck_name = deck['name']
            simulator.set_context(ctx)  # Set context for progress updates
            
            # Get archetype name and sprite for the report
            archetype = self.archetype_repo.get_archetype(deck['archetype_id'])
            archetype_image = None
            if archetype:
                simulator.archetype_name = archetype['name']
                # Get the archetype's sprite using the get_sprite function
                try:
                    archetype_image = get_sprite(archetype['name'])
                    # Resize to a reasonable size for the report
                    archetype_image = archetype_image.resize((100, 100))
                except Exception as e:
                    print(f"Error loading archetype sprite: {e}")

            # Run simulations with progress updates
            results = await simulator.run_simulations(1000)  # Run 1000 simulations

            # Generate and send main report image (setup hand, prize cards, draw for turn)
            report_text, _ = simulator.generate_report(results, deck_name=deck['name'])  # Pass deck name
            # Main simulation categories
            main_categories = ["setup_hand", "prize_cards", "draw_for_turn"]
            main_category_titles = {
                "setup_hand": "Setup Hand",
                "prize_cards": "Prize Cards",
                "draw_for_turn": "Draw for Turn"
            }
            # Additional draws categories
            additional_categories = ["squak_draw", "prof_draw"]
            additional_category_titles = {
                "squak_draw": "Squawkabilly/Iono Draw",
                "prof_draw": "If You Draw 1 for Professor Research"
            }

            # Prepare data for each category
            top_n_text = 10
            top_n_images = 4
            font_path = "arial.ttf"
            try:
                font = ImageFont.truetype(font_path, 20)
            except:
                font = ImageFont.load_default()
            line_height = 25
            left_margin = 10
            top_margin = 10
            sprite_size = 100
            text_width = 350
            card_width = 140  # Smaller card image width
            card_height = 196 # Smaller card image height
            spacing = 10

            # Function to create report image
            def create_report_image(categories, category_titles, title):
                # Extract only summary lines (title, archetype, total simulations, average mulligans)
                summary_lines = []
                lines = report_text.split('\n')
                for line in lines:
                    if line.strip() == '' or any(cat in line for cat in category_titles.values()):
                        break
                    summary_lines.append(line)
                # Prepare per-category stats (top 10, no percentage)
                category_stats = {cat: [] for cat in categories}
                current_cat = None
                for line in lines:
                    for cat in categories:
                        if line.strip().startswith(category_titles[cat]):
                            current_cat = cat
                            break
                    else:
                        if current_cat and line.strip() and not line.strip().endswith(":"):
                            # Remove percentage if present
                            stat = line
                            if ' times (' in stat:
                                stat = stat.split(' times (')[0] + ' times'
                            category_stats[current_cat].append(stat)
                    # Stop collecting if we hit a category not in this image
                    if current_cat and not any(line.strip().startswith(category_titles[c]) for c in categories) and any(line.strip().endswith(":") for c in category_titles if category_titles[c] not in [category_titles[cat] for cat in categories]):
                        current_cat = None

                # Font sizes
                title_font_size = 40
                summary_font_size = 28
                try:
                    title_font = ImageFont.truetype(font_path, title_font_size)
                except:
                    title_font = ImageFont.load_default()
                try:
                    summary_font = ImageFont.truetype(font_path, summary_font_size)
                except:
                    summary_font = ImageFont.load_default()

                total_width = text_width + spacing + card_width * top_n_images + left_margin * 2
                sprite_height = sprite_size
                title_height = title_font_size + 10
                summary_height = len(summary_lines[1:]) * (summary_font_size + 6)
                top_section_height = sprite_height + title_height + summary_height + 40
                num_categories = len(categories)
                category_block_height = max(card_height, line_height * (top_n_text + 1)) + spacing
                total_height = top_section_height + num_categories * category_block_height + spacing * (num_categories + 1)

                img = Image.new('RGB', (total_width, total_height), 'white')
                draw = ImageDraw.Draw(img)

                y = 20
                if archetype_image:
                    sprite_x = (total_width - sprite_size) // 2
                    img.paste(archetype_image, (sprite_x, y), archetype_image)
                    y += sprite_height + 10

                # Draw title
                title_text = title
                title_bbox = title_font.getbbox(title_text)
                title_w = title_bbox[2] - title_bbox[0]
                draw.text(((total_width - title_w) // 2, y), title_text, fill='black', font=title_font)
                y += title_font_size + 10

                # Draw summary lines
                for line in summary_lines[1:]:
                    line_bbox = summary_font.getbbox(line)
                    line_w = line_bbox[2] - line_bbox[0]
                    draw.text(((total_width - line_w) // 2, y), line, fill='black', font=summary_font)
                    y += summary_font_size + 6

                y += 20

                # Draw each category block
                for idx, category in enumerate(categories):
                    # Always draw the top 10 stats, even if empty
                    draw.text((left_margin, y), category_titles[category] + ':', fill='black', font=font)
                    stats = category_stats[category][:top_n_text]
                    if not stats:
                        stats = ["(No data)"]
                    for i, stat in enumerate(stats):
                        draw.text((left_margin, y + (i + 1) * line_height), stat, fill='black', font=font)

                    # Get and draw card images
                    top_cards = results["card_appearances"][category].most_common(top_n_images)
                    card_images = []
                    for card_name, _ in top_cards:
                        card_data = None
                        display_name = card_name.replace('Poke', 'Poké')
                        if card_name.startswith('Basic') and 'Energy' in card_name:
                            match = re.match(r'Basic \{([A-Z])\} Energy', card_name)
                            if match:
                                symbol = '{' + match.group(1) + '}'
                                energy_type = energy_symbol_map.get(symbol, None)
                                if energy_type:
                                    normalized_name = f'Basic {energy_type} Energy'
                                    card_data = self.tcg_api.get_card_by_name(normalized_name)
                                    display_name = normalized_name
                                else:
                                    card_data = self.tcg_api.get_card_by_name(card_name)
                                    display_name = card_name
                            else:
                                card_data = self.tcg_api.get_card_by_name(card_name)
                                display_name = card_name
                        else:
                            card_entry = next((entry for entry in card_entries if entry[0] == card_name), None)
                            if card_entry:
                                api_name = card_entry[0].replace('Poke', 'Poké')
                                card_data = self.tcg_api.get_card_by_name(api_name, card_entry[1], card_entry[2])
                                if not card_data:
                                    card_data = self.tcg_api.get_card_by_name(api_name)
                        if card_data:
                            image_url = self.tcg_api.get_card_image_url(card_data)
                            if image_url:
                                try:
                                    response = requests.get(image_url)
                                    if response.status_code == 200:
                                        card_image = Image.open(io.BytesIO(response.content)).resize((card_width, card_height))
                                        card_images.append(card_image)
                                except Exception as e:
                                    print(f"Error loading card image: {e}")

                    for j, card_img in enumerate(card_images):
                        x_img = text_width + spacing + left_margin + j * card_width
                        y_img = y
                        img.paste(card_img, (x_img, y_img))

                    y += category_block_height + spacing

                return img

            # Create and send main report image
            main_img = create_report_image(main_categories, main_category_titles, "Main Simulation Report")
            main_img_path = "temp_main_report.png"
            main_img.save(main_img_path)
            await ctx.send(file=discord.File(main_img_path))
            os.remove(main_img_path)

            # Create and send additional draws report image
            additional_img = create_report_image(additional_categories, additional_category_titles, "Additional Draws Report")
            additional_img_path = "temp_additional_report.png"
            additional_img.save(additional_img_path)
            await ctx.send(file=discord.File(additional_img_path))
            os.remove(additional_img_path)

        except ValueError as e:
            await ctx.send(f"Error: {str(e)}")
        except Exception as e:
            await ctx.send(f"An unexpected error occurred: {str(e)}")

async def setup(bot):
    await bot.add_cog(ToolCommands(bot)) 