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
        if result_reaction.emoji == "✅":
            result = "Win"
        elif result_reaction.emoji == "❌":
            result = "Loss"
        else:
            result = "Tie"
        
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
            done, pending = await asyncio.wait([
                bot.wait_for('reaction_add', timeout=60.0, check=archetype_check),
                bot.wait_for('message', timeout=60.0, check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
            ], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                result = task.result()
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
        # Now use main_archetypes[archetype_index]['name']
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
        
        done = False
        while not done:
            try:
                done, pending = await asyncio.wait([
                    bot.wait_for('message', timeout=60.0, check=notes_check),
                    bot.wait_for('reaction_add', timeout=60.0, check=lambda r, u: u == ctx.author and r.message.id == notes_message.id and str(r.emoji) == "❌")
                ], return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    result = task.result()
                    if isinstance(result, tuple):  # reaction
                        notes = None
                        done = True
                    else:  # message
                        notes = result.content
                        done = True
            except asyncio.TimeoutError:
                notes = None
                done = True
        
        # Log the match
        current_date = datetime.now().strftime('%Y-%m-%d')
        match_data = {
            "deck_id": selected_deck['id'],
            "result": result,
            "opponent_archetype": opponent_archetype,
            "player": ctx.author.name,
            "date": current_date,
            "notes": notes
        }
        
        try:
            match_response = supabase.table('matches').insert(match_data).execute()
            
            success_embed = discord.Embed(
                title="Match Logged Successfully!",
                description=f"Deck: {selected_deck['name']}\nResult: {result}\nOpponent: {opponent_archetype}\nDate: {current_date}",
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
                    alert_embed.add_field(name="Match Result", value=result, inline=True)
                    alert_message = await channel.send(embed=alert_embed)
                    await alert_message.add_reaction("✅")
                    
                    # Store the alert message ID for later reference
                    pending_archetype_updates[alert_message.id] = {
                        "user_id": discord_id,
                        "deck_id": selected_deck['id'],
                        "deck_name": selected_deck['name'],
                        "new_archetype": opponent_archetype,
                        "match_id": match_response.data[0]['id']  # Store the match ID for updating
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
    archetypes = [a['name'] for a in archetypes_response.data]
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

    # Step 6: Format output
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
        # Get the pending archetype information
        archetype_info = pending_archetype_updates[reaction.message.id]
        
        # Ask admin to either create new archetype or select existing one
        admin_embed = discord.Embed(
            title="Archetype Request Response",
            description=f"User requested archetype: **{archetype_info['new_archetype']}**\n\n"
                       f"1️⃣ Create new archetype\n"
                       f"2️⃣ Map to existing archetype",
            color=discord.Color.blue()
        )
        admin_message = await reaction.message.channel.send(embed=admin_embed)
        await admin_message.add_reaction("1️⃣")
        await admin_message.add_reaction("2️⃣")
        
        def admin_check(reaction, user):
            return user == reaction.message.author and reaction.message.id == admin_message.id and str(reaction.emoji) in ["1️⃣", "2️⃣"]
        
        try:
            admin_reaction, _ = await bot.wait_for('reaction_add', timeout=60.0, check=admin_check)
            
            if str(admin_reaction.emoji) == "1️⃣":
                # Create new archetype
                await reaction.message.channel.send("Please enter the key cards for this archetype, separated by commas:")
                
                def key_cards_check(m):
                    return m.author == user and m.channel == reaction.message.channel
                
                key_cards_msg = await bot.wait_for('message', timeout=60.0, check=key_cards_check)
                key_cards = key_cards_msg.content.strip()
                
                # Insert new archetype
                archetype_response = supabase.table('deck_archetypes').insert({
                    "name": archetype_info['new_archetype'],
                    "key_cards": key_cards
                }).execute()
                
                new_archetype_id = archetype_response.data[0]['id']
                
            else:
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
                
                def archetype_check(reaction, user):
                    return user == reaction.message.author and reaction.message.id == archetype_message.id and reaction.emoji in [f"{i+1}\u20e3" for i in range(len(archetypes))]
                
                archetype_reaction, _ = await bot.wait_for('reaction_add', timeout=60.0, check=archetype_check)
                archetype_index = int(archetype_reaction.emoji[0]) - 1
                new_archetype_id = archetypes[archetype_index]['id']
            
            # Update the match with the new archetype
            supabase.table('matches').update({
                "opponent_archetype": archetype_info['new_archetype']
            }).eq("id", archetype_info['match_id']).execute()
            
            # Notify the user
            user_discord_id = int(archetype_info['user_id'])
            user = bot.get_user(user_discord_id)
            if user:
                await user.send(f"Your match against archetype **{archetype_info['new_archetype']}** has been updated!")
            
            # Clean up
            del pending_archetype_updates[reaction.message.id]
            
        except asyncio.TimeoutError:
            await reaction.message.channel.send("You took too long to respond. Please try again later.")

bot.run(DISCORD_TOKEN)
