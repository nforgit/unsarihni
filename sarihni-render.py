import os
import logging
from collections import OrderedDict
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import Forbidden, TelegramError

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Suppress HTTP request logs (e.g., HTTP 200 OK)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Fetch Bot Token from Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN", "8925774805:AAGV6JfHwJOzStox7vC1-lsyOntQ6u_NBg4")
MAX_REPLY_MAP_SIZE = 1000

TERMS_TEXT = """بإستخدامك لبوت صارحني ، أنت توافق على:  
  
- لا تستخدم خدماتنا لانتهاك قوانين بلدك.  
- لا تروج للعنف من خلال البوت.  
- لا تنشر مواد إباحية من خلال البوت.  
- إتباع شروط إستخدام بوت صارحني بالكامل  
  
نحتفظ بالحق في تحديث شروط الإستخدام هذه في وقت لاحق."""

ACTIVE_SESSION_TEXT = """▪️ أنت بالفعل قمت بالدخول إلى رابط هذا الشخص  
▫️ لذلك فقط أرسل رسالتك له"""

SENT_CONFIRMATION_TEXT = "✅ تم إرسال رسالتك بسرية و نجاح ."


def sanitize_markdown(text: str) -> str:
    """Escape Markdown special characters in string fields."""
    if not text:
        return ""
    for char in ["_", "*", "`", "["]:
        text = text.replace(char, f"\\{char}")
    return text


def record_reply_mapping(bot_data: dict, forwarded_msg_id: int, sender_id: int, original_msg_id: int) -> None:
    """Safely store reply mappings with a cap to avoid memory leakage."""
    if "reply_map" not in bot_data:
        bot_data["reply_map"] = OrderedDict()
    
    reply_map: OrderedDict = bot_data["reply_map"]
    reply_map[forwarded_msg_id] = {
        "sender_id": sender_id,
        "msg_id": original_msg_id
    }
    
    while len(reply_map) > MAX_REPLY_MAP_SIZE:
        reply_map.popitem(last=False)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return

    bot_username = context.bot.username
    user_info = f"{user.full_name} (@{user.username or 'NoUsername'}, ID: {user.id})"

    if context.args:
        target_id_str = context.args[0]
        
        try:
            target_id = int(target_id_str)
        except ValueError:
            logger.info(f"[ACTION] User {user_info} attempted invalid start parameter: {target_id_str}")
            await update.message.reply_text("الرابط غير صالح.")
            return

        if target_id == user.id:
            logger.info(f"[ACTION] User {user_info} opened their own start link.")
            await update.message.reply_text("هذا هو الرابط الخاص بك! قم بنشره ليراسلُك الآخرون.")
            return

        if context.user_data.get("target_id") == target_id:
            logger.info(f"[ACTION] User {user_info} accessed active link session for Target ID: {target_id}")
            await update.message.reply_text(ACTIVE_SESSION_TEXT)
            return

        context.user_data["target_id"] = target_id
        logger.info(f"[ACTION] User {user_info} connected to Target ID: {target_id}")
        await update.message.reply_text(TERMS_TEXT)
        return

    logger.info(f"[ACTION] User {user_info} generated their personal link.")
    personal_link = f"https://t.me/{bot_username}?start={user.id}"
    msg = (
        f"مرحباً بك يا {sanitize_markdown(user.full_name)} في بوت صارحني! 👋\n\n"
        f"رابطك الخاص هو:\n`{personal_link}`\n\n"
        f"قم بوضع هذا الرابط في البايو الخاص بك لاستقبال الرسائل."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def handle_incoming_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return

    target_id = context.user_data.get("target_id")
    user_info = f"{user.full_name} (@{user.username or 'NoUsername'}, ID: {user.id})"
    
    msg_type = "text" if update.message.text else ("caption" if update.message.caption else "media/other")
    content_text = update.message.text or update.message.caption or f"[{update.message.effective_attachment.__class__.__name__ if update.message.effective_attachment else 'Media'}]"

    # Flow A: Owner replying to an incoming sarahne message
    if update.message.reply_to_message:
        reply_map = context.bot_data.get("reply_map", {})
        original_msg_id = update.message.reply_to_message.message_id

        if original_msg_id in reply_map:
            mapping = reply_map[original_msg_id]
            sender_id = mapping["sender_id"]
            sent_msg_id = mapping["msg_id"]

            try:
                await update.message.copy(
                    chat_id=sender_id,
                    reply_to_message_id=sent_msg_id
                )
                logger.info(f"[ACTION] Owner {user_info} replied to Original Sender ID: {sender_id} | Content ({msg_type}): {content_text}")
                await update.message.reply_text("تم إرسال ردك بنجاح.")
            except Forbidden:
                logger.warning(f"[ACTION] Failed to reply: Sender ID {sender_id} blocked the bot.")
                await update.message.reply_text("عذراً، تعذر إرسال الرد لأن المستخدم قام بحظر البوت.")
            except TelegramError as e:
                logger.error(f"Failed to forward reply from {user_info} to {sender_id}: {e}")
                await update.message.reply_text("عذراً، تعذر إرسال الرد.")
            return

    # Flow B: User sending a message to a target owner
    if target_id:
        sender_username = f"@{user.username}" if user.username else "لا يوجد اسم مستخدم"
        clean_name = sanitize_markdown(user.full_name)
        identity_header = (
            f"📥 **رسالة جديدة من:** [{clean_name}](tg://user?id={user.id})\n"
            f"👤 **المستخدم:** {sender_username}\n"
            f"🆔 **المعرف:** `{user.id}`\n\n"
        )

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=identity_header,
                parse_mode="Markdown"
            )

            forwarded_msg = await update.message.copy(chat_id=target_id)
            record_reply_mapping(context.bot_data, forwarded_msg.message_id, user.id, update.message.message_id)

            logger.info(f"[ACTION] Sender {user_info} sent message to Target ID: {target_id} | Content ({msg_type}): {content_text}")
            await update.message.reply_text(SENT_CONFIRMATION_TEXT)
        except Forbidden:
            logger.warning(f"[ACTION] Target ID {target_id} blocked the bot. Clearing session.")
            context.user_data.pop("target_id", None)
            await update.message.reply_text("عذراً، تعذر إرسال الرسالة لأن المتلقي حظر البوت أو أوقف حسابه.")
        except TelegramError as e:
            logger.error(f"Failed to send message from {user_info} to Target ID {target_id}: {e}")
            await update.message.reply_text("عذراً، حدث خطأ أثناء إرسال الرسالة.")
        return

    logger.info(f"[ACTION] User {user_info} sent unhandled message | Content ({msg_type}): {content_text}")
    await update.message.reply_text(
        "أنت لست في محادثة مع أحد حالياً. اضغط على رابط شخص ما لمراسلته، أو أرسل /start للحصول على رابطك."
    )


def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, handle_incoming_message)
    )

    # Deployment environment check (Render environment uses WEBHOOK_URL or PORT)
    render_external_url = os.getenv("RENDER_EXTERNAL_URL")
    port = int(os.getenv("PORT", "10000"))

    if render_external_url:
        # Webhook execution mode for Render Web Services
        webhook_url = f"{render_external_url}/webhook"
        logger.info(f"Starting bot in Webhook mode listening on port {port} targeting {webhook_url}")
        
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="webhook",
            webhook_url=webhook_url
        )
    else:
        # Local Polling fallback for offline testing
        logger.info("Starting bot in Polling mode locally...")
        application.run_polling()


if __name__ == "__main__":
    main()