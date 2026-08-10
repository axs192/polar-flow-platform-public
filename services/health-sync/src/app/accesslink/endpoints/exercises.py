#!/usr/bin/env python

from src.app.accesslink.endpoints.resource import Resource


class Exercises(Resource):
    """
    This resource provides all the necessary functions to list all exercise information
    from a user within last 30 days

    https://www.polar.com/accesslink-api/?python#list-exercises
    """

    def list_exercise(self, access_token):
        """
        Returns a List of all exercises completed within 30 Days

        :param access_token: access token of the user
        """

        headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}

        return self._get(
            endpoint="/exercises?samples=True&zones=False&route=False",
            headers=headers,
            access_token=access_token,
        )
