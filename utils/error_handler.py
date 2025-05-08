from discord.ext import commands

async def handle_command_error(ctx, error):
    """Handle various command errors and provide user-friendly messages."""
    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send("❌ This command can only be used in a server, not in DMs!")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command!")
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Unknown command! Use `!help` to see available commands.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: {error.param.name}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Invalid argument provided! Please check the command usage.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Please wait {error.retry_after:.1f}s before using this command again.")
    else:
        # Log unexpected errors
        print(f"Unexpected error: {error}")
        await ctx.send("❌ An unexpected error occurred. Please try again later.")

def setup_error_handling(bot):
    """Set up error handling for the bot."""
    @bot.event
    async def on_command_error(ctx, error):
        await handle_command_error(ctx, error)

    @bot.event
    async def on_error(event, *args, **kwargs):
        """Handle non-command errors."""
        print(f"Error in {event}: {args[0]}") 