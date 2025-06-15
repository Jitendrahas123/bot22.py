import logging
from telegram import (
    Update, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, Message
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler,
    filters, CallbackQueryHandler, ConversationHandler
)
from telegram.error import BadRequest

# -----------------------
# Bot Configuration
# -----------------------
TOKEN = "7972689145:AAEsCTgXOXtwE0a6tZZARofSzNe6B5S_LuE"
BOT_USERNAME = "Auction_Best_Bot"  # e.g., "Auction_Best_Bot"
ADMIN_IDS = [1850686769, 5925112646, 7797689351, 7783911874, 5631189181, 6467898610]  # Replace with your admin IDs
# Groups/Channels for required membership:
REQUIRED_GROUPS = ["@ImNotRacist_911", "@husbando_waifu"]
# Public Auction Channel (main posting) and Trade Group (secondary posting)
AUCTION_CHANNEL = "@ImNotRacist_911"  # main public channel for auction posts
TRADE_GROUP = "@husbando_waifu"        # second group where auction info is also posted
HEXAMONBOT_ID = 572621020

# Global flags
submissions_allowed = True  # Controls whether new submissions via /add are allowed
auction_active = True       # Controls whether bids are accepted

# Global subscribers set to store user IDs of all users who interacted with the bot
subscribers = set()

# -----------------------
# Conversation States
# -----------------------
(CATEGORY_SELECTION, NAME_INPUT, NAME_CONFIRMATION, INFO_INPUT, INFO_CONFIRMATION,
 IVS_INPUT, IVS_CONFIRMATION, MOVESET_INPUT, MOVESET_CONFIRMATION, BOOSTED_INPUT, BOOSTED_CONFIRMATION,
 PRICE_INPUT, PRICE_CONFIRMATION, TMS_NAME, TMS_NAME_CONFIRMATION,
 TMS_HEXAFWD, TMS_HEXAFWD_CONFIRMATION, TMS_PRICE, TMS_PRICE_CONFIRMATION, BID_AMOUNT_INPUT,
 UNAPPROVE_REASON) = range(21)
# New states for broadcast conversation
BROADCAST_TEXT = 100
BROADCAST_CONFIRM = 101

# -----------------------
# Data Storage
# -----------------------
auction_items = {}       # item_id -> dict with item details (including message ids, etc.)
user_items = {}          # user_id -> list of item_ids
admin_item_messages = {} # item_id -> list of dicts with keys "chat_id" and "message_id"
# For public posts, we now also store a separate trade group message id:
# auction_items[item_id]['message_id']  -> Auction Channel message id
# auction_items[item_id]['trade_message_id'] -> Trade Group message id

# -----------------------
# Logging Setup
# -----------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -----------------------
# Bot Commands
# -----------------------
BOT_COMMANDS = [
    BotCommand("start", "🏆 Start the Pokémon Auction Bot"),
    BotCommand("add", "➕ Add your Pokémon/TMs for auction"),
    BotCommand("myitems", "📦 View your approved items"),
    BotCommand("mybids", "💰 Check your active bids"),
    BotCommand("all_items", "🔍 Browse all approved items"),
    BotCommand("help", "❓ Show help menu"),
    BotCommand("stop_submission", "⛔ Stop new submissions (Admin only)"),
    BotCommand("end_auction", "🛑 End auction (Admin only)"),
    BotCommand("start_auction", "✅ Start auction (Admin only)"),
    BotCommand("message", "📢 Broadcast a message (Admin only)"),
    BotCommand("last_bid", "📊 View all bids on approved items"),
    BotCommand("remove_last_bid", "🗑 Remove last bid from item (Admin only)")]

# -----------------------
# Helper Functions
# -----------------------
def is_forwarded_from_hexamon(message: Message) -> bool:
    if not message.forward_origin:
        return False
    origin = message.forward_origin
    if origin.type == "user":
        return origin.sender_user.id == HEXAMONBOT_ID
    if origin.type == "chat":
        return origin.sender_chat.id == HEXAMONBOT_ID
    return False

async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        for group in REQUIRED_GROUPS:
            member = await context.bot.get_chat_member(group, user_id)
            if member.status in ["left", "kicked"]:
                return False
        return True
    except Exception as e:
        logger.error(f"Membership check failed: {e}")
        return True

async def remove_all_admin_buttons_for_item(item_id: str, context: ContextTypes.DEFAULT_TYPE):
    if item_id in admin_item_messages:
        for entry in admin_item_messages[item_id]:
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=entry["chat_id"],
                    message_id=entry["message_id"],
                    reply_markup=None
                )
            except Exception as e:
                logger.error(f"Error removing buttons from admin message {entry['message_id']} in {entry['chat_id']}: {e}")
        admin_item_messages.pop(item_id, None)

# Global fallback command to cancel any conversation
async def global_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Operation cancelled.")
    context.user_data.clear()
    return ConversationHandler.END

# -----------------------
# /start Command Handler
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    context.user_data.clear()
    subscribers.add(message.from_user.id)
    if message.chat.type in ["group", "supergroup"]:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💌 Start me privately", url=f"https://t.me/{BOT_USERNAME}?start=1")]
        ])
        await message.reply_text("Please chat with me in private for a better experience! 😊", reply_markup=keyboard)
        return
    args = context.args
    if args:
        param = args[0]
        if param.startswith("bid_"):
            await handle_private_bid_start(update, context, param.replace("bid_", ""))
            return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Auction Group", url="https://t.me/ImNotRacist_911"),
         InlineKeyboardButton("🤝 Trade Group", url="https://t.me/husbando_waifu")]
    ])
    welcome_msg = (
        "✨ Welcome to Pokémon Grabber Bot! ✨\n"
        "This bot manages the ultimate Pokémon & TMs auctions in Pokémon Grabber 🎉\n\n"
        "⚠️ Please make sure to join the required Channel & Groups:\n"
        "• Auction Channel: @ImNotRacist_911\n"
        "• Trade Group: @husbando_waifu\n\n"
        "Use /add to submit your items for auction.\n"
    )
    try:
        await message.reply_photo(
            photo="https://i.ibb.co/TB6xhTFj/Screen-Shot-2022-12-16-at-9-31-44-AM-e1671201592808.png",
            caption=welcome_msg,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        await message.reply_text(welcome_msg, reply_markup=keyboard)
    if not await check_membership(message.from_user.id, context):
        await message.reply_text("⚠️ Please join all required groups to participate! 🙏")
        return

# -----------------------
# Deep-Link Bidding Handler
# -----------------------
async def handle_private_bid_start(update: Update, context: ContextTypes.DEFAULT_TYPE, item_id: str):
    if not auction_active:
        await update.message.reply_text("🛑 Auction is already ended.")
        return
    item = auction_items.get(item_id)
    if not item or not item.get("approved"):
        await update.message.reply_text("❌ Item not found or not approved.")
        return
    if not await check_membership(update.effective_user.id, context):
        await update.message.reply_text("❌ Please join all required groups first! 🙏")
        return
    context.user_data.clear()
    context.user_data["bidding_item"] = item_id
    current_bid = item.get("highest_bid") or item.get("price")
    if item.get("message_id"):
        channel_link = f"https://t.me/{AUCTION_CHANNEL[1:]}/{item['message_id']}"
        item_name_link = f"[{item['name']}]({channel_link})"
    else:
        item_name_link = item['name']
    if item.get("highest_bidder_username"):
        current_bidder = f"\nCurrent Bidder: @{item.get('highest_bidder_username')}"
    elif item.get("highest_bidder"):
        current_bidder = f"\nCurrent Bidder: {item.get('highest_bidder')}"
    else:
        current_bidder = ""
    await update.message.reply_text(
        f"💰 You are bidding on {item_name_link}\n"
        f"Current Bid: {current_bid:,} PD{current_bidder}\n"
        "Please send your bid amount (numbers only):",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

# -----------------------
# "Try Again" Callback for Bid Errors
# -----------------------
async def handle_retry_bid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auction_active:
        await update.callback_query.answer("🛑 Auction is already ended.", show_alert=True)
        return
    query = update.callback_query
    await query.answer()
    # Remove buttons from this message
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except BadRequest as e:
        logger.error(f"Error removing buttons in retry: {e}")

    item_id = query.data.replace("retry_bid_", "")
    item = auction_items.get(item_id)
    if not item:
        await query.message.reply_text("❌ Item not found or auction ended.")
        return
    current_bid = item.get("highest_bid") or item.get("price")
    if item.get("message_id"):
        channel_link = f"https://t.me/{AUCTION_CHANNEL[1:]}/{item['message_id']}"
        item_name_link = f"[{item['name']}]({channel_link})"
    else:
        item_name_link = item['name']
    if item.get("highest_bidder_username"):
        current_bidder = f"\nCurrent Bidder: @{item.get('highest_bidder_username')}"
    elif item.get("highest_bidder"):
        current_bidder = f"\nCurrent Bidder: {item.get('highest_bidder')}"
    else:
        current_bidder = ""
    await query.message.reply_text(
        f"💰 You are bidding on {item_name_link}\n"
        f"Current Bid: {current_bid:,} PD{current_bidder}\n"
        "Please send your bid amount (numbers only):",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    context.user_data["bidding_item"] = item_id

# -----------------------
# Private Bid Message Handler with Confirmation
# -----------------------
async def handle_bid_in_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auction_active:
        await update.message.reply_text("🛑 Auction is already ended.")
        return
    if "bidding_item" not in context.user_data:
        return
    item_id = context.user_data["bidding_item"]
    item = auction_items.get(item_id)
    if not item:
        await update.message.reply_text("❌ Item not found or auction ended.")
        context.user_data.pop("bidding_item", None)
        return
    try:
        bid_amount = int(update.message.text.replace(",", "").strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Please try again with a proper integer.")
        return
    current_bid = item.get("highest_bid") or item.get("price")
    min_increase = 1000
    if current_bid >= 50000 and current_bid < 100000:
        min_increase = 2000
    elif current_bid >= 100000:
        min_increase = 5000
    if bid_amount <= current_bid or (bid_amount - current_bid) < min_increase:
        error_text = (
            "🚫 Bid Not Accepted!\n"
            "⁉️ Reasons:\n"
            "• Bid must be higher than the current bid\n"
            "• Follow the minimum bid increase rule:\n"
            "  +1k if below 50k\n"
            "  +2k if 50k-100k\n"
            "  +5k if over 100k\n\n"
            "Please try again."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Try Again", callback_data=f"retry_bid_{item_id}")]
        ])
        await update.message.reply_text(error_text, reply_markup=keyboard)
        return
    context.user_data["pending_bid"] = bid_amount
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data=f"confirm_bid_yes_{item_id}"),
            InlineKeyboardButton("❌ No", callback_data=f"confirm_bid_no_{item_id}")
        ]
    ])
    await update.message.reply_text(f"Confirm your bid of {bid_amount:,} PD?", reply_markup=keyboard)

# -----------------------
# Callback Handler for Bid Confirmation
# -----------------------
async def handle_bid_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Remove buttons from the confirmation message
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except BadRequest as e:
        logger.error(f"Error removing buttons in bid confirmation: {e}")
    data = query.data
    if data.startswith("confirm_bid_yes_"):
        item_id = data[len("confirm_bid_yes_"):]
    elif data.startswith("confirm_bid_no_"):
        item_id = data[len("confirm_bid_no_"):]
    else:
        await query.message.reply_text("❌ Invalid confirmation response.")
        return

    
    if "bidding_item" not in context.user_data or context.user_data["bidding_item"] != item_id:
        await query.message.reply_text("❌ This bid confirmation is outdated or invalid.")
        return

    pending_bid = context.user_data.get("pending_bid")
    if data.startswith("confirm_bid_yes_"):
        item = auction_items.get(item_id)
        if not item:
            await query.message.reply_text("❌ Item not found or auction ended.")
            return
        previous_bidder = item.get("highest_bidder")
        previous_bid = item.get("highest_bid") or item.get("price")
        # Update the bid information in the item
        item['highest_bid'] = pending_bid
        item['highest_bidder'] = query.from_user.id
        item['highest_bidder_username'] = query.from_user.username or query.from_user.full_name

        # ✅ Append to bid history
        item.setdefault("bids", []).append({
            "user_id": query.from_user.id,
            "username": query.from_user.username or query.from_user.full_name,
            "amount": pending_bid
        })
        # Notify the previous bidder if applicable
        if previous_bidder and previous_bidder != query.from_user.id:
            if item.get("message_id"):
                channel_link = f"https://t.me/{AUCTION_CHANNEL[1:]}/{item['message_id']}"
                hyperlink = f'<a href="{channel_link}">{item["name"]}</a>'
            else:
                hyperlink = item["name"]
            place_bid_button = InlineKeyboardMarkup([
                [InlineKeyboardButton("💵 Place Bid", url=f"https://t.me/{BOT_USERNAME}?start=bid_{item_id}")]
            ])
            msg_text = (
                f"Your bid on {hyperlink} has been outbid.\n"
                f"Earlier bid: {previous_bid:,} PD\n"
                f"New bid: {pending_bid:,} PD\n"
                "Please place a new bid if you wish."
            )
            try:
                await context.bot.send_message(
                    chat_id=previous_bidder,
                    text=msg_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=place_bid_button
                )
                logger.info(f"Notified previous bidder {previous_bidder} about being outbid on item {item_id}.")
            except Exception as e:
                logger.error(f"Failed to notify previous bidder {previous_bidder}: {e}")
        # Update the public auction messages in both Auction Channel and Trade Group
        new_caption = ""
        if item.get('category') == 'tms':
            new_caption = (
                f"=== TMs Page ===\n{item.get('tms_text', '')}\n\n"
                f"🎮 TMs Name: {item['name']}\n"
                f"Base Price: {item['price']:,} PD\n"
                f"Current Bid: {pending_bid:,} PD\n"
                f"Bidder: @{query.from_user.username or query.from_user.id}"
            )
        else:
            new_caption = (
                f"=== Info Page ===\n{item.get('info_text', '')}\n\n"
                f"=== IVs Page ===\n{item.get('ivs_text', '')}\n\n"
                f"=== Moveset Page ===\n{item.get('moveset_text', '')}\n\n"
                f"Name: {item['name']}\n"
                f"Category: {item.get('category', 'Unknown')}\n"
                f"Submitted by: @{item.get('owner_username', 'NoUsername')} (ID: {item.get('owner')})\n"
                f"Base Price: {item['price']:,} PD\n"
                f"Current Bid: {pending_bid:,} PD\n"
                f"Boosted: {item.get('boosted')}\n"
                f"Bidder: @{query.from_user.username or query.from_user.id}"
            )
        bidding_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_{item_id}"),
                InlineKeyboardButton("💵 Place Bid", url=f"https://t.me/{BOT_USERNAME}?start=bid_{item_id}")
            ]
        ])
        chosen_photo = (item.get("info_photo")
                        or item.get("ivs_photo")
                        or item.get("moveset_photo")
                        or item.get("tms_photo"))
        # Update Auction Channel message
        try:
            if chosen_photo:
                await context.bot.edit_message_caption(
                    chat_id=AUCTION_CHANNEL,
                    message_id=item.get("message_id"),
                    caption=new_caption,
                    reply_markup=bidding_keyboard
                )
            else:
                await context.bot.edit_message_text(
                    chat_id=AUCTION_CHANNEL,
                    message_id=item.get("message_id"),
                    text=new_caption,
                    reply_markup=bidding_keyboard
                )
        except Exception as e:
            logger.error(f"Error updating channel post for item {item_id}: {e}")
            await query.message.reply_text("⚠️ Failed to update auction channel message, but your bid is recorded.")
        # Also update Trade Group message if available
        if item.get("trade_message_id"):
            try:
                if chosen_photo:
                    await context.bot.edit_message_caption(
                        chat_id=TRADE_GROUP,
                        message_id=item.get("trade_message_id"),
                        caption=new_caption,
                        reply_markup=bidding_keyboard
                    )
                else:
                    await context.bot.edit_message_text(
                        chat_id=TRADE_GROUP,
                        message_id=item.get("trade_message_id"),
                        text=new_caption,
                        reply_markup=bidding_keyboard
                    )
            except Exception as e:
                logger.error(f"Error updating trade group post for item {item_id}: {e}")
        await query.message.reply_text(f"✅ Bid of {pending_bid:,} PD accepted!")
        context.user_data.pop("pending_bid", None)
        context.user_data.pop("bidding_item", None)
    elif data.startswith("confirm_bid_no_"):
        context.user_data.pop("pending_bid", None)
        await query.message.reply_text("Please send your bid amount (numbers only):")

# -----------------------
# /add Submission Conversation
# -----------------------
async def add_item_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not submissions_allowed:
        await update.message.reply_text("🚫 Sorry, we are not accepting new submissions right now!")
        return ConversationHandler.END
    if update.message.chat.type in ["group", "supergroup"]:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💌 Start in DM", url=f"https://t.me/{BOT_USERNAME}?start=1")]
        ])
        await update.message.reply_text("Let's add some Pokémon or TMs for auction! Click below to start in DM!", reply_markup=keyboard)
        return ConversationHandler.END
    if not await check_membership(update.message.from_user.id, context):
        await update.message.reply_text("❌ Please join the required groups first!")
        return ConversationHandler.END
    context.user_data.clear()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌟 Shiny", callback_data="category_shiny"),
         InlineKeyboardButton("🐉 Legendary", callback_data="category_legendary")],
        [InlineKeyboardButton("😊 Non-Legendary", callback_data="category_non_legendary")],
        [InlineKeyboardButton("📜 TMs", callback_data="category_tms")],
        [InlineKeyboardButton("🚫 Cancel", callback_data="cancel")]
    ])
    await update.message.reply_text("Select Pokémon Category (or TMs):", reply_markup=keyboard)
    return CATEGORY_SELECTION

async def handle_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.message.reply_text("🚫 Listing cancelled.")
        context.user_data.clear()
        return ConversationHandler.END
    chosen_category = query.data.split("_", 1)[1]
    if chosen_category == "tms":
        context.user_data["category"] = "tms"
        await query.message.reply_text("What TMs are you selling?")
        return TMS_NAME
    else:
        context.user_data["category"] = chosen_category
        await query.message.reply_text("What is your Pokémon's name?")
        return NAME_INPUT

# ------------
# TMs Flow
# ------------
async def handle_tms_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["tms_name"] = update.message.text
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="tms_name_yes"),
         InlineKeyboardButton("❌ No", callback_data="tms_name_no")]
    ])
    await update.message.reply_text(f"Confirm TMs name: {context.user_data['tms_name']}", reply_markup=keyboard)
    return TMS_NAME_CONFIRMATION

async def handle_tms_name_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "tms_name_no":
        await query.message.reply_text("What TMs are you selling?")
        return TMS_NAME
    await query.message.reply_text("Please forward the TMs Page from @HeXamonbot:")
    return TMS_HEXAFWD

async def handle_tms_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_forwarded_from_hexamon(update.message):
        await update.message.reply_text("⚠️ Please forward from @HeXamonbot.")
        return TMS_HEXAFWD
    if update.message.photo:
        context.user_data["tms_photo"] = update.message.photo[-1].file_id
        context.user_data["tms_text"] = update.message.caption or update.message.text
    else:
        context.user_data["tms_photo"] = None
        context.user_data["tms_text"] = update.message.text
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="tms_fwd_yes"),
         InlineKeyboardButton("❌ No", callback_data="tms_fwd_no")]
    ])
    await update.message.reply_text("Confirm the TMs Page (must be forwarded from @HeXamonbot):", reply_markup=keyboard)
    return TMS_HEXAFWD_CONFIRMATION

async def handle_tms_forward_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "tms_fwd_no":
        await query.message.reply_text("Please forward the TMs Page from @HeXamonbot again:")
        return TMS_HEXAFWD
    await query.message.reply_text("What is the base price? 📝 (numbers only, e.g., 2000)")
    return TMS_PRICE

async def handle_tms_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.replace(",", "").strip())
        context.user_data["tms_price"] = price
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes", callback_data="tms_price_yes"),
             InlineKeyboardButton("❌ No", callback_data="tms_price_no")]
        ])
        await update.message.reply_text(f"Confirm Base Price: {price}", reply_markup=keyboard)
        return TMS_PRICE_CONFIRMATION
    except ValueError:
        await update.message.reply_text("❌ Invalid price! Please enter numbers only.")
        return TMS_PRICE

async def handle_tms_price_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "tms_price_no":
        await query.message.reply_text("What is the base price? 📝 (numbers only, e.g., 2000)")
        return TMS_PRICE
    item_id = f"tms_{len(auction_items)+1}"
    auction_items[item_id] = {
        'name': context.user_data['tms_name'],
        'category': "tms",
        'tms_photo': context.user_data.get('tms_photo'),
        'tms_text': context.user_data.get('tms_text'),
        'price': context.user_data['tms_price'],
        'owner': query.from_user.id,
        'owner_username': query.from_user.username,
        'approved': False,
        'highest_bid': None,
        'highest_bidder': None,
        'message_id': None,          # Auction Channel message id (to be set upon approval)
        'trade_message_id': None     # Trade Group message id (to be set upon approval)
    }
    user_items.setdefault(query.from_user.id, []).append(item_id)
    chosen_photo = context.user_data.get('tms_photo')
    username_text = f"@{query.from_user.username}" if query.from_user.username else "(No username)"
    caption_text = (
        f"=== TMs Page ===\n{context.user_data.get('tms_text', '')}\n\n"
        f"New TMs Submission:\n"
        f"🎮 TMs Name: {context.user_data['tms_name']}\n"
        f"Price: {context.user_data['tms_price']:,} PD\n\n"
        f"Submitted by: {query.from_user.full_name} {username_text} (ID: {query.from_user.id})\n\n"
        f"Item ID: {item_id}"
    )
    approval_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{item_id}"),
         InlineKeyboardButton("🚫 Unapprove", callback_data=f"unapprove_{item_id}")]
    ])
    admin_item_messages[item_id] = []
    for admin_id in ADMIN_IDS:
        try:
            if chosen_photo:
                msg = await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=chosen_photo,
                    caption=caption_text,
                    reply_markup=approval_keyboard
                )
            else:
                msg = await context.bot.send_message(
                    chat_id=admin_id,
                    text=caption_text,
                    reply_markup=approval_keyboard
                )
            admin_item_messages[item_id].append({'chat_id': admin_id, 'message_id': msg.message_id})
        except Exception as e:
            logger.error(f"Failed to send notification to admin {admin_id}: {e}")
    # Optionally, send a copy of the submission to the Auction Channel and Trade Group if auto-approved later.
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👉 Join Auction Channel", url="https://t.me/ImNotRacist_911")],
        [InlineKeyboardButton("👉 Join Trade Group", url="https://t.me/husbando_waifu")]
    ])
    await query.message.reply_text(
        f"Your TMs ({context.user_data['tms_name']}) has been submitted for approval! ✅\n\n"
        "Make sure you join the required channels/groups!",
        reply_markup=keyboard
    )
    context.user_data.clear()
    return ConversationHandler.END

# -----------------------
# Original Pokémon Flow
# -----------------------
async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="name_yes"),
         InlineKeyboardButton("❌ No", callback_data="name_no")]
    ])
    await update.message.reply_text(f"Confirm name: {context.user_data['name']}", reply_markup=keyboard)
    return NAME_CONFIRMATION

async def handle_name_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "name_no":
        await query.message.reply_text("What is your Pokémon's name?")
        return NAME_INPUT
    await query.message.reply_text("Please forward the Pokémon Info Page from @HeXamonbot:")
    return INFO_INPUT

async def handle_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_forwarded_from_hexamon(update.message):
        await update.message.reply_text("⚠️ Please forward from @HeXamonbot.")
        return INFO_INPUT
    if update.message.photo:
        context.user_data["info_photo"] = update.message.photo[-1].file_id
        context.user_data["info_text"] = update.message.caption or update.message.text
    else:
        context.user_data["info_photo"] = None
        context.user_data["info_text"] = update.message.text
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="info_yes"),
         InlineKeyboardButton("❌ No", callback_data="info_no")]
    ])
    await update.message.reply_text("Confirm Pokémon Info Page (must be from @HeXamonbot):", reply_markup=keyboard)
    return INFO_CONFIRMATION

async def handle_info_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "info_no":
        await query.message.reply_text("Please forward the Pokémon Info Page from @HeXamonbot:")
        return INFO_INPUT
    await query.message.reply_text("Forward the Pokémon IVs Page from @HeXamonbot:")
    return IVS_INPUT

async def handle_ivs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_forwarded_from_hexamon(update.message):
        await update.message.reply_text("⚠️ Please forward from @HeXamonbot.")
        return IVS_INPUT
    if update.message.photo:
        context.user_data["ivs_photo"] = update.message.photo[-1].file_id
        context.user_data["ivs_text"] = update.message.caption or update.message.text
    else:
        context.user_data["ivs_photo"] = None
        context.user_data["ivs_text"] = update.message.text
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="ivs_yes"),
         InlineKeyboardButton("❌ No", callback_data="ivs_no")]
    ])
    await update.message.reply_text("Confirm Pokémon IVs Page (must be from @HeXamonbot):", reply_markup=keyboard)
    return IVS_CONFIRMATION

async def handle_ivs_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "ivs_no":
        await query.message.reply_text("Please forward the Pokémon IVs Page from @HeXamonbot:")
        return IVS_INPUT
    await query.message.reply_text("Forward the Pokémon Moveset Page from @HeXamonbot:")
    return MOVESET_INPUT

async def handle_moveset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_forwarded_from_hexamon(update.message):
        await update.message.reply_text("⚠️ Please forward from @HeXamonbot.")
        return MOVESET_INPUT
    if update.message.photo:
        context.user_data["moveset_photo"] = update.message.photo[-1].file_id
        context.user_data["moveset_text"] = update.message.caption or update.message.text
    else:
        context.user_data["moveset_photo"] = None
        context.user_data["moveset_text"] = update.message.text
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="moveset_yes"),
         InlineKeyboardButton("❌ No", callback_data="moveset_no")]
    ])
    await update.message.reply_text("Confirm Pokémon Moveset Page (must be from @HeXamonbot):", reply_markup=keyboard)
    return MOVESET_CONFIRMATION

async def handle_moveset_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "moveset_no":
        await query.message.reply_text("Please forward the Pokémon Moveset Page from @HeXamonbot:")
        return MOVESET_INPUT
    await query.message.reply_text("Is your Pokémon boosted? (Yes/No; if Yes, specify which IVs) 💥")
    return BOOSTED_INPUT

async def handle_boosted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["boosted"] = update.message.text
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="boosted_yes"),
         InlineKeyboardButton("❌ No", callback_data="boosted_no")]
    ])
    await update.message.reply_text("Confirm boosted information:", reply_markup=keyboard)
    return BOOSTED_CONFIRMATION

async def handle_boosted_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "boosted_no":
        await query.message.reply_text("Is your Pokémon boosted? (Yes/No; if Yes, specify which IVs)")
        return BOOSTED_INPUT
    await query.message.reply_text("What is the base price? 📝 (numbers only, e.g., 2000)")
    return PRICE_INPUT

async def handle_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.replace(",", "").strip())
        context.user_data["price"] = price
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes", callback_data="price_yes"),
             InlineKeyboardButton("❌ No", callback_data="price_no")]
        ])
        await update.message.reply_text(f"Confirm Base Price: {price}", reply_markup=keyboard)
        return PRICE_CONFIRMATION
    except ValueError:
        await update.message.reply_text("❌ Invalid price! Please enter numbers only.")
        return PRICE_INPUT

async def handle_price_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "price_no":
        await query.message.reply_text("What is the base price? 📝 (numbers only, e.g., 2000)")
        return PRICE_INPUT
    item_id = f"{context.user_data['category']}_{len(auction_items)+1}"
    auction_items[item_id] = {
        'name': context.user_data['name'],
        'category': context.user_data['category'],
        'info_photo': context.user_data.get('info_photo'),
        'info_text': context.user_data.get('info_text'),
        'ivs_photo': context.user_data.get('ivs_photo'),
        'ivs_text': context.user_data.get('ivs_text'),
        'moveset_photo': context.user_data.get('moveset_photo'),
        'moveset_text': context.user_data.get('moveset_text'),
        'boosted': context.user_data['boosted'],
        'price': context.user_data['price'],
        'owner': query.from_user.id,
        'owner_username': query.from_user.username,
        'approved': False,
        'highest_bid': None,
        'highest_bidder': None,
        'message_id': None,          # Auction Channel message id
        'trade_message_id': None     # Trade Group message id
    }
    user_items.setdefault(query.from_user.id, []).append(item_id)
    chosen_photo = (context.user_data.get('info_photo')
                    or context.user_data.get('ivs_photo')
                    or context.user_data.get('moveset_photo'))
    username_text = f"@{query.from_user.username}" if query.from_user.username else "(No username)"
    caption_text = (
        f"=== Info Page ===\n{context.user_data.get('info_text', '')}\n\n"
        f"=== IVs Page ===\n{context.user_data.get('ivs_text', '')}\n\n"
        f"=== Moveset Page ===\n{context.user_data.get('moveset_text', '')}\n\n"
        f"New Pokémon Submission:\n"
        f"🐾 Name: {context.user_data['name']}\n"
        f"🔰 Category: {context.user_data['category']}\n"
        f"💰 Price: {context.user_data['price']}\n"
        f"⚡ Boosted: {context.user_data['boosted']}\n"
        f"Submitted by: {query.from_user.full_name} {username_text} (ID: {query.from_user.id})\n\n"
        f"Item ID: {item_id}"
    )
    approval_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{item_id}"),
         InlineKeyboardButton("🚫 Unapprove", callback_data=f"unapprove_{item_id}")]
    ])
    admin_item_messages[item_id] = []
    for admin_id in ADMIN_IDS:
        try:
            if chosen_photo:
                msg = await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=chosen_photo,
                    caption=caption_text,
                    reply_markup=approval_keyboard
                )
            else:
                msg = await context.bot.send_message(
                    chat_id=admin_id,
                    text=caption_text,
                    reply_markup=approval_keyboard
                )
            admin_item_messages[item_id].append({'chat_id': admin_id, 'message_id': msg.message_id})
        except Exception as e:
            logger.error(f"Failed to send notification to admin {admin_id}: {e}")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👉 Join Auction Channel", url="https://t.me/ImNotRacist_911")],
        [InlineKeyboardButton("👉 Join Trade Group", url="https://t.me/husbando_waifu")]
    ])
    await query.message.reply_text(
        f"Your {context.user_data['name']} Pokémon has been submitted for approval! ✅\n\n"
        "Make sure you join the required channels/groups!",
        reply_markup=keyboard
    )
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Operation cancelled.")
    context.user_data.clear()
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📚 *Available Commands:*\n\n"
        "/start - 🏆 Start the bot\n"
        "/add - ➕ Submit Pokémon or TMs for auction\n"
        "/myitems - 📦 View your approved items\n"
        "/mybids - 💰 Check your active bids\n"
        "/all_items - 🔍 Browse all approved items\n"
        "/help - ❓ Show this help menu\n"
        "/stop_submission - ⛔ Stop new submissions (Admin only)\n"
        "/end_auction - 🛑 End auction (Admin only)\n"
        "/start_auction - ✅ Start auction (Admin only)\n"
        "/message - 📢 Broadcast a message (Admin only)"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

# -----------------------
# /stop_submission Command Handler
# -----------------------
async def stop_submission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global submissions_allowed
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    submissions_allowed = False
    await update.message.reply_text("🚫 New Pokémon submissions have been stopped.")

# -----------------------
# /end_auction Command Handler
# -----------------------
async def end_auction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global auction_active
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    auction_active = False
    await update.message.reply_text("🛑 Auction has been ended. No more bids will be accepted.")

# -----------------------
# /start_auction Command Handler
# -----------------------
async def start_auction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global submissions_allowed, auction_active
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    submissions_allowed = True
    auction_active = True
    await update.message.reply_text("✅ Auction has started. New submissions and bids are now accepted!")

# -----------------------
# /message Broadcast Conversation Handler
# -----------------------
async def message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text("📢 Please type the message to broadcast:")
    return BROADCAST_TEXT

async def broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    context.user_data["broadcast_message"] = text
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="broadcast_yes"),
         InlineKeyboardButton("❌ No", callback_data="broadcast_no")]
    ])
    await update.message.reply_text(
        "Do you want to forward this to the channel and all bot users? 📣",
        reply_markup=keyboard
    )
    return BROADCAST_CONFIRM

async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except BadRequest as e:
        logger.error(f"Error removing broadcast buttons: {e}")
    if query.data == "broadcast_yes":
        broadcast_msg = context.user_data.get("broadcast_message", "")
        try:
            await context.bot.send_message(chat_id=AUCTION_CHANNEL, text=broadcast_msg)
        except Exception as e:
            logger.error(f"Error sending broadcast to channel: {e}")
        for user_id in list(subscribers):
            try:
                await context.bot.send_message(chat_id=user_id, text=broadcast_msg)
            except Exception as e:
                logger.error(f"Error broadcasting to user {user_id}: {e}")
        await query.message.reply_text("📢 Broadcast completed.")
        return ConversationHandler.END
    else:
        await query.message.reply_text("📢 Please type the message to broadcast:")
        return BROADCAST_TEXT

# -----------------------
# /mybids Command Handler
# -----------------------
async def my_bids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("💬 Please use this command in a private chat with me.")
        return
    user_id = update.effective_user.id
    bid_lines = []
    for item_id, item in auction_items.items():
        if item.get("approved") and item.get("highest_bidder") == user_id and item.get("message_id"):
            channel_link = f"https://t.me/{AUCTION_CHANNEL[1:]}/{item['message_id']}"
            bid_lines.append(f'- <a href="{channel_link}">{item["name"]}</a>')
    if not bid_lines:
        await update.message.reply_text("😔 You have no active bids.")
        return
    text = "💰 Your active bids:\n\n" + "\n".join(bid_lines)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# -----------------------
# /all_items Command Handler
# -----------------------
async def all_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("💬 Please use this command in a private chat with me.")
        return
    groups = {}
    for item in auction_items.values():
        if item.get("approved") and item.get("message_id"):
            cat = item.get("category", "Unknown").capitalize()
            if cat not in groups:
                groups[cat] = []
            channel_link = f"https://t.me/{AUCTION_CHANNEL[1:]}/{item['message_id']}"
            groups[cat].append(f'- <a href="{channel_link}">{item["name"]}</a>')
    if not groups:
        await update.message.reply_text("😔 No approved items found.")
        return
    text_lines = []
    for cat in sorted(groups.keys()):
        text_lines.append(f"<b>{cat}:</b>")
        text_lines.extend(groups[cat])
        text_lines.append("")
    text = "\n".join(text_lines)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# -----------------------
# Admin Approval Handlers
# -----------------------
async def handle_admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Remove buttons from all admin messages for this item
    data = query.data
    item_id = data.split("_", 1)[1]
    await remove_all_admin_buttons_for_item(item_id, context)
    item = auction_items.get(item_id)
    if not item:
        await query.message.reply_text("❌ Item not found.")
        return
    owner_id = item.get("owner")
    name = item.get("name")
    admin = query.from_user
    admin_name = admin.full_name
    admin_username = f"@{admin.username}" if admin.username else ""
    try:
        await context.bot.send_message(
            chat_id=owner_id,
            text=f"🎉 Your {name} was approved for auction! ✅"
        )
    except Exception as e:
        logger.error(f"Approval notification failed: {e}")
    item['approved'] = True
    if item.get('category') == 'tms':
        channel_caption = (
            f"=== TMs Page ===\n{item.get('tms_text', '')}\n\n"
            f"New TMs Submission:\n"
            f"🎮 TMs Name: {item['name']}\n"
            f"Base Price: {item['price']:,} PD\n\n"
            f"Submitted by: @{item.get('owner_username', 'NoUsername')} (ID: {item.get('owner')})\n\n"
            f"Item ID: {item_id}"
        )
    else:
        channel_caption = (
            f"=== Info Page ===\n{item.get('info_text', '')}\n\n"
            f"=== IVs Page ===\n{item.get('ivs_text', '')}\n\n"
            f"=== Moveset Page ===\n{item.get('moveset_text', '')}\n\n"
            f"Name: {item['name']}\n"
            f"Category: {item.get('category', 'Unknown')}\n"
            f"Submitted by: @{item.get('owner_username', 'NoUsername')} (ID: {item.get('owner')})\n"
            f"Base Price: {item['price']:,} PD\n"
            f"Current Bid: {item['price']:,} PD\n"
            f"Boosted: {item.get('boosted')}\n"
        )
    bidding_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_{item_id}"),
            InlineKeyboardButton("💵 Place Bid", url=f"https://t.me/{BOT_USERNAME}?start=bid_{item_id}")
        ]
    ])
    chosen_photo = (item.get("info_photo")
                    or item.get("ivs_photo")
                    or item.get("moveset_photo")
                    or item.get("tms_photo"))
    try:
        # Post in Auction Channel
        if chosen_photo:
            msg = await context.bot.send_photo(
                chat_id=AUCTION_CHANNEL,
                photo=chosen_photo,
                caption=channel_caption,
                reply_markup=bidding_keyboard,
                parse_mode=ParseMode.HTML
            )
        else:
            msg = await context.bot.send_message(
                chat_id=AUCTION_CHANNEL,
                text=channel_caption,
                reply_markup=bidding_keyboard,
                parse_mode=ParseMode.HTML
            )
        item['message_id'] = msg.message_id
        # Also post in Trade Group
        try:
            if chosen_photo:
                trade_msg = await context.bot.send_photo(
                    chat_id=TRADE_GROUP,
                    photo=chosen_photo,
                    caption=channel_caption,
                    reply_markup=bidding_keyboard,
                    parse_mode=ParseMode.HTML
                )
            else:
                trade_msg = await context.bot.send_message(
                    chat_id=TRADE_GROUP,
                    text=channel_caption,
                    reply_markup=bidding_keyboard,
                    parse_mode=ParseMode.HTML
                )
            item['trade_message_id'] = trade_msg.message_id
        except Exception as e:
            logger.error(f"Failed to post to Trade Group: {e}")
        item['highest_bid'] = item['price']
        broadcast_text = f"✅ {name} approved by {admin_name} {admin_username}".strip()
        for aid in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=aid, text=broadcast_text)
            except Exception as e:
                logger.error(f"Error broadcasting approval to admin {aid}: {e}")
    except Exception as e:
        logger.error(f"Failed to post to channel: {e}")
        await query.message.reply_text("⚠️ Failed to post to channel!")

async def handle_admin_unapprove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Remove buttons from all admin messages for this item
    data = query.data
    item_id = data.split("_", 1)[1]
    await remove_all_admin_buttons_for_item(item_id, context)
    context.user_data["unapprove_item_id"] = item_id
    await context.bot.send_message(chat_id=query.from_user.id, text="🚫 Please type the reason for unapproval (e.g., Low IVs)")
    return UNAPPROVE_REASON

async def process_unapprove_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text
    item_id = context.user_data.get("unapprove_item_id")
    if not item_id:
        await update.message.reply_text("No item found.")
        return ConversationHandler.END
    item = auction_items.get(item_id)
    if not item:
        await update.message.reply_text("Item not found.")
        return ConversationHandler.END
    owner_id = item.get("owner")
    name = item.get("name")
    admin = update.effective_user
    admin_name = admin.full_name
    admin_username = f"@{admin.username}" if admin.username else ""
    try:
        await context.bot.send_message(
            chat_id=owner_id,
            text=f"❌ Your {name} was cancelled for auction.\nReason: {reason}"
        )
    except Exception as e:
        logger.error(f"Error sending unapproval message: {e}")
        await update.message.reply_text("Error sending unapproval message.")
    broadcast_text = f"❌ {name} unapproved by {admin_name} {admin_username}\nReason: {reason}".strip()
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=aid, text=broadcast_text)
        except Exception as e:
            logger.error(f"Error broadcasting unapproval to admin {aid}: {e}")
    context.user_data.pop("unapprove_item_id", None)
    return ConversationHandler.END

# -----------------------
# Refresh Button Handler
# -----------------------
async def handle_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    item_id = query.data.replace("refresh_", "")
    item = auction_items.get(item_id)
    if not item:
        await query.answer("❌ Item not found or auction ended!", show_alert=True)
        return
    alert_msg = (
        f"Item ID: {item_id}\n"
        "Bids refreshed successfully! ✅\n"
        "Join @husbando_waifu"
    )
    await query.answer(alert_msg, show_alert=True)

# -----------------------
# Main Command Handlers (/myitems, /mybids, /all_items)
# -----------------------
async def my_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("💬 Please use this command in a private chat with me.")
        return
    user_id = update.effective_user.id
    items = user_items.get(user_id, [])
    approved_lines = []
    for item_id in items:
        item = auction_items.get(item_id)
        if item and item.get("approved") and item.get("message_id"):
            link = f"https://t.me/{AUCTION_CHANNEL[1:]}/{item['message_id']}"
            approved_lines.append(f'- <a href="{link}">{item["name"]}</a>')
    if not approved_lines:
        await update.message.reply_text("😔 You have no approved items yet.")
        return
    text = "📦 Your approved items:\n\n" + "\n".join(approved_lines)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def my_bids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("💬 Please use this command in a private chat with me.")
        return
    user_id = update.effective_user.id
    bid_lines = []
    for item_id, item in auction_items.items():
        if item.get("approved") and item.get("highest_bidder") == user_id and item.get("message_id"):
            channel_link = f"https://t.me/{AUCTION_CHANNEL[1:]}/{item['message_id']}"
            bid_lines.append(f'- <a href="{channel_link}">{item["name"]}</a>')
    if not bid_lines:
        await update.message.reply_text("😔 You have no active bids.")
        return
    text = "💰 Your active bids:\n\n" + "\n".join(bid_lines)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def all_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("💬 Please use this command in a private chat with me.")
        return
    groups = {}
    for item in auction_items.values():
        if item.get("approved") and item.get("message_id"):
            cat = item.get("category", "Unknown").capitalize()
            if cat not in groups:
                groups[cat] = []
            channel_link = f"https://t.me/{AUCTION_CHANNEL[1:]}/{item['message_id']}"
            groups[cat].append(f'- <a href="{channel_link}">{item["name"]}</a>')
    if not groups:
        await update.message.reply_text("😔 No approved items found.")
        return
    text_lines = []
    for cat in sorted(groups.keys()):
        text_lines.append(f"<b>{cat}:</b>")
        text_lines.extend(groups[cat])
        text_lines.append("")
    text = "\n".join(text_lines)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# -----------------------
# Main Function
# -----------------------

async def last_bid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    buttons = []
    for item_id, item in auction_items.items():
        if item.get("approved") and item.get("message_id"):
            buttons.append([InlineKeyboardButton(item['name'], callback_data=f"viewbids_{item_id}")])

    if not buttons:
        await update.message.reply_text("❌ No approved items found.")
        return

    await update.message.reply_text(
        "📋 Select an item to view all bids:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def show_bids_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    item_id = query.data.split("viewbids_", 1)[-1]
    item = auction_items.get(item_id)

    if not item:
        return await query.edit_message_text("❌ Item not found.")

    bids = item.get("bids", [])
    if not bids:
        return await query.edit_message_text(f"<b>{item['name']}</b>\nNo bids placed yet.", parse_mode=ParseMode.HTML)

    lines = [f"<b>{item['name']}</b> - Bids:"]
    for bid in bids:
        uname = bid.get("username", "(No username)")
        uid = bid.get("user_id")
        amt = bid.get("amount")
        lines.append(f"• @{uname} (ID: <code>{uid}</code>) bid <b>{amt:,}</b>")
    channel_link = f"https://t.me/{AUCTION_CHANNEL[1:]}/{item['message_id']}"
    lines.append(f"\n<a href=\"{channel_link}\">View Auction Post</a>")

    await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# Add to your app handler setup in main()
    application.add_handler(CommandHandler("last_bid", last_bid))
    application.add_handler(CommandHandler("remove_last_bid", remove_last_bid))
    application.add_handler(CallbackQueryHandler(handle_remove_bid_callback, pattern=r"^showremove_"))
    application.add_handler(CallbackQueryHandler(handle_remove_bid_action, pattern=r"^removebid_"))
    application.add_handler(CallbackQueryHandler(show_bids_callback, pattern=r"^viewbids_"))

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_error_handler(error_handler)

    add_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_item_command)],
        states={
            # Category selection, Pokémon Flow, and TMs Flow
            CATEGORY_SELECTION: [CallbackQueryHandler(handle_category)],
            # Pokémon Flow:
            NAME_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
            NAME_CONFIRMATION: [CallbackQueryHandler(handle_name_confirmation)],
            INFO_INPUT: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_info)],
            INFO_CONFIRMATION: [CallbackQueryHandler(handle_info_confirmation)],
            IVS_INPUT: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_ivs)],
            IVS_CONFIRMATION: [CallbackQueryHandler(handle_ivs_confirmation)],
            MOVESET_INPUT: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_moveset)],
            MOVESET_CONFIRMATION: [CallbackQueryHandler(handle_moveset_confirmation)],
            BOOSTED_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_boosted)],
            BOOSTED_CONFIRMATION: [CallbackQueryHandler(handle_boosted_confirmation)],
            PRICE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price)],
            PRICE_CONFIRMATION: [CallbackQueryHandler(handle_price_confirmation)],
            # TMs Flow:
            TMS_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tms_name)],
            TMS_NAME_CONFIRMATION: [CallbackQueryHandler(handle_tms_name_confirmation)],
            TMS_HEXAFWD: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_tms_forward)],
            TMS_HEXAFWD_CONFIRMATION: [CallbackQueryHandler(handle_tms_forward_confirmation)],
            TMS_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tms_price)],
            TMS_PRICE_CONFIRMATION: [CallbackQueryHandler(handle_tms_price_confirmation)],
        },
        fallbacks=[
            CommandHandler("cancel", global_cancel),
            CommandHandler("start", global_cancel)
        ],
        allow_reentry=True
    )

    broadcast_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("message", message_command)],
        states={
            BROADCAST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_text)],
            BROADCAST_CONFIRM: [CallbackQueryHandler(broadcast_confirm, pattern=r"^broadcast_(yes|no)$")]
        },
        fallbacks=[
            CommandHandler("cancel", global_cancel),
            CommandHandler("start", global_cancel)
        ],
        allow_reentry=True
    )

    admin_unapprove_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_admin_unapprove, pattern=r"^unapprove_.*")],
        states={
            UNAPPROVE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_unapprove_reason)]
        },
        fallbacks=[
            CommandHandler("cancel", global_cancel),
            CommandHandler("start", global_cancel)
        ],
        allow_reentry=True
    )

    application.add_handler(add_conv_handler)
    application.add_handler(broadcast_conv_handler)
    application.add_handler(admin_unapprove_conv)
    application.add_handler(CallbackQueryHandler(handle_admin_approve, pattern=r"^approve_.*"))
    application.add_handler(CallbackQueryHandler(handle_refresh, pattern=r"^refresh_.*"))
    application.add_handler(CallbackQueryHandler(handle_retry_bid, pattern=r"^retry_bid_.*"))
    application.add_handler(CallbackQueryHandler(handle_bid_confirmation, pattern=r"^confirm_bid_.*"))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("myitems", my_items))
    application.add_handler(CommandHandler("mybids", my_bids))
    application.add_handler(CommandHandler("all_items", all_items))
    application.add_handler(CommandHandler("stop_submission", stop_submission))
    application.add_handler(CommandHandler("end_auction", end_auction))
    application.add_handler(CommandHandler("start_auction", start_auction))
    application.add_handler(
        MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, handle_bid_in_private)
    )

    async def set_commands(app):
        await app.bot.set_my_commands(BOT_COMMANDS)
    application.post_init = set_commands

    application.add_handler(CommandHandler("last_bid", last_bid))
    application.add_handler(CommandHandler("remove_last_bid", remove_last_bid))
    application.add_handler(CallbackQueryHandler(handle_remove_bid_callback, pattern=r"^showremove_"))
    application.add_handler(CallbackQueryHandler(handle_remove_bid_action, pattern=r"^removebid_"))
    application.add_handler(CallbackQueryHandler(show_bids_callback, pattern=r"^viewbids_"))

    application.run_polling()




# -----------------------
# /remove_last_bid Command Handler (Admin Only)
# -----------------------
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

async def remove_last_bid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    buttons = []
    for item_id, item in auction_items.items():
        if item.get("approved") and item.get("message_id"):
            label = f"{item['name']} - {item_id}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"showremove_{item_id}")])

    if not buttons:
        await update.message.reply_text("❌ No approved Pokémon found.")
        return

    await update.message.reply_text(
        "🗑 Select a Pokémon to remove the last bid:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def handle_remove_bid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    item_id = query.data.split("showremove_", 1)[-1]
    item = auction_items.get(item_id)

    if not item or not item.get("bids"):
        return await query.edit_message_text("❌ No bids found for this item.")

    bids = item["bids"]
    lines = [f"<b>{item['name']}</b> - All Bids:"]
    for bid in bids:
        lines.append(f"• @{bid.get('username')} (<code>{bid.get('user_id')}</code>): <b>{bid.get('amount'):,}</b> PD")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Remove Last Bid", callback_data=f"removebid_{item_id}")]
    ])

    await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def handle_remove_bid_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    item_id = query.data.split("removebid_", 1)[-1]
    item = auction_items.get(item_id)

    if not item or not item.get("bids"):
        return await query.edit_message_text("❌ No bids found to remove.")

    removed_bid = item["bids"].pop()
    previous_bid = item["bids"][-1] if item["bids"] else None

    if previous_bid:
        item["highest_bid"] = previous_bid["amount"]
        item["highest_bidder"] = previous_bid["user_id"]
        item["highest_bidder_username"] = previous_bid["username"]
    else:
        item["highest_bid"] = item["price"]
        item["highest_bidder"] = None
        item["highest_bidder_username"] = None

    new_caption = ""
    if item.get('category') == 'tms':
        new_caption = (
            f"=== TMs Page ===\n{item.get('tms_text', '')}\n\n"
            f"🎮 TMs Name: {item['name']}\n"
            f"Base Price: {item['price']:,} PD\n"
            f"Current Bid: {item['highest_bid']:,} PD\n"
            f"Bidder: @{item['highest_bidder_username'] or item['highest_bidder'] or 'None'}"
        )
    else:
        new_caption = (
            f"=== Info Page ===\n{item.get('info_text', '')}\n\n"
            f"=== IVs Page ===\n{item.get('ivs_text', '')}\n\n"
            f"=== Moveset Page ===\n{item.get('moveset_text', '')}\n\n"
            f"Name: {item['name']}\n"
            f"Category: {item.get('category', 'Unknown')}\n"
            f"Submitted by: @{item.get('owner_username', 'NoUsername')} (ID: {item.get('owner')})\n"
            f"Base Price: {item['price']:,} PD\n"
            f"Current Bid: {item['highest_bid']:,} PD\n"
            f"Boosted: {item.get('boosted')}\n"
            f"Bidder: @{item['highest_bidder_username'] or item['highest_bidder'] or 'None'}"
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_{item_id}"),
         InlineKeyboardButton("💵 Place Bid", url=f"https://t.me/{BOT_USERNAME}?start=bid_{item_id}")]
    ])

    try:
        await context.bot.edit_message_caption(
            chat_id=AUCTION_CHANNEL,
            message_id=item.get("message_id"),
            caption=new_caption,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await context.bot.edit_message_text(
            chat_id=AUCTION_CHANNEL,
            message_id=item.get("message_id"),
            text=new_caption,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

    if item.get("trade_message_id"):
        try:
            await context.bot.edit_message_caption(
                chat_id=TRADE_GROUP,
                message_id=item.get("trade_message_id"),
                caption=new_caption,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await context.bot.edit_message_text(
                chat_id=TRADE_GROUP,
                message_id=item.get("trade_message_id"),
                text=new_caption,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

    await query.edit_message_text(f"✅ Last bid removed for {item['name']}.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"⚠️ Exception occurred: {context.error}")


if __name__ == '__main__':
    main()



