import json
import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal

import boto3

from src.app.ETL.dynamo import Health_Record
from src.app.ETL.extractor import Extractor, HealthData
from src.app.ETL.transform import Transform
from src.app.helpers.config_loader import config_loader
from src.app.messaging.push_notifications import Push_Notification


class Daily_Helper:
    def __init__(self, response: HealthData = None):
        self.response = response
        self.config = config_loader()

    def create_load(self, **kwargs):

        try:
            logging.info("Creating summary stats for health data")

            date = kwargs["date"] if "date" in kwargs else datetime.now() - timedelta(days=1)

            yesterdays_date = date.strftime("%Y/%m/%d")
            logging.info("Creating heatlh data summary stats for %s", yesterdays_date)
            load = {"uid": str(self.config["user_id"]), "date": yesterdays_date}
            if self.response.recharge:
                load.update(
                    {
                        "hrv": self.response.recharge["heart_rate_variability_avg"],
                        "ans_charge": Decimal(str(self.response.recharge["ans_charge"])),
                        "nightly_recharge_status": self.response.recharge[
                            "nightly_recharge_status"
                        ],
                    }
                )
            if self.response.heart_rate:
                times_in_activity = Transform(
                    self.response.heart_rate["heart_rates"][0]
                ).calculate_exercise_brackets()
                moderate_act = times_in_activity["moderate_activity"]
                vigorous_act = times_in_activity["vigorous_activity"]
                average_hr = Transform(
                    self.response.heart_rate["heart_rates"][0]
                ).calculate_average_hr()
                load.update(
                    {
                        "average_daily_hr": average_hr,
                        "activity_score": Transform(
                            self.response.heart_rate
                        ).calculate_activity_score(
                            moderate_act=moderate_act, vigorous_act=vigorous_act
                        ),
                        "vigorous_activity": vigorous_act,
                        "moderate_activity": moderate_act,
                        "max_hr": Decimal(
                            str(
                                Transform(
                                    self.response.heart_rate["heart_rates"][0]
                                ).calculate_maxHR()
                            )
                        ),
                        "min_hr": Decimal(
                            str(
                                Transform(
                                    self.response.heart_rate["heart_rates"][0]
                                ).calculate_minHR()
                            )
                        ),
                    }
                )
            if self.response.sleep:
                load.update(
                    {
                        "sleep_start_time": self.response.sleep["sleep_start_time"],
                        "sleep_end_time": self.response.sleep["sleep_end_time"],
                        "sleep_score": self.response.sleep["sleep_score"],
                        "total_sleep": Transform(self.response.sleep).daily_sleep(),
                    }
                )
            if self.response.physical_info:
                load.update(
                    {
                        "resting-heart-rate": self.response.physical_info["resting-heart-rate"],
                        "maximum-heart-rate": self.response.physical_info["maximum-heart-rate"],
                    }
                )
            if self.response.daily_activity:
                load.update(
                    {
                        "steps": self.response.daily_activity[0]["steps"],
                        "dhrps": Decimal(
                            str(
                                round(
                                    (float(average_hr) / self.response.daily_activity[0]["steps"]),
                                    4,
                                )
                            )
                        ),
                    }
                )

            return load

        except Exception as e:
            logging.error(f"Error creating daily load: {e}")
            raise

    def upload_daily_load(self):
        """
        Function to upload daily file
        """
        try:
            logging.info("Starting Daily Load process...")

            table_name = os.environ["TABLE_NAME"]
            health_record = Health_Record()
            health_record.exists(table_name)

            # Get last date that is within DYNAMODB table
            last_updated = health_record.get_latest_date(uid=self.config["user_id"])

            now = datetime.now()

            # Work out the number of days between today and last_updated
            days = (now.date() - datetime.strptime(last_updated, "%Y/%m/%d").date()).days

            # Remove a day, because it should be added for previous date
            days = days - 1

            # Conditional - if more than 10 days, limit to a 10 look back
            if days > 10:
                days = 10

            if days == 0:
                logging.info("No new information to load, last upload was today..")

            # If the last time updated was yesterday, this will only run once. If updated today, it won't run.
            for x in range(days):
                self.single_day_upload(
                    date_1=(datetime.strptime(last_updated, "%Y/%m/%d") + timedelta(days=x + 2)),
                    date_2=(datetime.strptime(last_updated, "%Y/%m/%d") + timedelta(days=x + 1)),
                    date_3=datetime.strptime(last_updated, "%Y/%m/%d"),
                )

        except Exception as e:
            logging.error(f"Error uploading daily file: {e}")
            raise

    def single_day_upload(self, **kwargs):
        """
        Function to upload single day data file
        """
        try:
            table_name = os.environ["TABLE_NAME"]
            health_record = Health_Record()
            table_exists = health_record.exists(table_name)

            date_1 = kwargs["date_1"]  # Today
            date_2 = kwargs["date_2"]  # Yesterday
            date_3 = kwargs["date_3"]  # LastUpdated

            logging.info(f"Loading for :{date_2}..")

            # Add the dates into the extractor argumemnt
            extract = Extractor().extractor(date_1=date_1, date_2=date_2, date_3=date_3)
            logging.info("Extracted all health data")  # This notification should go into extractor

            load = Daily_Helper(extract).create_load(
                date=date_2
            )  # date_2 should be used, because yesterday date
            Daily_Helper(extract).upload_file(
                date=date_2
            )  # date_2 should be used, because yesterday date

            if not table_exists:
                logging.info(f"\nNo Table called: {table_name}...")
                return
            logging.info("Adding the extraction load to DynamoDB")
            health_record.add_record(load)
            logging.info("Successfully added load")

        except Exception as e:
            logging.error(f"Error uploading daily file: {e}")
            raise

    def send_daily_notification(self):
        """
        Function to send daily notification
        """
        try:
            extraction = Extractor()
            to_date, days = extraction.extraction_decider()
            activity_info = extraction.get_activities_for_date(to_date=to_date, days=days)
            if activity_info:
                logging.info("Successfully retrieved activities.")
            else:
                logging.warning("No activities found for the given date range.")

        except Exception as e:
            logging.error(f"Error retrieving activities: {e}")
            raise

        try:
            result_df = Transform(activity_info, start_date=to_date, days=days).create_metrics()
            logging.info("Metrics created, now sending notification")
        except Exception as e:
            logging.critical(f"Critical error in main: {e}")
            raise

        try:
            Push_Notification(result_df).send_note()
            return
        except Exception as e:
            logging.error(f"Error in sending SMS message: {e}")
            raise

    def upload_file(self, **kwargs):
        """
        Function to upload JSON file into S3 bucket. The bucket name and folder path are defined with env variables.
        """
        # Set before the try block so the except's log call below can't itself
        # raise UnboundLocalError (masking the real error) if a failure hits
        # before bucket_name/filename are ever assigned.
        bucket_name = None
        filename = None
        try:
            # Load variables
            bucket_name = os.environ["BUCKET_NAME"]
            folder_path = os.environ["FOLDER_PATH"]

            # Initialise S3 client
            s3 = boto3.client("s3")

            # Load Data / Take Health Data

            health_data = self.response
            date = kwargs["date"] if "date" in kwargs else datetime.now() - timedelta(days=1)
            timestamp = date.strftime("%Y%m%d_%H%M%S")
            filename = f"/{timestamp}_healthData.json"
            s3_key = folder_path + filename

            # Convert to JSON string
            json_data = json.dumps(health_data.__dict__, indent=4, default=str)

            logging.info("Uploading file to %s to bucket %s", filename, bucket_name)

            s3.put_object(
                Bucket=bucket_name,
                Key=s3_key,  # add folder path to filename here
                Body=json_data,
                ContentType="application/json",
            )
        except Exception as e:
            logging.error("Failed to upload %s to %s: %s", filename, bucket_name, e)
            raise


# End-of-file (EOF)
