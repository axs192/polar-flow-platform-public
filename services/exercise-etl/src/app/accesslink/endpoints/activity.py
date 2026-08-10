#!/usr/bin/env python

from src.app.accesslink.endpoints.resource import Resource


class Activty(Resource):
    """This resource provides all the necessary functions to manage Daily Activty.

    https://www.polar.com/accesslink-api/?http#daily-activity--beta-
    """

    def get_activities_between_date(self, access_token, from_date, to_date):
        """
        List activities for given date range

        List users activities available in AccessLink for given date range.
        From date cannot be older than 365 days from today and maximum range between from date and to date is 28 days.

        :param access_token: access token of the user
        :param from: Start date in format YYYY-MM-DD.
        :param to: End date in format YYYY-MM-DD. If not given, defaults to today.
        """
        headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}

        return self._get(
            endpoint=f"/users/activities/?from={from_date}&to={to_date}",
            headers=headers,
            access_token=access_token,
        )
