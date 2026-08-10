#!/usr/bin/env python

from src.app.accesslink.endpoints.resource import Resource


class Heart_Rate(Resource):
    """This resource provides all the necessary functions to get heart rate between two dates

    https://www.polar.com/accesslink-api/?python#get-continuous-heart-rate-samples-with-range
    """

    def get_heartrate_between_date(self, access_token, from_date, to_date):
        """
        Get users continuous heart rate values for given date range

        :param access_token: access token of the user
        :param from: Start date in format YYYY-MM-DD.
        :param to: End date in format YYYY-MM-DD. If not given, defaults to today.
        """
        headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}

        return self._get(
            endpoint=f"/users/continuous-heart-rate?from={from_date}&to={to_date}",
            headers=headers,
            access_token=access_token,
        )
