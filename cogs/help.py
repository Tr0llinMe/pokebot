import discord
from discord.ext import commands

class HelpCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='help')
    async def help(self, ctx):
        """Show all available commands."""
        # Create the help message
        help_message = (
            "PokéBot Commands\n"
            "Here are all available commands:\n\n"
            "👤 User Commands\n"
            "`!user register` - Register yourself\n\n"
            "📝 Deck Commands\n"
            "`!deck add <name>` - Add a new deck (DM only)\n"
            "`!deck edit` - Edit an existing deck\n"
            "`!deck box` - View your decks\n"
            "`!deck viewbox <ID>` - View a specific deck\n\n"
            "🎮 Match Commands\n"
            "`!match log` - Log a match\n"
            "`!match history` - View matchup history\n\n"
            "❓ MISC Commands \n"
            "`!archetype list` - List all archetypes\n"
        )
        
        await ctx.send(help_message)

    @commands.command(name='adminhelp')
    async def adminhelp(self, ctx):
        """Show admin-only commands."""
        # Check if user has admin permissions
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ This command is only available to administrators.")
            return

        # Create the admin help message
        admin_help = (
            "🔒 Admin Commands\n"
            "Here are all available admin commands:\n\n"
            "📝 Archetype Commands\n"
            "`!archetype add <name> <key_cards>` - Add a new archetype\n"
            "`!archetype remove <name>` - Remove an archetype\n"
            "`!archetype rename <old_name> <new_name>` - Rename an archetype\n\n"
            "👮 Admin Commands\n"
            "`!spritefetch` - Grabs the Sprites for all Archetypes\n"
            "`!reload <cog>` - Reloads a Cog\n"
            "`!reloadall` - Reloads all Cogs\n"
        )
        
        await ctx.send(admin_help)

async def setup(bot):
    await bot.add_cog(HelpCommands(bot)) 