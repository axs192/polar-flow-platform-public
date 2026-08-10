"""Sends the Q&A response back to the user over the WhatsApp Graph API."""

import logging
import os

import requests

from exercise_insights.shared.config_loader import config_loader


class Push_Notification:
    def __init__(self):
        config = config_loader()
        if not config:
            print("Push_Notification: No configuration loaded")
        self.auth_token = config["META_AUTH"]
        self.api_v = "v22.0"
        self.to_mobile = os.environ["TO_MOBILE"]
        self.from_mobile = os.environ["FROM_MOBILE"]
        self.url = f"https://graph.facebook.com/v22.0/{self.from_mobile}/messages"
        self.max_len = int(os.environ["MAX_LEN"])

    def send_note(self, message):
        """Sends a WhatsApp text message, splitting it if over max_len."""
        if len(message) <= self.max_len:
            headers = {
                "Authorization": f"Bearer {self.auth_token}",
                "Content-Type": "application/json",
            }
            data = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": self.to_mobile,
                "type": "text",
                "text": {"body": message},
            }

            response = requests.post(url=self.url, headers=headers, json=data, timeout=30)

            if response.status_code != 200:
                error = response.json()
                logging.error(
                    "Error during sending push notification: %s, error code: %s",
                    error["error"]["type"],
                    response.status_code,
                )
                return
            logging.info("Successfully sent notification")
            return

        split_index = message.rfind("\n\n", 0, self.max_len)
        if split_index == -1:
            split_index = message.rfind("\n", 0, self.max_len)
        if split_index == -1:
            split_index = message.rfind(" ", 0, self.max_len)

        if split_index <= 0:
            split_index = self.max_len

        first = message[:split_index].strip()
        remainder = message[split_index:].strip()

        self.send_note(first)
        self.send_note(remainder)
