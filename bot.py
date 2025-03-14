import discord
import asyncio
import os
import re
import json

from discord.ext import commands
from discord import Interaction

from supabase import create_client

from config import supabase, OWNER_ID, DISCORD_TOKEN, DISCORD_ALERT_CHANNEL 
#from models import Base, User, Deck, Match, DeckArchetype

from datetime import datetime, timezone

# Define intents
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.message_content = True

# Create bot instance with intents
bot = commands.Bot(command_prefix='!', intents=intents)

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


## ADMIN: ON CERTAIN EVENTS
@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return #Do not respond
    
    if reaction.message.id in pending_archetype_updates and str(reaction.emoji) == "✅":
        #Get the pending deck information
        deck_info = pending_archetype_updates[reaction.message.id]
        
        #Ask for new archetype name
        await reaction.message.channel.send(f"<@{user.id}>, please enter the new archetype name for **{deck_info['deck_name']}**:")
        
        def check(msg):
            return msg.author == user and msg.channel == reaction.message.channel
        
        # Wait for response from Admin
        archetype_msg = await bot.wait_for("message", check=check)
        new_archetype = archetype_msg.content.strip()

        # ✅ Check if the archetype already exists in the database
        existing_archetype_response = supabase.table('deck_archetypes').select("id").eq("name", new_archetype).execute()

        if existing_archetype_response.data:
            # ✅ Archetype exists → Use existing ID
            new_archetype_id = existing_archetype_response.data[0]['id']
            await reaction.message.channel.send(f"✅ Archetype **{new_archetype}** already exists. Assigning the deck to this archetype.")
        else:
            # ❌ Archetype doesn't exist → Insert a new entry
            await reaction.message.channel.send(f"🔄 Archetype **{new_archetype}** does not exist. Enter the key cards separated by commas:")
            key_cards_msg = await bot.wait_for("message", check=check)
            key_cards = key_cards_msg.content.strip()

            # Insert new archetype into the database
            archetype_insert_response = supabase.table('deck_archetypes').insert({
                "name": new_archetype,
                "key_cards": key_cards
            }).execute()
            new_archetype_id = archetype_insert_response.data[0]['id']

        # ✅ Update the deck with the correct archetype ID
        supabase.table('decks').update({"archetype_id": new_archetype_id}).eq("id", deck_info["deck_id"]).execute()

        # ✅ Fetch username from the database using the discord_id
        user_discord_id = int(deck_info["user_id"])  # Ensure it's an integer
        deck_submitter = bot.get_user(user_discord_id)  

        if not deck_submitter:
            print(f"❌ User {user_discord_id} not found in bot memory. Cannot send DM.")
        #To send the message from bot to user
        if deck_submitter:
            try:
                await deck_submitter.send(
                    f"📢 **Deck Update Notification** 📢\n"
                    f"Your deck **{deck_info['deck_name']}** has been updated to the archetype **{new_archetype}**.\n"
                    f"If you have any concerns, please contact an admin."
                )
                print(f"✅ Successfully sent DM to {deck_submitter.name}.")
            except discord.Forbidden:
                print(f"⚠️ Unable to DM {deck_submitter.name}. User may have DMs disabled.")

        # ✅ Log the update in the logs channel
        LOGS_CHANNEL_ID = DISCORD_ALERT_CHANNEL  # Replace with your logs channel ID
        logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
        
        if logs_channel:
            await logs_channel.send(
                f"📝 **Deck Archetype Update Logged** 📝\n"
                f"User: @{deck_submitter.name}\n"
                f"Deck Name: **{deck_info['deck_name']}**\n"
                f"Assigned Archetype: **{new_archetype}**\n"
                f"Updated by: <@{user.id}>"
            )

        # ✅ Remove pending entry
        del pending_archetype_updates[reaction.message.id]


bot.run(DISCORD_TOKEN)
