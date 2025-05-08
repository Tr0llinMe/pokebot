from discord.ext import commands
from database.supabase import UserRepository

class UserCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group()
    async def user(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send('Please specify a subcommand for user, e.g., "!user register".')
    
    @user.command(name='register')
    async def register(self, ctx):
        """Register a new user in the system."""
        discord_id = str(ctx.author.id)
        username = str(ctx.author)
        
        # Check if user already exists
        existing_user = UserRepository.get_user(discord_id)
        if existing_user:
            await ctx.send('You are already registered.')
            return
            
        # Create new user
        try:
            UserRepository.create_user(discord_id, username)
            await ctx.send('You have been registered.')
        except Exception as e:
            print(f"Error registering user: {e}")
            await ctx.send('❌ An error occurred during registration. Please try again later.')

async def setup(bot):
    await bot.add_cog(UserCommands(bot)) 