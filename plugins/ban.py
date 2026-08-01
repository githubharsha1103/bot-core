from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, CallbackQuery, InlineKeyboardMarkup, LabeledPrice
from utils import storage, get_message


@Client.on_callback_query(filters.regex("buy_unban"))
async def check_ban(client: Client, message: CallbackQuery):
    user_id = message.from_user.id
    user_data = await storage.get_user(user_id)
    if user_data:
        if user_data['ban']['totals'] >= 5:
            await message.answer(get_message(user_data['lang'], 'unban_too_many'))
            message.stop_propagation()
        
        if user_data['ban']['active']:
            payment_link = await client.create_invoice_link(
                title=f"Unban {user_id}",
                description="Unban yourself from the bot",
                payload=f"unban-purchase",
                currency='XTR',
                provider_token='',
                prices=[LabeledPrice("Unban", 400)]
            )

            pay_label = get_message(user_data['lang'], 'subscription.pay_btn')
            if message.message and message.message.chat:
                await message.edit_message_text(get_message(user_data['lang'], 'unban_buy'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(pay_label, url=payment_link, pay=True)]]))
        
    message.stop_propagation()

