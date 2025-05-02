import discord
from discord.ext import commands
import asyncio
from datetime import datetime
import io
import os
import json

from database.supabase import UserRepository, DeckRepository, ArchetypeRepository, MatchRepository
from utils.image import create_matchup_image

class MatchCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pending_archetype_updates = {}  # {message_id: {"user_id": str, "deck_id": int, "match_id": int}}

    @commands.group()
    async def match(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send('Please specify a subcommand for match, e.g., "!match log".')

    @match.command(name='log')
    async def log_match(self, ctx):
        """Log a new match result."""
        discord_id = str(ctx.author.id)
        user = UserRepository.get_user(discord_id)
        if not user:
            await ctx.send('❌ You need to register first.')
            return

        # Get user's decks
        decks = DeckRepository.get_user_decks(user['id'])
        if not decks:
            await ctx.send('❌ You need to add a deck first.')
            return

        # Create deck selection embed
        embed = discord.Embed(
            title="Select Your Deck",
            description="Type the number corresponding to your deck:",
            color=discord.Color.blue()
        )
        
        for i, deck in enumerate(decks):
            try:
                deck_data = json.loads(deck['decklist'])
                embed.add_field(name=f"{i+1}. {deck_data['name']}", value="\u200b", inline=False)
            except json.JSONDecodeError:
                embed.add_field(name=f"{i+1}. {deck['name']}", value="\u200b", inline=False)
        
        await ctx.send(embed=embed)
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            reply = await self.bot.wait_for('message', check=check, timeout=60.0)
            try:
                deck_index = int(reply.content.strip()) - 1
                if deck_index < 0 or deck_index >= len(decks):
                    await ctx.send("❌ Invalid deck selection.")
                    return
                selected_deck = decks[deck_index]
            except ValueError:
                await ctx.send("❌ Please enter a valid number.")
                return
            
            # Ask for match result
            result_embed = discord.Embed(
                title="Match Result",
                description="React with ✅ for Win, ❌ for Loss, or ➖ for Tie",
                color=discord.Color.blue()
            )
            result_message = await ctx.send(embed=result_embed)
            await result_message.add_reaction("✅")
            await result_message.add_reaction("❌")
            await result_message.add_reaction("➖")
            
            def result_check(reaction, user):
                return (user == ctx.author and 
                       reaction.message.id == result_message.id and 
                       str(reaction.emoji) in ["✅", "❌", "➖"])
            
            result_reaction, _ = await self.bot.wait_for('reaction_add', timeout=60.0, check=result_check)
            match_result = {
                "✅": "Win",
                "❌": "Loss",
                "➖": "Tie"
            }.get(str(result_reaction.emoji))
            
            if not match_result:
                await ctx.send("❌ Invalid result selection. Please try again.")
                return
            
            # Get archetypes for opponent selection
            archetypes = ArchetypeRepository.get_all_archetypes()
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
                return (user == ctx.author and 
                       reaction.message.id == archetype_message.id and 
                       str(reaction.emoji) in [f"{i+1}\u20e3" for i in range(len(main_archetypes))])
            
            try:
                # Create tasks for both message and reaction
                message_task = asyncio.create_task(
                    self.bot.wait_for('message', 
                                    timeout=60.0, 
                                    check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
                )
                reaction_task = asyncio.create_task(
                    self.bot.wait_for('reaction_add', 
                                    timeout=60.0, 
                                    check=archetype_check)
                )
                
                # Wait for either task to complete
                done, pending = await asyncio.wait(
                    [message_task, reaction_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                
                # Process the completed task
                completed_task = done.pop()
                result = await completed_task
                
                if isinstance(result, tuple):  # reaction
                    archetype_index = int(str(result[0].emoji)[0]) - 1
                else:  # message
                    try:
                        archetype_index = int(result.content.strip()) - 1
                    except ValueError:
                        await ctx.send("❌ Invalid archetype selection.")
                        return
                
                if archetype_index < 0 or archetype_index >= len(main_archetypes):
                    await ctx.send("❌ Invalid archetype selection.")
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
                
                try:
                    # Create tasks for both message and reaction
                    message_task = asyncio.create_task(
                        self.bot.wait_for('message', 
                                        timeout=60.0, 
                                        check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
                    )
                    reaction_task = asyncio.create_task(
                        self.bot.wait_for('reaction_add', 
                                        timeout=60.0, 
                                        check=lambda r, u: u == ctx.author and r.message.id == notes_message.id and str(r.emoji) == "❌")
                    )
                    
                    done, pending = await asyncio.wait(
                        [message_task, reaction_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    for task in pending:
                        task.cancel()
                    
                    completed_task = done.pop()
                    result = await completed_task
                    
                    notes = None if isinstance(result, tuple) else str(result.content)
                    
                    # Log the match
                    match = MatchRepository.create_match(
                        deck_id=selected_deck['id'],
                        result=match_result,
                        opponent_archetype=opponent_archetype,
                        player=str(ctx.author.name),
                        notes=notes
                    )
                    
                    # Send success message
                    success_embed = discord.Embed(
                        title="Match Logged Successfully!",
                        description=f"Deck: {selected_deck['name']}\n"
                                  f"Result: {match_result}\n"
                                  f"Opponent: {opponent_archetype}\n"
                                  f"Date: {datetime.now().strftime('%Y-%m-%d')}",
                        color=discord.Color.green()
                    )
                    if notes:
                        success_embed.add_field(name="Notes", value=notes, inline=False)
                    
                    await ctx.send(embed=success_embed)
                    
                    # If opponent archetype was "Others", notify admins
                    if opponent_archetype == "Others":
                        alert_channel = self.bot.get_channel(int(os.getenv('DISCORD_ALERT_CHANNEL')))
                        if alert_channel:
                            alert_embed = discord.Embed(
                                title="New Archetype Request",
                                description=f"User: **{ctx.author.name}** (<@{discord_id}>)\n"
                                          f"Requested archetype: **{opponent_archetype}**",
                                color=discord.Color.orange()
                            )
                            alert_embed.add_field(name="Match Result", value=match_result, inline=True)
                            alert_message = await alert_channel.send(embed=alert_embed)
                            await alert_message.add_reaction("✅")
                            
                            # Store for admin processing
                            from util.events import pending_archetype_updates
                            pending_archetype_updates[alert_message.id] = {
                                "user_id": str(discord_id),
                                "match_id": match['id'],
                                "new_archetype": opponent_archetype
                            }
                    
                except asyncio.TimeoutError:
                    await ctx.send("❌ You took too long to provide notes. Match not logged.")
                    return
                
            except asyncio.TimeoutError:
                await ctx.send("❌ You took too long to select an archetype. Please try logging the match again.")
                return
            
        except asyncio.TimeoutError:
            await ctx.send("❌ You took too long to select a deck. Please try logging the match again.")
            return

    @match.command(name='history')
    @commands.guild_only()
    async def matchup_history(self, ctx):
        """View matchup history for an archetype."""
        # Get all archetypes
        archetypes = ArchetypeRepository.get_all_archetypes()
        archetypes_list = [a['name'] for a in archetypes if a['name'] != 'Others']
        archetypes_list.append('Others')  # Add Others at the end
        
        msg = "Which archetype do you want a matchup history for?\n"
        msg += "\n".join(f"{i+1}. {name}" for i, name in enumerate(archetypes_list))
        await ctx.send(msg)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            reply = await self.bot.wait_for('message', check=check, timeout=60.0)
            try:
                idx = int(reply.content.strip()) - 1
                if idx < 0 or idx >= len(archetypes_list):
                    await ctx.send("❌ Invalid selection.")
                    return
                selected_archetype = archetypes_list[idx]
            except ValueError:
                await ctx.send("❌ Please enter a valid number.")
                return

            # Get all users in the guild
            guild_members = [str(member.id) for member in ctx.guild.members]
            users = [user for user in UserRepository.get_all_users() 
                    if user['discord_id'] in guild_members]
            user_ids = [user['id'] for user in users]

            # Get all decks of the selected archetype
            selected_archetype_id = next(a['id'] for a in archetypes if a['name'] == selected_archetype)
            decks = [deck for deck in DeckRepository.get_decks_by_archetype(selected_archetype_id)
                    if deck['user_id'] in user_ids]

            if not decks:
                await ctx.send("No decks found for that archetype.")
                return

            # Get all matches for those decks
            matches = []
            for deck in decks:
                matches.extend(MatchRepository.get_matches_by_deck(deck['id']))

            # Aggregate by opponent archetype
            summary = {}
            for match in matches:
                opp = match['opponent_archetype']
                if opp not in summary:
                    summary[opp] = {'Win': 0, 'Loss': 0, 'Tie': 0}
                summary[opp][match['result']] += 1

            # Generate text output
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
            
            # Generate and send image
            img = create_matchup_image(summary, selected_archetype)
            if img:
                with io.BytesIO() as image_binary:
                    img.save(image_binary, 'PNG')
                    image_binary.seek(0)
                    await ctx.send(file=discord.File(image_binary, f'{selected_archetype}_matchups.png'))
            else:
                await ctx.send("No matchup data available to generate image.")

        except asyncio.TimeoutError:
            await ctx.send("❌ You took too long to respond.")
            return

async def setup(bot):
    await bot.add_cog(MatchCommands(bot)) 