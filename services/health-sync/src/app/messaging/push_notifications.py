"""
Module to send notifications via the WhatsApp Graph API
"""

import logging
import os

import requests
from dotenv import load_dotenv

from src.app.helpers.config_loader import config_loader
from src.app.messaging.create_message import Create_Message

load_dotenv()


class Push_Notification:
    def __init__(self, response):
        config = config_loader()
        if not config:
            logging.error("Push_Notifcation: No configuration loaded")
        self.auth_token = config["META_AUTH"]
        if not response:
            logging.error("Push_Notification: No message provided")
        self.message, self.title = Create_Message(response).create_message()
        self.api_v = "v22.0"
        self.to_mobile = os.environ["TO_MOBILE"]
        self.from_mobile = os.environ["FROM_MOBILE"]
        self.url = f"https://graph.facebook.com/v22.0/{self.from_mobile}/messages"
        # self.email = os.environ["EMAIL"]
        try:
            logging.info("Sending push notification")
        except Exception as e:
            logging.exception("Error during sending push notification: %s", e)

    def send_note(self):
        """
        Add URL. This sends a push notification - type = note to a device or a person
        """

        url = self.url
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
        }
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self.to_mobile,
            "type": "template",
            "template": {
                "name": "daily_update",
                "language": {"code": "en"},
                "components": [
                    {
                        "type": "header",
                        "parameters": [
                            {"type": "text", "parameter_name": "title", "text": self.title}
                        ],
                    },
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "parameter_name": "update", "text": self.message}
                        ],
                    },
                ],
            },
        }

        response = requests.post(url=url, headers=headers, json=data, timeout=30)

        if response.status_code != 200:
            error = response.json()
            logging.error(
                "Error during sending push notification: %s, error code: %s",
                error["error"]["type"],
                response.status_code,
            )
        else:
            logging.info("Successfully sent notification")
            logging.debug(response)
