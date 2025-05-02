import discord
import asyncio
from typing import Dict, Any
from datetime import datetime, timezone
import json

# Dictionary to store pending archetype updates
pending_archetype_updates: Dict[int, Dict[str, Any]] = {}

async def setup(bot):
    """Setup function to add event handlers to the bot."""
    @bot.event
    async def on_reaction_add(reaction, user):
        if user.bot:
            return  # Do not respond to bot reactions
        
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
                    archetype_response = bot.supabase.table('deck_archetypes').insert({
                        "name": archetype_info['new_archetype'],
                        "key_cards": key_cards
                    }).execute()
                    
                    new_archetype_id = archetype_response.data[0]['id']
                    await reaction.message.channel.send(f"✅ Created new archetype: {archetype_info['new_archetype']}")
                    
                elif str(admin_reaction.emoji) == "2️⃣":
                    # Map to existing archetype
                    archetypes_response = bot.supabase.table('deck_archetypes').select("*").execute()
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
                    others_response = bot.supabase.table('deck_archetypes').select("*").eq('name', 'Others').execute()
                    if others_response.data:
                        new_archetype_id = others_response.data[0]['id']
                        await reaction.message.channel.send("✅ Keeping archetype as 'Others'")
                    else:
                        await reaction.message.channel.send("❌ Error: 'Others' archetype not found in database")
                        return
                
                # Update the deck with the new archetype ID
                if 'deck_id' in archetype_info:
                    # First get the current deck data
                    deck_response = bot.supabase.table('decks').select("*").eq("id", archetype_info['deck_id']).execute()
                    if not deck_response.data:
                        await reaction.message.channel.send("❌ Error: Deck not found in database")
                        return
                    
                    current_deck = deck_response.data[0]
                    decklist = json.loads(current_deck['decklist'])
                    
                    # Update the deck with new archetype and last_modified timestamp
                    bot.supabase.table('decks').update({
                        "archetype_id": new_archetype_id,
                        "last_modified": datetime.now(timezone.utc).isoformat()
                    }).eq("id", archetype_info['deck_id']).execute()
                
                # Update the match with the new archetype if it exists
                if 'match_id' in archetype_info:
                    bot.supabase.table('matches').update({
                        "opponent_archetype": archetype_info['new_archetype']
                    }).eq("id", archetype_info['match_id']).execute()
                
                # Notify the user
                user_discord_id = int(archetype_info['user_id'])
                discord_user = bot.get_user(user_discord_id)
                if discord_user:
                    await discord_user.send(f"Your deck **{archetype_info.get('deck_name', 'match')}** has been processed with the archetype **{archetype_info['new_archetype']}**!")
                
                # Clean up
                del pending_archetype_updates[reaction.message.id]
                
            except asyncio.TimeoutError:
                await reaction.message.channel.send("❌ Response timeout. Please try again.")
                return 