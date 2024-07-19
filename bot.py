import discord
from discord.ext import commands
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URI 
from models import Base, User, Deck, Match
from dotenv import load_dotenv
import os

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
@commands.dm_only()
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

@bot.command()
@commands.dm_only()
async def add_deck(ctx, deck_name, archetype):
    discord_id = str(ctx.author.id)
    session = Session()
    user = session.query(User).filter_by(discord_id=discord_id).first()
    if user:
        new_deck = Deck(user_id=user.id, name=deck_name, archetype=archetype)
        session.add(new_deck)
        session.commit()
        await ctx.send(f'Deck "{deck_name}" with archetype "{archetype}" has been added.')
        print(f'Deck "{deck_name}" with archetype "{archetype}" added for user {user.username}.')
    else:
        await ctx.send('You need to register first.')
        print(f'User {ctx.author} needs to register first.')

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

bot_token = os.getenv('DISCORD_TOKEN')
bot.run(bot_token)
