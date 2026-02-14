import asyncio
from app.models import init_db
from app.bot import (
    create_bot_application, start, status, current_analysis, future_market,
    sync_history, list_users, start_feedback, receive_feedback, 
    cancel_feedback, start_weather, receive_weather_location, cancel_weather,
    start_env_analysis, receive_env_location, cancel_env,
    start_broadcast, send_broadcast, cancel_broadcast,
    handle_keyboard_buttons, WAITING_FEEDBACK, WAITING_WEATHER_LOCATION, 
    WAITING_ENV_LOCATION, WAITING_BROADCAST_MESSAGE,
    WAITING_LOCATION_MENU, WAITING_LOCATION_NAME, WAITING_LOCATION_COORDS, WAITING_LOCATION_DELETE,
    handle_location_buttons, receive_location_name, receive_location_coords, confirm_delete_location,
    cancel_locations, list_all_locations_admin
)


from app.scheduler import setup_scheduler
from telegram.ext import CommandHandler, MessageHandler, filters, ConversationHandler

async def post_init(application):
    print("Setting up Scheduler...")
    scheduler = setup_scheduler(application)
    scheduler.start()

def main():
    # Initialize Database
    print("Initializing Database...")
    init_db()
    
    # Create Bot Application with post_init hook
    print("Setting up Bot...")
    application = create_bot_application(post_init=post_init)
    
    # Locations Conversation Handler
    locations_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📌 Minhas Propriedades$"), handle_keyboard_buttons)
        ],
        states={
            WAITING_LOCATION_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_location_buttons)
            ],
            WAITING_LOCATION_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_location_name)
            ],
            WAITING_LOCATION_COORDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_location_coords)
            ],
            WAITING_LOCATION_DELETE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete_location)
            ]
        },
        fallbacks=[CommandHandler("cancelar", cancel_locations)]
    )

    # Feedback Conversation Handler
    feedback_handler = ConversationHandler(
        entry_points=[
            CommandHandler("feedback", start_feedback),
            MessageHandler(filters.Regex("^💬 Feedback$"), start_feedback)
        ],
        states={
            WAITING_FEEDBACK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_feedback)
            ]
        },
        fallbacks=[CommandHandler("cancelar", cancel_feedback)]
    )
    
    # Weather Conversation Handler
    weather_handler = ConversationHandler(
        entry_points=[
            CommandHandler("clima", start_weather),
            MessageHandler(filters.Regex("^🌧️ Precipitação$"), start_weather)
        ],
        states={
            WAITING_WEATHER_LOCATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_weather_location)
            ]
        },
        fallbacks=[CommandHandler("cancelar", cancel_weather)]
    )
    
    # Broadcast Conversation Handler
    broadcast_handler = ConversationHandler(
        entry_points=[
            CommandHandler("anunciar", start_broadcast),
            MessageHandler(filters.Regex("^📢 Enviar Anúncio$"), start_broadcast)
        ],
        states={
            WAITING_BROADCAST_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, send_broadcast)
            ]
        },
        fallbacks=[CommandHandler("cancelar", cancel_broadcast)]
    )
    
    # Environmental Analysis Conversation Handler
    env_handler = ConversationHandler(
        entry_points=[
            CommandHandler("ambiental", start_env_analysis),
            MessageHandler(filters.Regex("^🌿 Análise Ambiental$"), start_env_analysis)
        ],
        states={
            WAITING_ENV_LOCATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_env_location)
            ]
        },
        fallbacks=[CommandHandler("cancelar", cancel_env)]
    )
    
    # Add Handlers

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("atual", current_analysis))
    application.add_handler(CommandHandler("futuro", future_market))
    application.add_handler(CommandHandler("importar", sync_history))
    application.add_handler(CommandHandler("usuarios", list_users))
    application.add_handler(CommandHandler("admin_locais", list_all_locations_admin))
    
    # Conversation Handlers
    application.add_handler(locations_handler)
    application.add_handler(feedback_handler)
    application.add_handler(weather_handler)
    application.add_handler(env_handler)
    application.add_handler(broadcast_handler)

    
    # Keyboard button handler (must be last to not interfere with other handlers)
    application.add_handler(MessageHandler(
        filters.Regex("^(📊 Cotação Atual|🔮 Mercado Futuro|🌧️ Precipitação|🌿 Análise Ambiental|📢 Enviar Anúncio|📈 Status|📥 Importar Histórico|👥 Lista de Usuários|💬 Feedback|📌 Minhas Propriedades)$"),
        handle_keyboard_buttons
    ))


    
    # Run Bot
    print("Starting Bot...")
    application.run_polling()

if __name__ == "__main__":
    main()
