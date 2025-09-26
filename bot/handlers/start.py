from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

def register_start(app: Client):

    @app.on_message(filters.private & filters.command("start"))
    async def start_handler(client: Client, message: Message):
        welcome_text = (
            "🎉 Welcome to Robot!\n\n"
            "Enter your phone number with the country code.\n"
            "Example: +91xxxxxxxxxx\n\n"
            "Type /cap to see available countries."
        )

        # Create a button for the hamburger (≡) menu
        menu_button = [
            [InlineKeyboardButton("≡ Menu", callback_data="menu_options")]  # Hamburger Menu
        ]

        # Create reply markup with the menu button
        reply_markup = InlineKeyboardMarkup(menu_button)

        # Send the message with the inline menu button
        await message.reply_text(
            welcome_text,
            reply_markup=reply_markup
        )

    @app.on_callback_query(filters.regex("menu_options"))
    async def show_menu(client: Client, callback_query):
        # Create the options menu to show after the (≡) button is clicked
        menu_options = [
            [InlineKeyboardButton("✅ Restart /start", callback_data="restart")],
            [InlineKeyboardButton("🌐 Capacity /cap", callback_data="capacity")],
            [InlineKeyboardButton("🎰 Check - Balance /account", callback_data="account")],
            [InlineKeyboardButton("💸 Withdraw Accounts /withdraw", callback_data="withdraw")],
            [InlineKeyboardButton("🆘 Need Help? /support", callback_data="support")]
        ]

        # Create reply markup for the options menu
        reply_markup = InlineKeyboardMarkup(menu_options)

        # Answer the callback query and update the message with the menu
        await callback_query.answer()
        await callback_query.edit_message_text(
            "Please choose an option:",
            reply_markup=reply_markup
        )
