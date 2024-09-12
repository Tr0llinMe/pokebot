import discord
from discord.ext import commands
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URI, OWNER_ID, DISCORD_TOKEN 
from models import Base, User, Deck, Match, DeckArchetype
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

engine = create_engine(DATABASE_URI)
Session = sessionmaker(bind=engine)

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
    session = Session()
    user = session.query(User).filter_by(discord_id=discord_id).first()
    if user:
        await ctx.send('You are already registered.')
    else:
        new_user = User(discord_id=discord_id, username=username)
        session.add(new_user)
        session.commit()
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
    session = Session()
    user = session.query(User).filter_by(discord_id=discord_id).first()

    if not user:
        await ctx.send('You need to register first.')
        return

    if not deck_name:
        await ctx.send('Please provide a deck name using the format `!add_deck <deck_name>`.')
        return

    archetypes = session.query(DeckArchetype).all()
    archetype_names = [archetype.name for archetype in archetypes]

    if deck_file is None:
        await ctx.send(f'Please provide a deck text file or choose from the available archetypes: {", ".join(archetype_names)}.')
        return

    # Define the upload directory and ensure it exists
    upload_dir = 'uploads'
    os.makedirs(upload_dir, exist_ok=True)

    # Create a filename using user ID and deck name
    sanitized_deck_name = re.sub(r'\W+', '_', deck_name)  # Replace non-alphanumeric characters with underscores
    filename = f"{discord_id}_{sanitized_deck_name}.txt"
    file_path = os.path.join(upload_dir, filename)

    # Save the deck file to the uploads directory
    await deck_file.save(file_path)

    # Read the deck file
    with open(file_path, 'r') as file:
        deck_content = file.read()

    # Extract card names from the deck file
    cards = re.findall(r'\d+ ([\w\s{}]+)', deck_content)
    cards = [normalize_text(card) for card in cards]

    # Identify the archetype
    identified_archetype = 'Others'
    for archetype in archetypes:
        archetype_cards = [normalize_text(card) for card in archetype.key_cards.split(',')]
        if all(any(ac in card for card in cards) for ac in archetype_cards):
            identified_archetype = archetype.name
            break

    # Ensure "Others" archetype exists
    others_archetype = session.query(DeckArchetype).filter_by(name='Others').first()
    if others_archetype is None:
        others_archetype = DeckArchetype(name='Others', key_cards='')
        session.add(others_archetype)
        session.commit()

    # Get the archetype ID
    archetype_entry = session.query(DeckArchetype).filter_by(name=identified_archetype).first()
    if archetype_entry is None:
        archetype_entry = others_archetype

    # Add the deck to the database
    new_deck = Deck(user_id=user.id, name=deck_name, archetype_id=archetype_entry.id)
    session.add(new_deck)
    session.commit()

    await ctx.send(f'Deck "{deck_name}" has been added with the identified archetype "{identified_archetype}".')

@add.command(name='archetype')
async def add_archetype(ctx):
    if str(ctx.author.id) != OWNER_ID:
        await ctx.send('You are not authorized to add archetypes.')
        return

    await ctx.send('Please enter the archetype name:')
    
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    archetype_name = await bot.wait_for('message', check=check)
    
    await ctx.send('Please enter the key cards for the archetype, separated by commas:')
    key_cards_message = await bot.wait_for('message', check=check)
    
    key_cards = key_cards_message.content.split(',')
    key_cards = [card.strip() for card in key_cards]

    session = Session()
    new_archetype = DeckArchetype(name=archetype_name.content, key_cards=','.join(key_cards))
    session.add(new_archetype)
    session.commit()
    
    await ctx.send(f'Archetype "{archetype_name.content}" has been added with key cards: {", ".join(key_cards)}')

### MATCH GROUP ###
@bot.group()
async def add(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send('Please specify a subcommand for user, e.g., "!match log".')

@match.command(name='log')
async def log_match(ctx, deck_name, result):
    discord_id = str(ctx.author.id)
    session = Session()
    user = session.query(User).filter_by(discord_id=discord_id).first()

    if not user:
        await ctx.send('You need to register first.')
        return

    deck = session.query(Deck).filter_by(user_id=user.id, name=deck_name).first()
    if not deck:
        await ctx.send('Deck not found.')
        return

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

    # Retrieve archetype options from the database
    archetypes = session.query(DeckArchetype).order_by(DeckArchetype.name).all()
    archetype_names = [archetype.name for archetype in archetypes if archetype.name != 'Others']
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
    current_date = datetime.now().strftime('%m-%d-%Y')

    # Log the match in the database
    new_match = Match(deck_id=deck.id, result=standardized_result, opponent_archetype=opponent_archetype, player=user.username, date=current_date)
    session.add(new_match)
    session.commit()

    await ctx.send(f'Match for deck "{deck_name}" with result "{standardized_result}" against archetype "{opponent_archetype}" logged on {current_date}.')
    print(f'Match for deck "{deck_name}" with result "{standardized_result}" against archetype "{opponent_archetype}" logged for user {user.username} on {current_date}.')
        
                
@match.command(name='history')
@commands.guild_only()
async def matchup_history(ctx, archetype):
    session = Session()
    guild_id = ctx.guild.id

    # Get users from the guild
    users = session.query(User).all()
    user_ids = [user.id for user in users if user.discord_id in [str(member.id) for member in ctx.guild.members]]
    
    # Get decks that match the provided archetype
    decks = session.query(Deck).filter(Deck.user_id.in_(user_ids), Deck.archetype == archetype).all()
    deck_ids = [deck.id for deck in decks]
    
    # Get matches related to the filtered decks
    matches = session.query(Match).filter(Match.deck_id.in_(deck_ids)).all()

    if matches:
        # Calculate wins and losses (assuming "Win" and "Loss" are the only possible values)
        wins = sum(1 for match in matches if match.result == 'Win')
        losses = sum(1 for match in matches if match.result == 'Loss')

        # Prepare response message
        response = f'Matchup history for archetype "{archetype}": {wins} wins and {losses} losses.\n\n'
        response += 'Detailed matchups:\n'
        for match in matches:
            response += f'Player: {match.player}, Result: {match.result}, Opponent Archetype: {match.opponent_archetype}\n'
        
        # Send the response to the user
        await ctx.send(response)
        print(f'Provided matchup history for archetype "{archetype}".')
    else:
        await ctx.send(f'No matches found for archetype "{archetype}".')
        print(f'No matches found for archetype "{archetype}".')

bot.run(DISCORD_TOKEN)
