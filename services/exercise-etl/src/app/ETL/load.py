import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class loader:
    """Encapsulates an Amazon DynamoDB table of exercise data.

    Example data structure for a exercise record in this table:
        {
            "uid": "123456",
            "date": "2026-02-22",
            "exerciseID": "123456",
            "sport": "RUNNING",
            ..........
    """

    def __init__(self):
        """
        :param dyn_resource: A Boto3 DynamoDB resource.
        """
        self.dyn_resource = boto3.resource("dynamodb")
        self.table = None

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
        Adds a exercise record to the table.

        :param uid: The ID of the user.
        :param date: The date of the record.
        :param info: The data to insert into attributes, to note this will
        be flattened.
        """
        if "uid" not in load:
            logger.error("Couldn't add exercise record %s to table %s. Here's why: %s: %s")
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
