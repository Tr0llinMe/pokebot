import discord
from discord.ext import commands
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import supabase, OWNER_ID, DISCORD_TOKEN 
from models import Base, User, Deck, Match, DeckArchetype
import asyncio
import os
import re
from datetime import datetime

# Define intents
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.message_content = True

# Create bot instance with intents
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'Bot is ready. Logged in as {bot.user}')

def normalize_text(text):
    return text.replace(' ', '').lower()

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
async def add(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send('Please specify a subcommand for user, e.g., "!add deck".')

@add.command(name='deck')
@commands.dm_only()
async def add_deck(ctx, deck_name=None, deck_file: discord.Attachment = None):
    discord_id = str(ctx.author.id)

    # Check if user is registered
    user_response = supabase.table('users').select("*").eq('discord_id', discord_id).execute()
    if not user_response.data:
        await ctx.send('You need to register first.')
        return

    if not deck_name:
        await ctx.send('Please provide a deck name using the format `!add deck <deck_name>`.')
        return

    # Get archetypes
    archetype_response = supabase.table('deck_archetypes').select("*").execute()
    archetype_names = [archetype['name'] for archetype in archetype_response.data]

    if deck_file is None:
        await ctx.send(f'Please provide a deck text file or choose from the available archetypes: {", ".join(archetype_names)}.')
        return

    # Save the deck file
    upload_dir = 'uploads'
    os.makedirs(upload_dir, exist_ok=True)
    sanitized_deck_name = re.sub(r'\W+', '_', deck_name)
    file_path = os.path.join(upload_dir, f"{discord_id}_{sanitized_deck_name}.txt")
    await deck_file.save(file_path)

    # Read and process the deck file
    with open(file_path, 'r') as file:
        deck_content = file.read()

    # Extract card names
    cards = re.findall(r'\d+ ([\w\s{}]+)', deck_content)
    cards = [normalize_text(card) for card in cards]

    # Identify archetype
    identified_archetype = 'Others'
    for archetype in archetype_response.data:
        archetype_cards = [normalize_text(card) for card in archetype['key_cards'].split(',')]
        if all(any(ac in card for card in cards) for ac in archetype_cards):
            identified_archetype = archetype['name']
            break

    # Ensure "Others" archetype exists
    others_archetype = supabase.table('deck_archetypes').select("*").eq('name', 'Others').execute()
    if not others_archetype.data:
        supabase.table('deck_archetypes').insert({"name": "Others", "key_cards": ""}).execute()

    # Add the deck to the database
    user_id = user_response.data[0]['id']
    archetype_entry = next((a for a in archetype_response.data if a['name'] == identified_archetype), None)
    supabase.table('decks').insert({
        "user_id": user_id,
        "name": deck_name,
        "archetype_id": archetype_entry['id'] if archetype_entry else None
    }).execute()

    await ctx.send(f'Deck "{deck_name}" has been added with the identified archetype "{identified_archetype}".')

@add.command(name='archetype')
@commands.dm_only()
async def add_archetype(ctx):
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
    response = supabase.table('deck_archetypes').insert({
        "name": archetype_name.content,
        "key_cards": ','.join(key_cards)
    }).execute()

    if response.error:
        await ctx.send('An error occurred while adding the archetype. Please try again later.')
        print(f"Error adding archetype: {response.error}")
    else:
        await ctx.send(f'Archetype "{archetype_name.content}" has been added with key cards: {", ".join(key_cards)}')

### MATCH GROUP ###
@bot.group()
async def match(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send('Please specify a subcommand for user, e.g., "!match log".')

@match.command(name='log')
async def log_match(ctx, deck_name, result):
    discord_id = str(ctx.author.id)

    # Check if the user is registered
    user_response = supabase.table('users').select("*").eq('discord_id', discord_id).execute()
    if not user_response.data:
        await ctx.send('You need to register first.')
        return

    user = user_response.data[0]  # Get the user object

    # Check if the deck exists for the user
    deck_response = supabase.table('decks').select("*").eq('user_id', user['id']).eq('name', deck_name).execute()
    if not deck_response.data:
        await ctx.send('Deck not found.')
        return

    deck = deck_response.data[0]  # Get the deck object

    # Standardize the result input
    win_conditions = ['won', 'win', '1']
    loss_conditions = ['lost', 'lose', '2']
    if result.lower() in win_conditions:
        standardized_result = 'Win'
    elif result.lower() in loss_conditions:
        standardized_result = 'Loss'
    else:
        await ctx.send('Invalid result. Please enter "won", "win", "lost", "lose", "1", or "2".')
        return

    # Retrieve archetypes from the database
    archetypes_response = supabase.table('deck_archetypes').select("*").execute()
    archetypes = archetypes_response.data
    archetype_names = [archetype['name'] for archetype in archetypes if archetype['name'] != 'Others']
    archetype_names.append('Others')  # Ensure "Others" is the last option

    # Prompt the user to select an opponent archetype
    await ctx.send(f'Please select the opponent archetype:\n' +
                   '\n'.join(f'{i + 1}. {name}' for i, name in enumerate(archetype_names)))

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        msg = await bot.wait_for('message', check=check, timeout=60.0)
        selected_index = int(msg.content) - 1
        if 0 <= selected_index < len(archetype_names):
            opponent_archetype = archetype_names[selected_index]
        else:
            await ctx.send('Invalid selection. Please try logging the match again.')
            return
    except ValueError:
        await ctx.send('Invalid input. Please enter the number corresponding to the archetype.')
        return
    except asyncio.TimeoutError:
        await ctx.send('You took too long to respond. Please try logging the match again.')
        return

    # Get the current date
    current_date = datetime.now().strftime('%Y-%m-%d')

    # Log the match in the database
    match_response = supabase.table('matches').insert({
        "deck_id": deck['id'],
        "result": standardized_result,
        "opponent_archetype": opponent_archetype,
        "player": user['username'],
        "date": current_date
    }).execute()

    if match_response.error:
        await ctx.send('An error occurred while logging the match. Please try again later.')
        print(f"Error logging match: {match_response.error}")
    else:
        await ctx.send(f'Match for deck "{deck_name}" with result "{standardized_result}" against archetype "{opponent_archetype}" logged on {current_date}.')
        print(f'Match for deck "{deck_name}" with result "{standardized_result}" against archetype "{opponent_archetype}" logged for user {user["username"]} on {current_date}.')
        
                
@match.command(name='history')
@commands.guild_only()
async def matchup_history(ctx, archetype):
    guild_id = ctx.guild.id

    # Get all users from the guild
    guild_members = [str(member.id) for member in ctx.guild.members]
    users_response = supabase.table('users').select("*").execute()

    if not users_response.data:
        await ctx.send(f"No users are registered.")
        return

    # Filter users who are members of the guild
    user_ids = [user['id'] for user in users_response.data if user['discord_id'] in guild_members]

    if not user_ids:
        await ctx.send(f"No registered users found in this guild.")
        return

    # Get decks matching the archetype and users in the guild
    decks_response = supabase.table('decks').select("*").eq("archetype_id", archetype).in_("user_id", user_ids).execute()

    if not decks_response.data:
        await ctx.send(f"No decks found for archetype '{archetype}'.")
        return

    deck_ids = [deck['id'] for deck in decks_response.data]

    # Get matches related to the filtered decks
    matches_response = supabase.table('matches').select("*").in_("deck_id", deck_ids).execute()

    if not matches_response.data:
        await ctx.send(f"No matches found for archetype '{archetype}'.")
        return

    matches = matches_response.data

    # Calculate wins and losses
    wins = sum(1 for match in matches if match['result'] == 'Win')
    losses = sum(1 for match in matches if match['result'] == 'Loss')

    # Prepare the response message
    response = f'Matchup history for archetype "{archetype}": {wins} wins and {losses} losses.\n\n'
    response += 'Detailed matchups:\n'
    for match in matches:
        response += f'Player: {match["player"]}, Result: {match["result"]}, Opponent Archetype: {match["opponent_archetype"]}\n'

    # Send the response to the user
    await ctx.send(response)
    print(f'Provided matchup history for archetype "{archetype}".')
        
        
### TOOL GROUP ###
@bot.group()
async def tool(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send('Please specify a subcommand for user, e.g., "!tool mully".')
        
#@tool.command(name='mully')

bot.run(DISCORD_TOKEN)
