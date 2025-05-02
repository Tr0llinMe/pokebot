import discord
import asyncio
import os
import re
import json
from PIL import Image, ImageDraw, ImageFont
import requests
import io
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, Tuple

from discord.ext import commands
from discord import Interaction

from supabase import create_client

from config import supabase, OWNER_ID, DISCORD_TOKEN, DISCORD_ALERT_CHANNEL 
#from models import Base, User, Deck, Match, DeckArchetype

# Define intents
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.message_content = True

# Create bot instance with intents and remove default help command
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Rate limiting setup
class RateLimiter:
    def __init__(self, rate: int, per: float):
        self.rate = rate  # Number of allowed commands
        self.per = per   # Time window in seconds
        self.tokens = defaultdict(lambda: self.rate)
        self.last_update = defaultdict(float)

    def is_rate_limited(self, user_id: int) -> Tuple[bool, float]:
        current = datetime.now().timestamp()
        time_passed = current - self.last_update[user_id]
        
        # Reset tokens if enough time has passed
        if time_passed > self.per:
            self.tokens[user_id] = self.rate
        
        # Update last check time
        self.last_update[user_id] = current
        
        if self.tokens[user_id] <= 0:
            return True, self.per - time_passed
        
        self.tokens[user_id] -= 1
        return False, 0

# Create rate limiter instance (5 commands per 10 seconds)
rate_limiter = RateLimiter(5, 10)

# Error handler for the bot
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send("❌ This command can only be used in a server, not in DMs!")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command!")
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Unknown command! Use `!help` to see available commands.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: {error.param.name}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Invalid argument provided! Please check the command usage.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Please wait {error.retry_after:.1f}s before using this command again.")
    else:
        # Log unexpected errors
        print(f"Unexpected error: {error}")
        await ctx.send("❌ An unexpected error occurred. Please try again later.")

# Command error handler for specific commands
@bot.event
async def on_command(ctx):
    # Check rate limit
    is_limited, wait_time = rate_limiter.is_rate_limited(ctx.author.id)
    if is_limited:
        await ctx.send(f"⏳ You're sending commands too quickly! Please wait {wait_time:.1f} seconds.")
        return

    # Log command usage
    print(f"Command used: {ctx.command.name} by {ctx.author} ({ctx.author.id})")

# Custom help command
@bot.command()
async def help(ctx):
    """Shows this help message"""
    embed = discord.Embed(
        title="PokéBot Commands",
        description="Here are all available commands:",
        color=discord.Color.blue()
    )
    
    # User commands
    embed.add_field(
        name="👤 User Commands",
        value="`!user register` - Register yourself\n",
        inline=False
    )
    
    # Deck commands
    embed.add_field(
        name="📝 Deck Commands",
        value="`!deck add <name>` - Add a new deck\n"
              "`!deck edit` - Edit an existing deck\n"
              "`!mydecks` - View your decks\n"
              "`!viewdeck <ID>` - View a specific deck",
        inline=False
    )
    
    # Match commands
    embed.add_field(
        name="🎮 Match Commands",
        value="`!match log` - Log a match\n"
              "`!match history` - View matchup history",
        inline=False
    )
    
    # Admin commands (only shown to owner)
    if str(ctx.author.id) == OWNER_ID:
        embed.add_field(
            name="⚙️ Admin Commands",
            value="`!archetype add` - Add new archetype\n"
                  "`!tool spritefetch` - Fetch Pokémon sprites",
            inline=False
        )
    
    embed.set_footer(text="Use the commands in the appropriate channels!")
    await ctx.send(embed=embed)

#Admin Logs -  Tracking pending deck updates
pending_archetype_updates = {}  # {message_id: {"user_id": int, "deck_id": int, "deck_name": str, "cards": list}}

@bot.event
async def on_ready():
    print(f'Bot is ready. Logged in as {bot.user}')
    
    
def extract_card_names(deck_content):
    """
    Extract full Pokémon card names while ignoring set codes.
    """
    # Match card lines: "1 Roaring Moon ex PRE 162"
    matches = re.findall(r'\d+\s+([A-Za-z\s-]+?)(?:\s+\w+\s*\d+)?$', deck_content, re.MULTILINE)

    # Normalize to extract only the first word
    return [normalize_text(match) for match in matches]


def normalize_text(text):
    """
    Normalize card names by:
    
    Converting to lowercase
    Removing set codes (any extra words after the first two)
    Stripping extra spaces
    """
    text = text.lower().strip()  # Convert to lowercase
    words = text.split()
    return words[0] if words else ""  # Extract only the first word

def normalize_pokeapi_name(archetype_name):
    # Convert "RoaringMoon" or "Iron Valiant" to "roaring-moon"
    # Handles camel case and spaces
    name = archetype_name.replace(" ", "-")
    # Insert hyphens before uppercase letters (except the first)
    name = ''.join(['-' + c.lower() if c.isupper() and i != 0 else c.lower() for i, c in enumerate(name)])
    name = name.replace('--', '-')  # In case of double hyphens
    return name

def get_sprite(archetype_name):
    sprite_dir = './sprites'
    os.makedirs(sprite_dir, exist_ok=True)
    sprite_path = os.path.join(sprite_dir, f'{archetype_name.lower()}.png')
    
    # Special case for "Others" archetype - use Unown
    if archetype_name == "Others":
        sprite_path = os.path.join(sprite_dir, 'unown.png')
        if os.path.exists(sprite_path):
            return Image.open(sprite_path).convert('RGBA')
        # Fetch Unown sprite if not cached
        url = 'https://pokeapi.co/api/v2/pokemon/unown/'
        try:
            data = requests.get(url).json()
            sprite_url = data['sprites']['front_default']
            if not sprite_url:
                raise Exception("No sprite found in API response.")
            sprite_data = requests.get(sprite_url).content
            with open(sprite_path, 'wb') as f:
                f.write(sprite_data)
            return Image.open(io.BytesIO(sprite_data)).convert('RGBA')
        except Exception as e:
            print(f'Error fetching Unown sprite: {e}')
            return Image.new('RGBA', (64, 64), (255, 255, 255, 0))
    
    if os.path.exists(sprite_path):
        return Image.open(sprite_path).convert('RGBA')
    # Try to fetch from PokéAPI
    pokeapi_name = normalize_pokeapi_name(archetype_name)
    url = f'https://pokeapi.co/api/v2/pokemon/{pokeapi_name}/'
    try:
        data = requests.get(url).json()
        sprite_url = data['sprites']['front_default']
        if not sprite_url:
            raise Exception("No sprite found in API response.")
        sprite_data = requests.get(sprite_url).content
        with open(sprite_path, 'wb') as f:
            f.write(sprite_data)
        return Image.open(io.BytesIO(sprite_data)).convert('RGBA')
    except Exception as e:
        print(f'Error fetching sprite for {archetype_name}: {e}')
        # Return a blank placeholder
        return Image.new('RGBA', (64, 64), (255, 255, 255, 0))

def winrate_color(winrate):
    # Interpolate between red (low), white (mid), blue (high)
    if winrate < 40:
        # Red: (255, 128, 128)
        return (255, int(128 + (winrate/40)*127), int(128 + (winrate/40)*127))
    elif winrate > 60:
        # Blue: (128, 192, 255)
        return (int(128 + ((100-winrate)/40)*127), int(192 + ((100-winrate)/40)*63), 255)
    else:
        # White: (255, 255, 255)
        return (255, 255, 255)

def create_matchup_image(summary, archetype_name):
    cell_width, cell_height = 120, 180
    try:
        font = ImageFont.truetype('arial.ttf', 16)
    except:
        # Fallback to default font if arial not found
        font = ImageFont.load_default()
    
    num_cells = len(summary)
    if num_cells == 0:
        return None
        
    img = Image.new('RGBA', (cell_width * num_cells, cell_height), (255,255,255,255))
    draw = ImageDraw.Draw(img)
    
    for i, (opp, record) in enumerate(summary.items()):
        total = record['Win'] + record['Loss'] + record['Tie']
        if total == 0:
            continue
            
        winrate = (record['Win'] + record['Tie']/3) / total * 100
        color = winrate_color(winrate)
        x = i * cell_width
        
        # Draw background
        draw.rectangle([x, 0, x+cell_width, cell_height], fill=color)
        
        # Draw sprite
        sprite = get_sprite(opp)
        sprite = sprite.resize((64, 64))
        img.paste(sprite, (x + 28, 20), sprite)
        
        # Draw text
        text_color = (0, 0, 0)  # Black text
        draw.text((x+10, 90), f'{winrate:.1f}%', font=font, fill=text_color)
        draw.text((x+10, 120), f'{record["Win"]}-{record["Loss"]}-{record["Tie"]}', font=font, fill=text_color)
        
        # Handle archetype name with better text wrapping
        # Split camelCase: look for capital letters after lowercase
        name_parts = []
        current_word = opp[0]
        for c in opp[1:]:
            if c.isupper() and current_word[-1].islower():
                name_parts.append(current_word)
                current_word = c
            else:
                current_word += c
        name_parts.append(current_word)
        
        if len(name_parts) > 1:
            # For multi-part names (like RoaringMoon), split into parts
            first_line = name_parts[0]
            second_line = ''.join(name_parts[1:])
            draw.text((x+10, 140), first_line, font=font, fill=text_color)
            draw.text((x+10, 155), second_line, font=font, fill=text_color)
        else:
            # For single-word names
            draw.text((x+10, 140), opp, font=font, fill=text_color)
    
    return img

### SINGLE COMMANDS ###

## This is to view the decks based on the user ##
@bot.command()
async def mydecks(ctx):
    discord_id = str(ctx.author.id)  # ✅ Ensure it's a string

    # ✅ Step 1: Get the internal `user_id` from the users table
    user_response = supabase.table('users').select("id").eq("discord_id", discord_id).execute()

    if not user_response.data:
        await ctx.send("❌ You are not registered in the system. Please add a deck first.")
        return

    user_id = user_response.data[0]["id"]  # ✅ Fetch internal user ID

    # ✅ Step 2: Fetch all decks for this `user_id`
    user_decks = supabase.table('decks').select("id, name, decklist").eq("user_id", user_id).execute()

    # ✅ Debugging: Print response to verify data
    print(f"Debug: Retrieved Decks for User ID {user_id}: {user_decks.data}")

    if not user_decks.data:
        await ctx.send("You don't have any saved decks yet.")
        return

    # ✅ Format response message
    response = "**Your Saved Decks:**\n"
    for deck in user_decks.data:
        deck_data = json.loads(deck["decklist"])  # Convert JSON string back to Python dict
        response += f"- **{deck_data['name']}** - {deck_data['archetype']} (ID: {deck['id']})\n"

    response += "\nType `!viewdeck <ID>` to see a specific decklist."

    await ctx.send(response)
## This is to view the decklist given the deck and ID ##
@bot.command()
async def viewdeck(ctx, deck_id: int):
    discord_id = str(ctx.author.id)  # Ensure correct format

    # ✅ Step 1: Get `user_id` from `users` table
    user_response = supabase.table('users').select("id").eq("discord_id", discord_id).execute()
    if not user_response.data:
        await ctx.send("❌ You are not registered in the system. Please add a deck first.")
        return

    user_id = user_response.data[0]["id"]  # ✅ Fetch internal user ID

    # ✅ Step 2: Fetch the requested deck using `user_id`
    deck_response = supabase.table('decks').select("decklist").eq("user_id", user_id).eq("id", deck_id).execute()

    if not deck_response.data:
        await ctx.send("❌ Deck not found.")
        return

    deck_data = json.loads(deck_response.data[0]['decklist'])  # Convert JSON back to Python dict

    # ✅ Format decklist output
    response = f"📜 **{deck_data['name']}** - {deck_data['archetype']} 📜\n"
    response += f"🕒 Last Modified: {deck_data['last_modified']}\n"
    response += "```" + "\n".join(deck_data["cards"]) + "```"

    await ctx.send(response)

### USER GROUP ###
@bot.group()
async def user(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send('Please specify a subcommand for user, e.g., "!user register".')
    
@user.command(name='register')
async def register(ctx):
    discord_id = str(ctx.author.id)
    username = str(ctx.author)
    
    # Check if user already exists in Supabase
    response = supabase.table('users').select("*").eq('discord_id', discord_id).execute()
    if response.data:
        await ctx.send('You are already registered.')
    else:
        # Insert new user
        supabase.table('users').insert({"discord_id": discord_id, "username": username}).execute()
        await ctx.send('You have been registered.')

### DECK GROUP ###
@bot.group()
async def deck(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send('Please specify a subcommand for user, e.g., "!deck add".')

@deck.command(name='add')
@commands.dm_only()
async def deck_add(ctx, deck_name: str = None):
    discord_id = str(ctx.author.id)
    
    # Check if user is registered
    user_response = supabase.table('users').select("*").eq('discord_id', discord_id).execute()
    if not user_response.data:
        await ctx.send('You need to register first.')
        return

    if not deck_name:
        await ctx.send('Please provide a deck name using the format `!add deck <deck_name>`.')
        return

    #Checking input by user to see how the data is handled
    await ctx.send('Would you like to upload a file or paste the decklist? Reply with `file` or `text`.')
    def check(msg):
        return msg.author == ctx.author and msg.channel == ctx.channel
    try:
        choice_msg = await bot.wait_for("message", check=check, timeout=60.0)
        choice = choice_msg.content.lower().strip()
    except asyncio.TimeoutError:
        await ctx.send("You took too long to respond. Please try again.")
        return

    deck_content = None
    
    # Define `file_path` for early setup
    upload_dir = 'uploads'
    os.makedirs(upload_dir, exist_ok=True)
    sanitized_deck_name = re.sub(r'\W+', '_', deck_name)
    file_path = os.path.join(upload_dir, f"{discord_id}_{sanitized_deck_name}.txt")
    
    if choice == "file":
        await ctx.send("Please upload your deck file.")

        try:
            file_msg = await bot.wait_for("message", check=check, timeout=120.0)
            if not file_msg.attachments:
                await ctx.send("No file detected. Please try again.")
                return

            #Allowing file to be saved
            deck_file = file_msg.attachments[0]
            await deck_file.save(file_path)

            # Read and process the deck file
            with open(file_path, 'r') as file:
                deck_content = file.read()
        except asyncio.TimeoutError:
            await ctx.send("You took too long to upload the file. Please try again.")
            return

    elif choice == "text":
        await ctx.send("Please paste your decklist (one card per line).")

        try:
            deck_msg = await bot.wait_for("message", check=check, timeout=180.0)
            deck_content = deck_msg.content
            
            # Save the manually entered decklist to a file
            with open(file_path, "w") as file:
                file.write(deck_content)
                
        except asyncio.TimeoutError:
            await ctx.send("You took too long to paste the decklist. Please try again.")
            return

    else:
        await ctx.send("Invalid option. Please use `file` or `text`.")
        return

    if not deck_content:
        await ctx.send("Deck content is empty. Please try again.")
        return

    # Extract card names
    cards = re.findall(r'\d+\s+([\w-]+)', deck_content)
    cards = [normalize_text(card) for card in cards]
    
    cards = extract_card_names(deck_content)

    # Identify archetype
    identified_archetype = "Others"  # Default to "Others"

    archetype_response = supabase.table('deck_archetypes').select("*").execute()
    for archetype in archetype_response.data:
        archetype_cards = [normalize_text(card.strip()) for card in archetype['key_cards'].split(',')]

        # Count the number of matching key cards
        match_count = sum(1 for ac in archetype_cards if ac in cards)
        
        # Debug which key cards aren't matching
        unmatched_cards = [ac for ac in archetype_cards if ac not in cards]
        print(f"Key Cards Not Found in Deck: {unmatched_cards}")

        # Debugging output
        print(f"Checking Archetype: {archetype['name']}")
        print(f"Matching Key Cards Found: {match_count} / 3 Required")
        
        
    
        # If at least 3 key cards match, assign this archetype
        if match_count >= 3:
            identified_archetype = archetype['name']
            break
        
        
        
    # Ensure "Others" archetype exists - Purely needed just in case error in database tables
    others_archetype = supabase.table('deck_archetypes').select("*").eq('name', 'Others').execute()
    if not others_archetype.data:
        supabase.table('deck_archetypes').insert({"name": "Others", "key_cards": ""}).execute()

    # ✅ Convert decklist into JSON format
    deck_data = {
        "name": deck_name,
        "archetype": identified_archetype,
        "cards": deck_content.split("\n"),  # Store decklist as a list
        "last_modified": datetime.now(timezone.utc).isoformat()  # Store timestamp for future updates
    }

    # ✅ Insert deck into the database
    user_id = user_response.data[0]['id']
    archetype_entry = next((a for a in archetype_response.data if a['name'] == identified_archetype), None)

    deck_insert_response = supabase.table('decks').insert({
        "user_id": user_id,
        "name": deck_name,
        "archetype_id": archetype_entry['id'] if archetype_entry else None,
        "decklist": json.dumps(deck_data)  # ✅ Supabase supports JSONB storage with JSON dumps
    }).execute()
    

    #Deck ID
    deck_id = deck_insert_response.data[0]['id']
    await ctx.send(f'Deck "{deck_name}" has been added with the identified archetype "{identified_archetype}".')
     
    # If deck is classified as "Others", send notification with file
    if identified_archetype == "Others":
        channel = bot.get_channel(DISCORD_ALERT_CHANNEL)
        if channel:
            # Create a Discord File object from the uploaded decklist
            deck_file = discord.File(file_path, filename=f"{deck_name}.txt")

            alert_message = await channel.send(
                f"🚨 **Unrecognized Deck Submission** 🚨\n"
                f"User: <@{discord_id}>\n"
                f"Deck Name: **{deck_name}**\n"
                f"Archetype set to **'Others'**. Click ✅ to categorize.",
                file=deck_file  # Attach the file
            )
            await alert_message.add_reaction("✅")

            # Store pending deck updates for Admins to track
            pending_archetype_updates[alert_message.id] = {
                "user_id": discord_id, #store within string id
                "deck_id": deck_id,
                "deck_name": deck_name,
                "cards": cards
            }

@deck.command(name='edit')
@commands.dm_only()
async def deck_edit(ctx):
    discord_id = str(ctx.author.id) #Fetch User ID
    
    # ✅ Step 1: Matching user ID based on disc ID
    user_response = supabase.table('users').select("id").eq("discord_id", discord_id).execute()
    if not user_response.data:
        await ctx.send("❌ You are not registered in the system. Please add a deck first.")
        return

    user_id = user_response.data[0]["id"] #Grab the ID of the user
    
    # ✅ Step 2: Fetch all decks for this user
    user_decks = supabase.table('decks').select("id, name, decklist").eq("user_id", user_id).execute()
    if not user_decks.data:
        await ctx.send("You don't have any saved decks yet.")
        return

    # ✅ Step 3: List decks for user selection
    response = "**Your Saved Decks:**\n"
    for deck in user_decks.data:
        deck_data = json.loads(deck["decklist"])
        response += f"- **{deck_data['name']}** - {deck_data['archetype']} (ID: {deck['id']})\n"

    response += "\nPlease enter the `ID` of the deck you want to edit:"
    await ctx.send(response)

    def check(msg):
        return msg.author == ctx.author and msg.channel == ctx.channel

    try:
        deck_id_msg = await bot.wait_for("message", check=check, timeout=60.0)
        deck_id = int(deck_id_msg.content.strip())
    except (asyncio.TimeoutError, ValueError):
        await ctx.send("❌ Invalid input. Please try again.")
        return

    # ✅ Step 4: Fetch selected deck
    deck_response = supabase.table('decks').select("id, name, decklist").eq("user_id", user_id).eq("id", deck_id).execute()
    if not deck_response.data:
        await ctx.send("❌ Deck not found or you do not have permission to edit this deck.")
        return

    deck = deck_response.data[0]
    deck_data = json.loads(deck["decklist"])  # Convert JSON string to dict
    
    # ✅ Step 5: Ask if they want to upload a file or paste the decklist
    await ctx.send("📜 Would you like to upload a new deck file or paste the decklist? Reply with `file` or `text`.")

    try:
        choice_msg = await bot.wait_for("message", check=check, timeout=60.0)
        choice = choice_msg.content.lower().strip()
    except asyncio.TimeoutError:
        await ctx.send("❌ You took too long to respond.")
        return

    deck_content = None

    if choice == "file":
        await ctx.send("📁 Please upload your new deck file.")

        try:
            file_msg = await bot.wait_for("message", check=check, timeout=120.0)
            if not file_msg.attachments:
                await ctx.send("❌ No file detected. Please try again.")
                return

            deck_file = file_msg.attachments[0]
            deck_content = await deck_file.read()  # Read file contents as string
            deck_content = deck_content.decode("utf-8")  # Convert bytes to string
        except asyncio.TimeoutError:
            await ctx.send("❌ You took too long to upload the file. Please try again.")
            return

    elif choice == "text":
        await ctx.send("📜 Please paste your new decklist (one card per line).")

        try:
            deck_msg = await bot.wait_for("message", check=check, timeout=180.0)
            deck_content = deck_msg.content.strip()
        except asyncio.TimeoutError:
            await ctx.send("❌ You took too long to paste the decklist. Please try again.")
            return
    else:
        await ctx.send("❌ Invalid option. Please try again.")
        return

    # ✅ Step 6: Ask if they want to change the deck name
    await ctx.send("✏️ Would you like to rename the deck? Reply with `y` or `n`.")

    try:
        rename_msg = await bot.wait_for("message", check=check, timeout=30.0)
        rename_choice = rename_msg.content.lower().strip()
    except asyncio.TimeoutError:
        await ctx.send("❌ You took too long to respond. Keeping the original name.")
        rename_choice = "n"

    if rename_choice == "y":
        await ctx.send("✏️ Enter the new deck name:")
        try:
            name_msg = await bot.wait_for("message", check=check, timeout=60.0)
            new_name = name_msg.content.strip()
        except asyncio.TimeoutError:
            await ctx.send("❌ You took too long to respond. Keeping the original name.")
            new_name = deck_data["name"]
    else:
        new_name = deck_data["name"]

    # ✅ Step 7: Update deck in database
    deck_data["name"] = new_name
    deck_data["cards"] = deck_content.split("\n")  # Convert new decklist to list
    deck_data["last_modified"] = datetime.now(timezone.utc).isoformat()  # Update timestamp

    update_fields = {
        "name": new_name,
        "decklist": json.dumps(deck_data)  # Store updated JSON
    }

    supabase.table('decks').update(update_fields).eq("id", deck_id).execute()

    await ctx.send(f"✅ Your deck **{deck_data['name']}** has been updated successfully!")

### ARCHETYPE GROUP ###
@bot.group()
async def archetype(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send('Please specify a subcommand for user, e.g., "!archetype add".')


@archetype.command(name='add')
@commands.dm_only()
async def archetype_add(ctx):
    if str(ctx.author.id) != OWNER_ID:
        await ctx.send('You are not authorized to add archetypes.')
        return

    # Prompt user for archetype name
    await ctx.send('Please enter the archetype name:')
    
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        archetype_name = await bot.wait_for('message', check=check, timeout=60.0)
    except asyncio.TimeoutError:
        await ctx.send('You took too long to respond. Please try again.')
        return

    # Prompt user for key cards
    await ctx.send('Please enter the key cards for the archetype, separated by commas:')
    
    try:
        key_cards_message = await bot.wait_for('message', check=check, timeout=60.0)
    except asyncio.TimeoutError:
        await ctx.send('You took too long to respond. Please try again.')
        return
    
    # Process the key cards
    key_cards = key_cards_message.content.split(',')
    key_cards = [card.strip() for card in key_cards]

    # Add the archetype to the database using Supabase
    try:
        response = supabase.table('deck_archetypes').insert({
        "name": archetype_name.content,
        "key_cards": ','.join(key_cards)
        }).execute()
        
        #Checking if the Insert was Successful
        if response.error:
            await ctx.send('An error occurred while adding the archetype. Please try again later.')
            print(f"Error adding archetype: {response.error}")
        else:
            await ctx.send(f'Archetype "{archetype_name.content}" has been added with key cards: {", ".join(key_cards)}')
    except Exception as e:
        await ctx.send('❌ An error occurred while adding the archetype. Please try again later.')
        print(f"Error adding archetype: {e}")

### MATCH GROUP ###
@bot.group()
async def match(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send('Please specify a subcommand for user, e.g., "!match log".')

@match.command(name='log')
async def log_match(ctx):
    discord_id = str(ctx.author.id)
    
    # Check if user is registered
    user_response = supabase.table('users').select("*").eq('discord_id', discord_id).execute()
    if not user_response.data:
        await ctx.send('You need to register first.')
        return

    user = user_response.data[0]
    
    # Get user's decks
    decks_response = supabase.table('decks').select("id, name").eq('user_id', user['id']).execute()
    if not decks_response.data:
        await ctx.send('You need to add a deck first.')
        return

    # Create an embed with deck selection buttons
    embed = discord.Embed(
        title="Select Your Deck",
        description="Click the reaction corresponding to your deck:",
        color=discord.Color.blue()
    )
    
    # Add deck options to embed
    for i, deck in enumerate(decks_response.data):
        embed.add_field(name=f"{i+1}. {deck['name']}", value="\u200b", inline=False)
    
    message = await ctx.send(embed=embed)
    
    # Add number reactions
    for i in range(len(decks_response.data)):
        await message.add_reaction(f"{i+1}\u20e3")  # Number emojis
    
    # Wait for reaction
    def check(reaction, user):
        return user == ctx.author and reaction.message.id == message.id and reaction.emoji in [f"{i+1}\u20e3" for i in range(len(decks_response.data))]
    
    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
        deck_index = int(reaction.emoji[0]) - 1
        selected_deck = decks_response.data[deck_index]
        
        # Ask for match result
        result_embed = discord.Embed(
            title="Match Result",
            description="React with ✅ for Win, ❌ for Loss, or ➖ for Tie",
            color=discord.Color.blue()
        )
        result_message = await ctx.send(embed=result_embed)
        await result_message.add_reaction("✅")
        await result_message.add_reaction("❌")
        await result_message.add_reaction("➖")  # Tie
        
        def result_check(reaction, user):
            return user == ctx.author and reaction.message.id == result_message.id and reaction.emoji in ["✅", "❌", "➖"]
        
        result_reaction, _ = await bot.wait_for('reaction_add', timeout=60.0, check=result_check)
        match_result = None
        if str(result_reaction.emoji) == "✅":
            match_result = "Win"
        elif str(result_reaction.emoji) == "❌":
            match_result = "Loss"
        elif str(result_reaction.emoji) == "➖":
            match_result = "Tie"
            
        if match_result is None:
            await ctx.send("Invalid result selection. Please try again.")
            return
        
        # Get archetypes
        archetypes_response = supabase.table('deck_archetypes').select("*").execute()
        archetypes = archetypes_response.data
        main_archetypes = [a for a in archetypes if a['name'] != 'Others']
        others_archetype = next((a for a in archetypes if a['name'] == 'Others'), None)
        if others_archetype:
            main_archetypes.append(others_archetype)
        
        archetype_embed = discord.Embed(
            title="Opponent's Archetype",
            description="Select the opponent's archetype (react or type the number):",
            color=discord.Color.blue()
        )
        for i, archetype in enumerate(main_archetypes):
            archetype_embed.add_field(name=f"{i+1}. {archetype['name']}", value="\u200b", inline=False)
        archetype_message = await ctx.send(embed=archetype_embed)
        for i in range(len(main_archetypes)):
            await archetype_message.add_reaction(f"{i+1}\u20e3")
        
        def archetype_check(reaction, user):
            return user == ctx.author and reaction.message.id == archetype_message.id and reaction.emoji in [f"{i+1}\u20e3" for i in range(len(main_archetypes))]
        
        archetype_index = None
        try:
            # Create tasks for both message and reaction
            message_task = asyncio.create_task(bot.wait_for('message', timeout=60.0, check=lambda m: m.author == ctx.author and m.channel == ctx.channel))
            reaction_task = asyncio.create_task(bot.wait_for('reaction_add', timeout=60.0, check=archetype_check))
            
            # Wait for either task to complete
            done, pending = await asyncio.wait([message_task, reaction_task], return_when=asyncio.FIRST_COMPLETED)
            
            # Cancel pending tasks
            for task in pending:
                task.cancel()
            
            # Process the completed task
            for task in done:
                result = await task
                if isinstance(result, tuple):  # reaction
                    archetype_index = int(result[0].emoji[0]) - 1
                else:  # message
                    try:
                        archetype_index = int(result.content.strip()) - 1
                    except Exception:
                        archetype_index = None
            
            if archetype_index is None or archetype_index < 0 or archetype_index >= len(main_archetypes):
                await ctx.send("Invalid archetype selection.")
                return
        except asyncio.TimeoutError:
            await ctx.send("You took too long to respond. Please try logging the match again.")
            return
            
        opponent_archetype = main_archetypes[archetype_index]['name']
        
        # Ask for optional notes
        notes_embed = discord.Embed(
            title="Match Notes (Optional)",
            description="Type any notes about the match or react with ❌ to skip",
            color=discord.Color.blue()
        )
        notes_message = await ctx.send(embed=notes_embed)
        await notes_message.add_reaction("❌")
        
        notes = None
        def notes_check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            # Create tasks for both message and reaction
            message_task = asyncio.create_task(bot.wait_for('message', timeout=60.0, check=notes_check))
            reaction_task = asyncio.create_task(bot.wait_for('reaction_add', timeout=60.0, check=lambda r, u: u == ctx.author and r.message.id == notes_message.id and str(r.emoji) == "❌"))
            
            # Wait for either task to complete
            done, pending = await asyncio.wait([message_task, reaction_task], return_when=asyncio.FIRST_COMPLETED)
            
            # Cancel pending tasks
            for task in pending:
                task.cancel()
            
            # Process the completed task
            for task in done:
                result = await task
                if isinstance(result, tuple):  # reaction
                    notes = None
                    break  # Exit the loop since we got a reaction
                else:  # message
                    notes = str(result.content)  # Ensure we store a string
        except asyncio.TimeoutError:
            notes = None
        
        # Log the match
        current_date = datetime.now().strftime('%Y-%m-%d')
        match_data = {
            "deck_id": selected_deck['id'],
            "result": str(match_result),  # Use match_result instead of result
            "opponent_archetype": str(opponent_archetype),  # Ensure archetype is a string
            "player": str(ctx.author.name),  # Ensure player name is a string
            "date": str(current_date),  # Ensure date is a string
            "notes": str(notes) if notes is not None else None  # Ensure notes is a string or None
        }
        
        try:
            match_response = supabase.table('matches').insert(match_data).execute()
            
            success_embed = discord.Embed(
                title="Match Logged Successfully!",
                description=f"Deck: {selected_deck['name']}\nResult: {match_result}\nOpponent: {opponent_archetype}\nDate: {current_date}",
                color=discord.Color.green()
            )
            if notes:
                success_embed.add_field(name="Notes", value=notes, inline=False)
            await ctx.send(embed=success_embed)
            
            # If new archetype was requested, send notification to admin channel
            if opponent_archetype == "Others":
                channel = bot.get_channel(DISCORD_ALERT_CHANNEL)
                if channel:
                    # Get user's name from Discord
                    user_obj = bot.get_user(int(discord_id))
                    username = user_obj.name if user_obj else "Unknown User"
                    
                    alert_embed = discord.Embed(
                        title="New Archetype Request",
                        description=f"User: **{username}** (<@{discord_id}>)\nRequested archetype: **{opponent_archetype}**",
                        color=discord.Color.orange()
                    )
                    alert_embed.add_field(name="Deck", value=selected_deck['name'], inline=True)
                    alert_embed.add_field(name="Match Result", value=match_result, inline=True)
                    alert_message = await channel.send(embed=alert_embed)
                    await alert_message.add_reaction("✅")
                    
                    # Store the alert message ID for later reference
                    pending_archetype_updates[alert_message.id] = {
                        "user_id": str(discord_id),  # Ensure discord_id is a string
                        "deck_id": int(selected_deck['id']),  # Ensure deck_id is an integer
                        "deck_name": str(selected_deck['name']),  # Ensure deck_name is a string
                        "new_archetype": str(opponent_archetype),  # Ensure archetype is a string
                        "match_id": int(match_response.data[0]['id'])  # Ensure match_id is an integer
                    }
        except Exception as e:
            await ctx.send('An error occurred while logging the match. Please try again later.')
            print(f"Error logging match: {e}")
            
    except asyncio.TimeoutError:
        await ctx.send("You took too long to respond. Please try logging the match again.")

@match.command(name='history')
@commands.guild_only()
async def matchup_history(ctx):
    # Step 1: Prompt for archetype
    archetypes_response = supabase.table('deck_archetypes').select("*").execute()
    archetypes = [a['name'] for a in archetypes_response.data if a['name'] != 'Others']
    archetypes.append('Others')  # Add Others at the end
    
    msg = "Which archetype do you want a matchup history for?\n"
    msg += "\n".join(f"{i+1}. {name}" for i, name in enumerate(archetypes))
    await ctx.send(msg)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        reply = await bot.wait_for('message', check=check, timeout=60.0)
        idx = int(reply.content.strip()) - 1
        if idx < 0 or idx >= len(archetypes):
            await ctx.send("Invalid selection.")
            return
        selected_archetype = archetypes[idx]
    except Exception:
        await ctx.send("Invalid input or timeout.")
        return

    # Step 2: Get all users in the guild
    guild_members = [str(member.id) for member in ctx.guild.members]
    users_response = supabase.table('users').select("*").execute()
    user_ids = [user['id'] for user in users_response.data if user['discord_id'] in guild_members]

    # Step 3: Get all decks of the selected archetype
    decks_response = supabase.table('decks').select("*").in_("user_id", user_ids).execute()
    # Find the archetype_id for the selected archetype
    selected_archetype_id = None
    for a in archetypes_response.data:
        if a['name'] == selected_archetype:
            selected_archetype_id = a['id']
            break
    deck_ids = [deck['id'] for deck in decks_response.data if deck.get('archetype_id') == selected_archetype_id]

    if not deck_ids:
        await ctx.send("No decks found for that archetype.")
        return

    # Step 4: Get all matches for those decks
    matches_response = supabase.table('matches').select("*").in_("deck_id", deck_ids).execute()
    matches = matches_response.data

    # Step 5: Aggregate by opponent archetype
    summary = {}
    for match in matches:
        opp = match['opponent_archetype']
        if opp not in summary:
            summary[opp] = {'Win': 0, 'Loss': 0, 'Tie': 0}
        summary[opp][match['result']] += 1

    # Step 6: Generate both text and image output
    # Text output
    output = f"Matchup History for {selected_archetype}:\n"
    output += "Opponent | Win% | W-L-T\n"
    output += "---------|------|------\n"
    for opp, record in summary.items():
        total = record['Win'] + record['Loss'] + record['Tie']
        if total == 0:
            continue
        winrate = (record['Win'] + record['Tie']/3) / total * 100
        output += f"{opp} | {winrate:.1f}% | {record['Win']}-{record['Loss']}-{record['Tie']}\n"
    
    await ctx.send(f"```{output}```")
    
    # Image output
    img = create_matchup_image(summary, selected_archetype)
    if img:
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        await ctx.send(file=discord.File(buf, filename=f'{selected_archetype}_matchups.png'))
    else:
        await ctx.send("No matchup data available to generate image.")

### TOOL GROUP ###
@bot.group()
async def tool(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send('Please specify a subcommand for user, e.g., "!tool mully".')
        
@tool.command(name='spritefetch')
@commands.dm_only()
async def sprite_fetch(ctx):
    if str(ctx.author.id) != OWNER_ID:
        await ctx.send('You are not authorized to fetch sprites.')
        return

    # Get all archetypes
    archetypes_response = supabase.table('deck_archetypes').select("*").execute()
    archetypes = [a['name'] for a in archetypes_response.data]
    
    # Create progress message
    progress_msg = await ctx.send("Starting sprite fetch...")
    
    # Fetch sprites for each archetype
    success_count = 0
    error_count = 0
    error_list = []
    
    for archetype in archetypes:
        try:
            # Update progress
            await progress_msg.edit(content=f"Fetching sprite for {archetype}...")
            
            # Get sprite (this will automatically cache it)
            sprite = get_sprite(archetype)
            
            if sprite:
                success_count += 1
            else:
                error_count += 1
                error_list.append(archetype)
                
        except Exception as e:
            error_count += 1
            error_list.append(f"{archetype} ({str(e)})")
            print(f"Error fetching sprite for {archetype}: {e}")
    
    # Send completion message
    result_msg = f"✅ Sprite fetch completed!\n"
    result_msg += f"Successfully fetched: {success_count} sprites\n"
    if error_count > 0:
        result_msg += f"Failed to fetch: {error_count} sprites\n"
        result_msg += "Failed archetypes:\n"
        result_msg += "\n".join(f"- {archetype}" for archetype in error_list)
    
    await ctx.send(result_msg)

## ADMIN: ON CERTAIN EVENTS
@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return  # Do not respond
    
    if reaction.message.id in pending_archetype_updates and str(reaction.emoji) == "✅":
        # Get the pending archetype information
        archetype_info = pending_archetype_updates[reaction.message.id]
        
        # Ask admin to either create new archetype or select existing one
        admin_embed = discord.Embed(
            title="Archetype Request Response",
            description=f"User requested archetype: **{archetype_info['new_archetype']}**\n\n"
                       f"1️⃣ Create new archetype\n"
                       f"2️⃣ Map to existing archetype\n"
                       f"3️⃣ Keep as 'Others'",
            color=discord.Color.blue()
        )
        admin_message = await reaction.message.channel.send(embed=admin_embed)
        await admin_message.add_reaction("1️⃣")
        await admin_message.add_reaction("2️⃣")
        await admin_message.add_reaction("3️⃣")
        
        def admin_check(r, u):
            return (
                u.id == user.id and  # Check if it's the same user who initiated
                r.message.id == admin_message.id and  # Check if it's the same message
                str(r.emoji) in ["1️⃣", "2️⃣", "3️⃣"]  # Check if it's one of our reactions
            )
        
        try:
            admin_reaction, _ = await bot.wait_for('reaction_add', timeout=60.0, check=admin_check)
            
            if str(admin_reaction.emoji) == "1️⃣":
                # Create new archetype
                await reaction.message.channel.send("Please enter the key cards for this archetype, separated by commas:")
                
                def key_cards_check(m):
                    return m.author.id == user.id and m.channel == reaction.message.channel
                
                key_cards_msg = await bot.wait_for('message', timeout=60.0, check=key_cards_check)
                key_cards = key_cards_msg.content.strip()
                
                # Insert new archetype
                archetype_response = supabase.table('deck_archetypes').insert({
                    "name": archetype_info['new_archetype'],
                    "key_cards": key_cards
                }).execute()
                
                new_archetype_id = archetype_response.data[0]['id']
                await reaction.message.channel.send(f"✅ Created new archetype: {archetype_info['new_archetype']}")
                
            elif str(admin_reaction.emoji) == "2️⃣":
                # Map to existing archetype
                archetypes_response = supabase.table('deck_archetypes').select("*").execute()
                archetypes = archetypes_response.data
                
                archetype_embed = discord.Embed(
                    title="Select Existing Archetype",
                    description="React with the number corresponding to the archetype:",
                    color=discord.Color.blue()
                )
                
                for i, archetype in enumerate(archetypes):
                    archetype_embed.add_field(name=f"{i+1}. {archetype['name']}", value="\u200b", inline=False)
                
                archetype_message = await reaction.message.channel.send(embed=archetype_embed)
                
                for i in range(len(archetypes)):
                    await archetype_message.add_reaction(f"{i+1}\u20e3")
                
                def archetype_check(r, u):
                    return (
                        u.id == user.id and
                        r.message.id == archetype_message.id and
                        r.emoji in [f"{i+1}\u20e3" for i in range(len(archetypes))]
                    )
                
                archetype_reaction, _ = await bot.wait_for('reaction_add', timeout=60.0, check=archetype_check)
                archetype_index = int(str(archetype_reaction.emoji)[0]) - 1
                new_archetype_id = archetypes[archetype_index]['id']
                await reaction.message.channel.send(f"✅ Mapped to existing archetype: {archetypes[archetype_index]['name']}")
                
            else:  # "3️⃣" - Keep as Others
                # Find the Others archetype ID
                others_response = supabase.table('deck_archetypes').select("*").eq('name', 'Others').execute()
                if others_response.data:
                    new_archetype_id = others_response.data[0]['id']
                    await reaction.message.channel.send("✅ Keeping archetype as 'Others'")
                else:
                    await reaction.message.channel.send("❌ Error: 'Others' archetype not found in database")
                    return
            
            # Update the match with the new archetype ID (for all cases)
            if 'match_id' in archetype_info:
                supabase.table('matches').update({
                    "opponent_archetype": archetype_info['new_archetype']
                }).eq("id", archetype_info['match_id']).execute()
            
            # Notify the user
            user_discord_id = int(archetype_info['user_id'])
            discord_user = bot.get_user(user_discord_id)
            if discord_user:
                await discord_user.send(f"Your match against archetype **{archetype_info['new_archetype']}** has been processed!")
            
            # Clean up
            del pending_archetype_updates[reaction.message.id]
            
        except asyncio.TimeoutError:
            await reaction.message.channel.send("❌ Response timeout. Please try again.")
            return

bot.run(DISCORD_TOKEN)
