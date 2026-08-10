#!/usr/bin/env python

from src.app.accesslink.endpoints.resource import Resource


class Sleep(Resource):
    """This resource provides all the necessary functions to get sleep for date

    https://www.polar.com/accesslink-api/?python#get-sleep
    """

    def get_sleep_for_date(self, access_token, date):
        """
        Get users sleep data values for given date rage

        :param access_token: access token of the user
        :param date: date in format YYYY-MM-DD. Date of sleep as ISO-8601 date string
        """
        headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}

        return self._get(
            endpoint=f"/users/sleep/{date}", headers=headers, access_token=access_token
        )
