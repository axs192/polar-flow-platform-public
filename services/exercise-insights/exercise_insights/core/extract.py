import logging

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class dynamo_extract:
    """Encapsulates an Amazon DynamoDB table of health data.

    Example data structure for a health record in this table:
        {
            "uid": 1234568,
            "date": "12/31/2025",
            "hrv": 55.5,
            "average_daily_hr": 70,
            "steps": 8000,
            "rhr": "A washed up pitcher flashes through his career.",
            "total_sleep": 4987,
            "activity_score": 30.00,
            "vigorous_activity": 5.00
            "moderate_activity":15.00
            "dhrps":0.00083
            "max_hr":180
        }
    """

    def __init__(self, table: str):
        """
        :param dyn_resource: A Boto3 DynamoDB resource.
        """
        self.dyn_resource = boto3.resource("dynamodb")
        self.exists(table)

    def exists(self, table_name):
        """
        Determines whether a table exists. As a side effect, stores the table in
        a member variable.

        :param table_name: The name of the table to check.
        :return: True when the table exists; otherwise, False.
        """
        try:
            table = self.dyn_resource.Table(table_name)
            table.load()
            exists = True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                exists = False
            else:
                logger.error(
                    "Couldn't check for existence of %s. Here's why: %s: %s",
                    table_name,
                    err.response["Error"]["Code"],
                    err.response["Error"]["Message"],
                )
                raise
        else:
            self.table = table
        return exists

    def add_record(self, load):
        """
        Adds a health record to the table.

        :param uid: The ID of the user.
        :param date: The date of the record.
        :param info: The data to insert into attributes, to note this will
        be flattened.
        """
        if "uid" not in load:
            logger.error("Couldn't add health record %s to table %s. Here's why: %s: %s")
            raise

        item = {}

        for k, v in load.items():
            item[k] = v

        try:
            self.table.put_item(Item=item)
            logging.info("Added new record for: %s, into table: %s", load["uid"], self.table.name)
        except ClientError as err:
            logger.error(
                "Couldn't add health record %s to table %s. Here's why: %s: %s",
                load["uid"],
                self.table.name,
                err.response["Error"]["Code"],
                err.response["Error"]["Message"],
            )
            raise

    def get_record(self, uid, date):
        """
        Gets health data from the table for a specific date.

        :param uid: The User_ID.
        :param date: The date in ISO format.
        :return: The data about the requested record.
        """
        try:
            response = self.table.get_item(Key={"uid": uid, "date": date})
            return response["Item"]
        except ClientError as err:
            logger.error(
                "Couldn't get record from %s from table %s. Here's why: %s: %s",
                date,
                self.table.name,
                err.response["Error"]["Code"],
                err.response["Error"]["Message"],
            )
            raise

    # Get latest date
    def get_latest_date(self, uid):
        """
        Gets the last date an entry was entered

        :param self: Description
        :param uid: The uid for the table
        """
        try:
            response = self.table.query(
                KeyConditionExpression=Key("uid").eq(uid), Limit=1, ScanIndexForward=False
            )
            return response["Items"][0]["date"]
        except ClientError as err:
            logger.error(
                "Couldn't get record from table %s. Here's why: %s: %s",
                self.table.name,
                err.response["Error"]["Code"],
                err.response["Error"]["Message"],
            )
            raise

    def get_records_bt_dates(self, uid: str, start_date: str, end_date: str) -> list:
        """_summary_

        Parameters
        ----------
        uid : str
            _description_
        start_date : str
            _description_
        end_date : str
            _description_

        Returns
        -------
        list
            _description_
        """
        # TODO: Add Try Catch Method
        response = self.table.query(
            KeyConditionExpression=Key("uid").eq(uid) & Key("date").between(start_date, end_date)
        )
        items = response["Items"]

        return items
