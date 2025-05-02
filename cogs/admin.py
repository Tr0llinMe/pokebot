import discord
from discord.ext import commands
import os
import requests
from PIL import Image
import io

from database.supabase import ArchetypeRepository
from utils.image import normalize_pokeapi_name, get_sprite
from config import DISCORD_ALERT_CHANNEL

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        """Check if the user has access to the admin logs channel."""
        # Get the admin channel
        admin_channel = ctx.guild.get_channel(DISCORD_ALERT_CHANNEL)
        if not admin_channel:
            return False
            
        # Check if user has permissions to view the admin channel
        permissions = admin_channel.permissions_for(ctx.author)
        return permissions.view_channel

    @commands.command(name='spritefetch')
    @commands.has_permissions(administrator=True)
    async def spritefetch(self, ctx):
        """Fetch sprites for all archetypes."""
        try:
            # Create sprites directory if it doesn't exist
            sprites_dir = 'assets/sprites'
            os.makedirs(sprites_dir, exist_ok=True)

            # Get all archetypes
            archetypes = ArchetypeRepository.get_all_archetypes()
            
            # Create progress embed
            progress_embed = discord.Embed(
                title="Fetching Sprites",
                description="Starting sprite fetch...",
                color=discord.Color.blue()
            )
            progress_msg = await ctx.send(embed=progress_embed)

            success_count = 0
            failed_archetypes = []

            for archetype in archetypes:
                try:
                    name = archetype['name']
                    if name == 'Others':
                        # Use Unown for Others archetype
                        sprite_url = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/201.png"
                        response = requests.get(sprite_url)
                        if response.status_code == 200:
                            sprite_path = os.path.join(sprites_dir, f"{name.lower()}.png")
                            with open(sprite_path, 'wb') as f:
                                f.write(response.content)
                            success_count += 1
                        continue

                    # Try to get sprite
                    sprite = get_sprite(name)
                    if sprite:
                        success_count += 1
                    else:
                        failed_archetypes.append(name)

                    # Update progress every 5 archetypes
                    if (success_count + len(failed_archetypes)) % 5 == 0:
                        progress = (success_count + len(failed_archetypes)) / len(archetypes) * 100
                        progress_embed.description = f"Progress: {progress:.1f}%\n"
                        progress_embed.description += f"✅ Success: {success_count}\n"
                        progress_embed.description += f"❌ Failed: {len(failed_archetypes)}"
                        await progress_msg.edit(embed=progress_embed)

                except Exception as e:
                    failed_archetypes.append(name)
                    print(f"Error fetching sprite for {name}: {str(e)}")

            # Final update
            final_embed = discord.Embed(
                title="Sprite Fetch Complete",
                description=f"✅ Successfully fetched {success_count} sprites\n"
                          f"❌ Failed to fetch {len(failed_archetypes)} sprites",
                color=discord.Color.green() if not failed_archetypes else discord.Color.orange()
            )

            if failed_archetypes:
                failed_list = "\n".join(failed_archetypes)
                final_embed.add_field(
                    name="Failed Archetypes",
                    value=f"```{failed_list}```",
                    inline=False
                )

            await progress_msg.edit(embed=final_embed)

        except Exception as e:
            await ctx.send(f"❌ Error during sprite fetch: {str(e)}")

    @commands.command(name='reload')
    @commands.has_permissions(administrator=True)
    async def reload(self, ctx, cog: str):
        """Reload a specific cog."""
        try:
            self.bot.reload_extension(f"cogs.{cog}")
            await ctx.send(f"✅ Successfully reloaded {cog}")
        except Exception as e:
            await ctx.send(f"❌ Error reloading {cog}: {str(e)}")

    @commands.command(name='reloadall')
    @commands.has_permissions(administrator=True)
    async def reload_all(self, ctx):
        """Reload all cogs."""
        try:
            success = []
            failed = []
            
            for cog in ['deck', 'match', 'archetype', 'admin']:
                try:
                    self.bot.reload_extension(f"cogs.{cog}")
                    success.append(cog)
                except Exception as e:
                    failed.append((cog, str(e)))
            
            # Create response embed
            embed = discord.Embed(
                title="Reload Status",
                color=discord.Color.green() if not failed else discord.Color.orange()
            )
            
            if success:
                embed.add_field(
                    name="✅ Successfully Reloaded",
                    value="\n".join(success),
                    inline=False
                )
            
            if failed:
                embed.add_field(
                    name="❌ Failed to Reload",
                    value="\n".join(f"{cog}: {error}" for cog, error in failed),
                    inline=False
                )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error reloading cogs: {str(e)}")

async def setup(bot):
    await bot.add_cog(AdminCommands(bot)) 