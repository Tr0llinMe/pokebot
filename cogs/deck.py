import os
import discord
from discord.ext import commands
from datetime import datetime, timezone
import json

from database.supabase import UserRepository, DeckRepository, ArchetypeRepository
from utils.deck_parser import extract_card_names, identify_archetype, format_decklist
from utils.events import pending_archetype_updates

class DeckCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group()
    async def deck(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send('Please specify a subcommand for deck, e.g., "!deck add".')

    @deck.command(name='add')
    @commands.dm_only()
    async def deck_add(self, ctx, deck_name: str = None):
        """Add a new deck to your collection."""
        if not deck_name:
            await ctx.send('Please provide a deck name using the format `!deck add <deck_name>`.')
            return

        # Check if user is registered
        discord_id = str(ctx.author.id)
        user = UserRepository.get_user(discord_id)
        if not user:
            await ctx.send('You need to register first.')
            return

        # Ask for deck input method
        await ctx.send('Would you like to upload a file or paste the decklist? Reply with `file` or `text`.')
        
        def check(msg):
            return msg.author == ctx.author and msg.channel == ctx.channel

        try:
            choice_msg = await self.bot.wait_for("message", check=check, timeout=60.0)
            choice = choice_msg.content.lower().strip()
        except TimeoutError:
            await ctx.send("You took too long to respond. Please try again.")
            return

        deck_content = None
        upload_dir = 'uploads'
        os.makedirs(upload_dir, exist_ok=True)
        sanitized_deck_name = ''.join(c for c in deck_name if c.isalnum() or c in (' ', '_'))
        file_path = os.path.join(upload_dir, f"{discord_id}_{sanitized_deck_name}.txt")

        if choice == "file":
            try:
                await ctx.send("Please upload your deck file.")
                file_msg = await self.bot.wait_for("message", check=check, timeout=120.0)
                if not file_msg.attachments:
                    await ctx.send("No file detected. Please try again.")
                    return

                deck_file = file_msg.attachments[0]
                await deck_file.save(file_path)
                with open(file_path, 'r') as file:
                    deck_content = file.read()
            except TimeoutError:
                await ctx.send("You took too long to upload the file. Please try again.")
                return

        elif choice == "text":
            try:
                await ctx.send("Please paste your decklist (one card per line).")
                deck_msg = await self.bot.wait_for("message", check=check, timeout=180.0)
                deck_content = deck_msg.content
                with open(file_path, "w") as file:
                    file.write(deck_content)
            except TimeoutError:
                await ctx.send("You took too long to paste the decklist. Please try again.")
                return
        else:
            await ctx.send("Invalid option. Please use `file` or `text`.")
            return

        if not deck_content:
            await ctx.send("Deck content is empty. Please try again.")
            return

        # Process deck content
        cards = extract_card_names(deck_content)
        archetypes = ArchetypeRepository.get_all_archetypes()
        identified_archetype = identify_archetype(cards, archetypes)

        # Find archetype ID
        archetype_entry = next((a for a in archetypes if a['name'] == identified_archetype), None)
        if not archetype_entry:
            await ctx.send("Error: Could not identify deck archetype.")
            return

        # Create deck data
        deck_data = {
            "name": deck_name,
            "archetype": identified_archetype,
            "cards": deck_content.split("\n"),
            "last_modified": datetime.now(timezone.utc).isoformat()
        }

        # Save deck to database
        try:
            deck = DeckRepository.create_deck(
                user_id=user['id'],
                name=deck_name,
                archetype_id=archetype_entry['id'],
                decklist=deck_data
            )
            await ctx.send(f'Deck "{deck_name}" has been added with the identified archetype "{identified_archetype}".')

            # Notify admins if deck is classified as "Others"
            if identified_archetype == "Others":
                alert_channel = self.bot.get_channel(int(os.getenv('DISCORD_ALERT_CHANNEL')))
                if alert_channel:
                    deck_file = discord.File(file_path, filename=f"{deck_name}.txt")
                    alert_embed = discord.Embed(
                        title="🚨 Unrecognized Deck Submission",
                        description=f"User: <@{discord_id}>\nDeck Name: **{deck_name}**\nArchetype set to **'Others'**. Click ✅ to categorize.",
                        color=discord.Color.orange()
                    )
                    alert_message = await alert_channel.send(embed=alert_embed, file=deck_file)
                    await alert_message.add_reaction("✅")
                    
                    # Store for admin processing
                    pending_archetype_updates[alert_message.id] = {
                        "deck_id": deck['id'],
                        "user_id": discord_id,
                        "deck_name": deck_name,
                        "new_archetype": identified_archetype
                    }

        except Exception as e:
            print(f"Error creating deck: {e}")
            await ctx.send("❌ An error occurred while saving your deck. Please try again later.")

    @deck.command(name='box')
    async def box(self, ctx):
        """View all your saved decks."""
        discord_id = str(ctx.author.id)
        user = UserRepository.get_user(discord_id)
        if not user:
            await ctx.send("❌ You are not registered in the system. Please add a deck first.")
            return

        decks = DeckRepository.get_user_decks(user['id'])
        if not decks:
            await ctx.send("You don't have any saved decks yet.")
            return

        response = "**Your Saved Decks:**\n"
        for deck in decks:
            try:
                deck_data = json.loads(deck["decklist"])
                # Get the last_modified timestamp from the deck data
                last_modified = deck_data.get('last_modified')
                if last_modified:
                    # Convert ISO format to datetime
                    date_obj = datetime.fromisoformat(last_modified)
                    # Format to a more readable string
                    readable_date = date_obj.strftime('%B %d, %Y at %I:%M %p')
                    response += f"- **{deck_data['name']}** - {deck_data['archetype']} (ID: {deck['id']})\n"
                    response += f"  🕒 Last Modified: {readable_date}\n"
                else:
                    response += f"- **{deck_data['name']}** - {deck_data['archetype']} (ID: {deck['id']})\n"
            except json.JSONDecodeError:
                response += f"- **{deck['name']}** (ID: {deck['id']})\n"

        response += "\nType `!deck viewbox <ID>` to see a specific decklist."
        await ctx.send(response)

    @deck.command(name='viewbox')
    async def viewbox(self, ctx, deck_id: int):
        """View a specific deck by its ID."""
        discord_id = str(ctx.author.id)
        user = UserRepository.get_user(discord_id)
        if not user:
            await ctx.send("❌ You are not registered in the system. Please add a deck first.")
            return

        deck = DeckRepository.get_deck(deck_id, user['id'])
        if not deck:
            await ctx.send("❌ Deck not found.")
            return

        try:
            deck_data = json.loads(deck['decklist'])
            # Get the last_modified timestamp from the deck data
            last_modified = deck_data.get('last_modified')
            if last_modified:
                # Convert ISO format to datetime
                date_obj = datetime.fromisoformat(last_modified)
                # Format to a more readable string
                readable_date = date_obj.strftime('%B %d, %Y at %I:%M %p')
                response = f"📜 **{deck_data['name']}** - {deck_data['archetype']} 📜\n"
                response += f"🕒 Last Modified: {readable_date}\n"
                response += "```" + "\n".join(deck_data["cards"]) + "```"
            else:
                response = f"📜 **{deck_data['name']}** - {deck_data['archetype']} 📜\n"
                response += "```" + "\n".join(deck_data["cards"]) + "```"
            await ctx.send(response)
        except json.JSONDecodeError:
            await ctx.send(f"**{deck['name']}**\n```{deck['decklist']}```")

async def setup(bot):
    await bot.add_cog(DeckCommands(bot)) 