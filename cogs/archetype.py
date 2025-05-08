import discord
from discord.ext import commands
import asyncio
from datetime import datetime

from database.supabase import ArchetypeRepository
from config import DISCORD_ALERT_CHANNEL, OWNER_ID

class ArchetypeCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        """Check if the user has access to the admin logs channel for admin commands."""
        # Only check for admin commands
        if ctx.command.name in ['add', 'remove', 'rename']:
            # If in DM, only allow if user is bot owner
            if not ctx.guild:
                return ctx.author.id == int(OWNER_ID)
                
            # Get the admin channel
            admin_channel = ctx.guild.get_channel(DISCORD_ALERT_CHANNEL)
            if not admin_channel:
                return False
                
            # Check if user has permissions to view the admin channel
            permissions = admin_channel.permissions_for(ctx.author)
            return permissions.view_channel or ctx.author.guild_permissions.administrator
        return True

    @commands.group()
    async def archetype(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send('Please specify a subcommand for archetype, e.g., "!archetype add".')

    @archetype.command(name='add')
    async def add_archetype(self, ctx):
        """Add a new archetype."""
        try:
            # Check if archetype already exists
            await ctx.send('Please enter the archetype name:')
            
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            try:
                archetype_name = await self.bot.wait_for('message', check=check, timeout=60.0)
            except asyncio.TimeoutError:
                await ctx.send('❌ You took too long to respond.')
                return

            # Check if archetype already exists
            archetypes = ArchetypeRepository.get_all_archetypes()
            if any(a['name'].lower() == archetype_name.content.lower() for a in archetypes):
                await ctx.send(f"❌ Archetype '{archetype_name.content}' already exists.")
                return

            # Get key cards
            await ctx.send('Please enter the key cards for the archetype, separated by commas:')
            
            try:
                key_cards_message = await self.bot.wait_for('message', check=check, timeout=60.0)
            except asyncio.TimeoutError:
                await ctx.send('❌ You took too long to respond.')
                return

            # Process key cards
            key_cards = [card.strip() for card in key_cards_message.content.split(',')]

            # Add the archetype
            ArchetypeRepository.create_archetype(archetype_name.content, key_cards)
            await ctx.send(f"✅ Successfully added archetype: {archetype_name.content}")

        except Exception as e:
            await ctx.send(f"❌ Error adding archetype: {str(e)}")

    @archetype.command(name='remove')
    async def remove_archetype(self, ctx, *, name: str):
        """Remove an archetype."""
        try:
            # Check if archetype exists
            archetypes = ArchetypeRepository.get_all_archetypes()
            archetype = next((a for a in archetypes if a['name'].lower() == name.lower()), None)
            
            if not archetype:
                await ctx.send(f"❌ Archetype '{name}' not found.")
                return

            # Create confirmation message
            confirm_embed = discord.Embed(
                title="⚠️ Confirm Archetype Removal",
                description=f"Are you sure you want to remove the archetype '{name}'?\nThis will affect all related matches and decks.",
                color=discord.Color.orange()
            )
            confirm_msg = await ctx.send(embed=confirm_embed)
            
            # Add reactions
            await confirm_msg.add_reaction("✅")
            await confirm_msg.add_reaction("❌")

            # Wait for reaction
            try:
                reaction, _ = await self.bot.wait_for(
                    'reaction_add',
                    timeout=30.0,
                    check=lambda r, u: u == ctx.author and str(r.emoji) in ["✅", "❌"] and r.message.id == confirm_msg.id
                )
                
                if str(reaction.emoji) == "✅":
                    # Remove the archetype
                    ArchetypeRepository.delete_archetype(archetype['id'])
                    await ctx.send(f"✅ Successfully removed archetype: {name}")
                else:
                    await ctx.send("❌ Operation cancelled.")

            except asyncio.TimeoutError:
                await ctx.send("❌ Operation timed out.")

        except Exception as e:
            await ctx.send(f"❌ Error removing archetype: {str(e)}")

    @archetype.command(name='list')
    async def list_archetypes(self, ctx):
        """List all archetypes."""
        try:
            archetypes = ArchetypeRepository.get_all_archetypes()
            if not archetypes:
                await ctx.send("No archetypes found.")
                return

            # Create embed
            embed = discord.Embed(
                title="Available Archetypes",
                description="Here are all the registered archetypes:",
                color=discord.Color.blue()
            )

            # Sort archetypes by name, putting "Others" last
            sorted_archetypes = sorted(
                [a for a in archetypes if a['name'] != 'Others'],
                key=lambda x: x['name']
            )
            others = next((a for a in archetypes if a['name'] == 'Others'), None)
            if others:
                sorted_archetypes.append(others)

            # Add archetypes to embed
            for i, archetype in enumerate(sorted_archetypes, 1):
                key_cards = archetype.get('key_cards', '').split(',')
                key_cards_text = ', '.join(key_cards) if key_cards else 'No key cards specified'
                
                embed.add_field(
                    name=f"{i}. {archetype['name']}",
                    value=f"Key Cards: {key_cards_text}\nCreated: {datetime.fromisoformat(archetype['created_at']).strftime('%Y-%m-%d')}",
                    inline=False
                )

            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Error listing archetypes: {str(e)}")

    @archetype.command(name='rename')
    async def rename_archetype(self, ctx, old_name: str, new_name: str):
        """Rename an archetype."""
        try:
            # Check if old archetype exists
            archetypes = ArchetypeRepository.get_all_archetypes()
            old_archetype = next((a for a in archetypes if a['name'].lower() == old_name.lower()), None)
            
            if not old_archetype:
                await ctx.send(f"❌ Archetype '{old_name}' not found.")
                return

            # Check if new name already exists
            if any(a['name'].lower() == new_name.lower() for a in archetypes):
                await ctx.send(f"❌ Archetype '{new_name}' already exists.")
                return

            # Create confirmation message
            confirm_embed = discord.Embed(
                title="⚠️ Confirm Archetype Rename",
                description=f"Are you sure you want to rename '{old_name}' to '{new_name}'?\nThis will update all related matches and decks.",
                color=discord.Color.orange()
            )
            confirm_msg = await ctx.send(embed=confirm_embed)
            
            # Add reactions
            await confirm_msg.add_reaction("✅")
            await confirm_msg.add_reaction("❌")

            # Wait for reaction
            try:
                reaction, _ = await self.bot.wait_for(
                    'reaction_add',
                    timeout=30.0,
                    check=lambda r, u: u == ctx.author and str(r.emoji) in ["✅", "❌"] and r.message.id == confirm_msg.id
                )
                
                if str(reaction.emoji) == "✅":
                    # Rename the archetype
                    ArchetypeRepository.update_archetype(old_archetype['id'], new_name)
                    await ctx.send(f"✅ Successfully renamed '{old_name}' to '{new_name}'")
                else:
                    await ctx.send("❌ Operation cancelled.")

            except asyncio.TimeoutError:
                await ctx.send("❌ Operation timed out.")

        except Exception as e:
            await ctx.send(f"❌ Error renaming archetype: {str(e)}")

async def setup(bot):
    await bot.add_cog(ArchetypeCommands(bot)) 