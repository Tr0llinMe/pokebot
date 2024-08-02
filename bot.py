import discord
from discord.ext import commands
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URI, OWNER_ID, DISCORD_TOKEN 
from models import Base, User, Deck, Match, DeckArchetype
import os
import re

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

@bot.command()
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

def normalize_text(text):
    return text.replace(' ', '').lower()

@bot.command()
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


@bot.command()
@commands.dm_only()
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

@bot.command()
async def log_match(ctx, deck_name, result, opponent_archetype):
    discord_id = str(ctx.author.id)
    session = Session()
    user = session.query(User).filter_by(discord_id=discord_id).first()
    if user:
        deck = session.query(Deck).filter_by(user_id=user.id, name=deck_name).first()
        if deck:
            new_match = Match(deck_id=deck.id, result=result, opponent_archetype=opponent_archetype, player=user.username)
            session.add(new_match)
            session.commit()
            await ctx.send(f'Match for deck "{deck_name}" with result "{result}" against archetype "{opponent_archetype}" logged.')
            print(f'Match for deck "{deck_name}" with result "{result}" against archetype "{opponent_archetype}" logged for user {user.username}.')
        else:
            await ctx.send('Deck not found.')
            print(f'Deck "{deck_name}" not found for user {user.username}.')
    else:
        await ctx.send('You need to register first.')
        print(f'User {ctx.author} needs to register first.')
        
                
@bot.command()
@commands.guild_only()
async def matchup_spread(ctx, archetype):
    session = Session()
    guild_id = ctx.guild.id
    users = session.query(User).all()
    user_ids = [user.id for user in users if user.discord_id in [str(member.id) for member in ctx.guild.members]]
    decks = session.query(Deck).filter(Deck.user_id.in_(user_ids), Deck.archetype == archetype).all()
    deck_ids = [deck.id for deck in decks]
    matches = session.query(Match).filter(Match.deck_id.in_(deck_ids)).all()
    
    if matches:
        wins = sum(1 for match in matches if match.result.lower() in ['win','won'])
        losses = sum(1 for match in matches if match.result.lower() in ['lose', 'lost'])
        response = f'Matchup spread for archetype "{archetype}": {wins} wins and {losses} losses.\n\n'
        response += 'Detailed matchups:\n'
        for match in matches:
            response += f'Player: {match.player}, Deck: {match.deck.name}, Result: {match.result}, Opponent Archetype: {match.opponent_archetype}\n'
        await ctx.send(response)
        print(f'Provided matchup spread for archetype "{archetype}".')
    else:
        await ctx.send(f'No matches found for archetype "{archetype}".')
        print(f'No matches found for archetype "{archetype}".')

bot.run(DISCORD_TOKEN)
