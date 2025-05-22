import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from database.supabase import get_supabase

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

class Pokebot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None  # Disable default help command
        )
        # Initialize Supabase client
        self.supabase = get_supabase()

    async def setup_hook(self):
        # Load all cogs
        for cog in [
            'cogs.help',
            'cogs.user',
            'cogs.deck',
            'cogs.match',
            'cogs.archetype',
            'cogs.admin',
            'cogs.tool'
        ]:
            try:
                await self.load_extension(cog)
                print(f'Successfully loaded {cog}')
            except Exception as e:
                print(f'Failed to load {cog}: {str(e)}')
        
        # Load events
        from utils.events import setup
        await setup(self)
        print('Successfully loaded events')

    async def on_ready(self):
        print(f'{self.user} has connected to Discord!')
        print('Connected to the following guilds:')
        for guild in self.guilds:
            print(f'- {guild.name} (id: {guild.id})')

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.errors.CheckFailure):
            await ctx.send('❌ You do not have the required permissions to run this command.')
        elif isinstance(error, commands.errors.MissingRequiredArgument):
            await ctx.send('❌ Missing required argument. Please check the command usage.')
        elif isinstance(error, commands.errors.CommandNotFound):
            await ctx.send('❌ Command not found. Use !help to see available commands.')
        else:
            print(f'Error: {str(error)}')
            await ctx.send(f'❌ An error occurred: {str(error)}')

def main():
    bot = Pokebot()
    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    main() 