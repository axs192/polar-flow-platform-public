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
            endpoint="/exercises?samples=True&zones=True&route=False",
            headers=headers,
            access_token=access_token,
        )

    def get_exercise(self, access_token, exerciseId):
        """
        Get users exercise using hashed id. Only Exercises uploaded to Flow in the
        last 30 days are available.

        :param access_token: access token of the user
        :param exerciseId: Hashed exercise id.
        """

        headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}

        endpoint = f"/exercises/{exerciseId}?samples=True&zones=True&route=False"

        return self._get(endpoint=endpoint, headers=headers, access_token=access_token)

    def get_exercise_FIT_file(self, access_token, exerciseId):
        """
        Get users exercise using hashed id. Only Exercises uploaded to Flow in the
        last 30 days are available.

        :param access_token: access token of the user
        :param exerciseId: Hashed exercise id.
        """

        headers = {"Accept": "*/*", "Authorization": f"Bearer {access_token}"}

        endpoint = f"/exercises/{exerciseId}/fit"

        return self._get(endpoint=endpoint, headers=headers, access_token=access_token)
