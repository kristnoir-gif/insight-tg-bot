"""
Простой HTTP сервер для обслуживания Telegram Web App.
Запускается вместе с ботом для работы Web App кнопки.
"""
import logging
from pathlib import Path
from aiohttp import web

logger = logging.getLogger(__name__)

# Путь к файлу Web App
WEBAPP_DIR = Path(__file__).parent
WEBAPP_FILE = WEBAPP_DIR / "webapp_channels.html"


async def serve_webapp(request):
    """Обслуживает HTML файл Web App."""
    try:
        with open(WEBAPP_FILE, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        return web.Response(
            text=html_content,
            content_type='text/html',
            headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, OPTIONS',
                'Access-Control-Allow-Headers': '*',
            }
        )
    except FileNotFoundError:
        return web.Response(text="Web App file not found", status=404)
    except Exception as e:
        logger.error(f"Error serving webapp: {e}")
        return web.Response(text=f"Error: {str(e)}", status=500)


async def get_channels_api(request):
    """API endpoint для получения списка каналов."""
    from db import get_all_channels_for_admin
    import json
    
    try:
        channels = get_all_channels_for_admin()
        return web.json_response(channels)
    except Exception as e:
        logger.error(f"Error in channels API: {e}")
        return web.json_response(
            {'error': str(e)},
            status=500
        )


def setup_webapp_server(app: web.Application):
    """Настраивает маршруты для Web App."""
    app.router.add_get('/webapp/channels', serve_webapp)
    app.router.add_get('/api/channels', get_channels_api)
    logger.info("Web App server routes configured")


async def start_webapp_server(host='0.0.0.0', port=8081):
    """Запускает отдельный HTTP сервер для Web App."""
    app = web.Application()
    setup_webapp_server(app)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, host, port)
    await site.start()
    
    logger.info(f"Web App server started on http://{host}:{port}/webapp/channels")
    return runner
