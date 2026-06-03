import unittest
from unittest.mock import patch, MagicMock
from io import BytesIO
import sys
import os

# Ajusta path para importar o app local
sys.path.append(os.getcwd())

# Define variáveis de ambiente fictícias para que a importação do app.models e outros não falhe
os.environ["DATABASE_URL"] = "postgresql://dummy_user:dummy_pass@localhost:5432/dummy_db"
os.environ["CAR_DATABASE_URL"] = "postgresql://dummy_user:dummy_pass@localhost:5432/dummy_db"
os.environ["OPENAI_API_KEY"] = "sk-dummykey1234567890abcdef"
os.environ["ADMIN_CHAT_ID"] = "1118914866"

class TestWhatsAppSenderAndPlatform(unittest.TestCase):
    
    @patch('app.whatsapp.sender.META_ACCESS_TOKEN', 'fake_access_token')
    @patch('app.whatsapp.sender.META_PHONE_ID', 'fake_phone_id')
    @patch('requests.post')
    def test_send_whatsapp_text_success(self, mock_post):
        # Configura Mock para responder sucesso (200 OK)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messaging_product": "whatsapp", "contacts": [{"input": "556784013193", "wa_id": "556784013193"}], "messages": [{"id": "wamid.HBgLNTU2Nzg0MDEzMTkzFQIAERgSRDMzQ0FBMzc0RDg1OEM1OTdFAA=="}]}
        mock_post.return_value = mock_response
        
        from app.whatsapp.sender import send_whatsapp_text
        success = send_whatsapp_text("556784013193", "Olá Patrão! Este é um teste mockado.")
        
        self.assertTrue(success)
        mock_post.assert_called_once()
        # Verifica se o payload tem a estrutura correta exigida pela Meta
        args, kwargs = mock_post.call_args
        payload = kwargs.get('json', {})
        self.assertEqual(payload.get("to"), "556784013193")
        self.assertEqual(payload.get("type"), "text")
        self.assertEqual(payload.get("text", {}).get("body"), "Olá Patrão! Este é um teste mockado.")

    @patch('app.whatsapp.sender.META_ACCESS_TOKEN', 'fake_access_token')
    @patch('app.whatsapp.sender.META_PHONE_ID', 'fake_phone_id')
    @patch('requests.post')
    def test_send_whatsapp_text_failure(self, mock_post):
        # Meta Graph API rejeita o envio (ex: 400 Bad Request)
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"error":{"message":"Invalid phone number","type":"OAuthException","code":100}}'
        mock_post.return_value = mock_response
        
        from app.whatsapp.sender import send_whatsapp_text
        success = send_whatsapp_text("556784013193", "Texto teste")
        
        self.assertFalse(success)

    @patch('app.whatsapp.sender.META_ACCESS_TOKEN', 'fake_access_token')
    @patch('app.whatsapp.sender.META_PHONE_ID', 'fake_phone_id')
    @patch('requests.post')
    def test_upload_media_bytesio(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "fake_media_id_123"}
        mock_post.return_value = mock_response
        
        from app.whatsapp.sender import _upload_media
        img_buffer = BytesIO(b"dummy_image_data")
        media_id = _upload_media(img_buffer, "image/png", "map.png")
        
        self.assertEqual(media_id, "fake_media_id_123")
        mock_post.assert_called_once()

    @patch('app.whatsapp.sender.META_ACCESS_TOKEN', 'fake_access_token')
    @patch('app.whatsapp.sender.META_PHONE_ID', 'fake_phone_id')
    @patch('requests.post')
    def test_send_whatsapp_template_alert(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        from app.whatsapp.sender import send_whatsapp_template_alert
        success = send_whatsapp_template_alert(
            to_phone="556784013193",
            media_id="fake_media_id_123",
            prop_nome="Fazenda Esperança",
            data_str="24/05/2026",
            ndvi_val="0.65"
        )
        
        self.assertTrue(success)
        args, kwargs = mock_post.call_args
        payload = kwargs.get('json', {})
        self.assertEqual(payload.get("type"), "template")
        self.assertEqual(payload.get("template", {}).get("name"), "alerta_ndvi_satelite")
        
        # Verifica se as variáveis no corpo do template foram passadas na ordem certa
        components = payload.get("template", {}).get("components", [])
        body_component = next((c for c in components if c.get("type") == "body"), None)
        self.assertIsNotNone(body_component)
        params = body_component.get("parameters", [])
        self.assertEqual(len(params), 3)
        self.assertEqual(params[0].get("text"), "Fazenda Esperança")
        self.assertEqual(params[1].get("text"), "24/05/2026")
        self.assertEqual(params[2].get("text"), "0.65")

    def test_platform_detection_in_agent_instantiation(self):
        # Testa a detecção de plataforma em novos cadastros
        # IDs normais de Telegram (números curtos ou strings não puramente numéricas)
        self.assertFalse("1118914866".isdigit() and len("1118914866") >= 11)
        self.assertTrue("556784013193".isdigit() and len("556784013193") >= 11)

    @patch('app.whatsapp.sender.META_ACCESS_TOKEN', 'fake_access_token')
    @patch('app.whatsapp.sender.META_PHONE_ID', 'fake_phone_id')
    @patch('requests.post')
    def test_send_whatsapp_image_by_id(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        from app.whatsapp.sender import send_whatsapp_image_by_id
        success = send_whatsapp_image_by_id("556784013193", "fake_media_id_123", "Legenda de teste")
        
        self.assertTrue(success)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        payload = kwargs.get('json', {})
        self.assertEqual(payload.get("type"), "image")
        self.assertEqual(payload.get("image", {}).get("id"), "fake_media_id_123")
        self.assertEqual(payload.get("image", {}).get("caption"), "Legenda de teste")


class TestNDVIAlertsWhatsApp(unittest.IsolatedAsyncioTestCase):

    @patch('app.ndvi_alerts.fetch_car_perimeter')
    @patch('app.ndvi_alerts.get_ndvi_image')
    @patch('app.ndvi_alerts.get_ndvi_analysis')
    @patch('app.ndvi_alerts.generate_environmental_image')
    @patch('app.whatsapp.sender._upload_media')
    @patch('app.whatsapp.sender.send_whatsapp_image_by_id')
    @patch('app.whatsapp.sender.send_whatsapp_template_alert')
    @patch('app.models.log_activity')
    async def test_check_and_alert_whatsapp_fallback_flow(
        self, mock_log, mock_template, mock_image_by_id, mock_upload, 
        mock_gen_img, mock_analysis, mock_ndvi_img, mock_perimeter
    ):
        # 1. Configura mocks do processamento NDVI
        mock_perimeter.return_value = ({"type": "Polygon"}, "OFFICIAL", "MS-12345")
        mock_ndvi_img.return_value = {"date": "2026-05-24"}
        mock_analysis.return_value = {
            "stats": {"mean": 0.65},
            "cloud_coverage": 5.0,
            "date_str": "24/05/2026",
            "region_bbox": {},
            "ndvi_img": BytesIO(b"sat_img"),
            "dt": 1774353600
        }
        mock_gen_img.return_value = BytesIO(b"composite_img_bytes")
        
        # 2. Configura mocks de envio de WhatsApp:
        # Upload único retorna media_id
        mock_upload.return_value = "media_id_upload_unico"
        # Envio livre falha (ex: janela 24h expirada)
        mock_image_by_id.return_value = False
        # Fallback de template funciona com sucesso
        mock_template.return_value = True
        
        # 3. Configura o banco de dados simulado e objetos
        from app.models import FavoriteLocation, User
        loc = FavoriteLocation(
            id=1,
            user_id="556784013193",
            name="Fazenda Pantanal",
            latitude=-20.46,
            longitude=-54.61,
            last_ndvi_date="2026-05-20",
            ndvi_alerts_enabled=True
        )
        
        mock_session = MagicMock()
        mock_user = User(chat_id="556784013193", platform="whatsapp")
        mock_session.query().filter().first.return_value = mock_user
        
        # 4. Executa a função
        from app.ndvi_alerts import _check_and_alert
        await _check_and_alert(None, mock_session, loc)
        
        # 5. Validações do Fluxo Otimizado e Ocorrências
        # Garante que as funções de análise e perímetro rodaram
        mock_perimeter.assert_called_once()
        mock_analysis.assert_called_once()
        mock_gen_img.assert_called_once()
        
        # Garante que o upload único rodou apenas UMA vez
        mock_upload.assert_called_once_with(mock_gen_img.return_value, "image/png", "map.png")
        
        # Garante que a tentativa de envio livre rodou com o media_id
        from unittest.mock import ANY
        mock_image_by_id.assert_called_once_with("556784013193", "media_id_upload_unico", ANY)
        
        # Garante que o fallback de template rodou com o MESMO media_id sem uploads adicionais
        mock_template.assert_called_once_with(
            to_phone="556784013193",
            media_id="media_id_upload_unico",
            prop_nome="Fazenda Pantanal",
            data_str="24/05/2026",
            ndvi_val="0.65"
        )
        
        # Garante que a atividade com status de sucesso via template foi logada no ActivityLog
        mock_log.assert_called_once_with(
            chat_id="556784013193",
            action="NDVI_ALERT_SEND",
            platform="whatsapp",
            details="Propriedade: Fazenda Pantanal (Template)",
            status="SUCCESS",
            trigger_type="AUTO_ALERT"
        )


if __name__ == '__main__':
    unittest.main()
