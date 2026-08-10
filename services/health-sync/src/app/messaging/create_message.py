# Download the helper library from https://www.twilio.com/docs/python/install

import logging
from datetime import datetime

from dotenv import load_dotenv

from src.app.messaging.response_templates import (
    activity_steps,
    template_met_weekly,
    template_on_track_weekly,
    template_over_daily,
    template_over_weekly,
    template_under_daily,
    template_under_weekly,
    template_weekend,
)

load_dotenv()


class Create_Message:
    def __init__(self, metrics):
        self.no_data = metrics["No_Data"]
        if self.no_data == 1:
            return
        self.steps = int(metrics["Total_Steps"])
        self.goal = metrics["Total_Goal"]
        self.daily_goal = metrics["Daily_Goal"]
        self.average_steps = int(metrics["Average_Steps"])

    def create_message(self):
        a = int(datetime.now().strftime("%w"))

        if self.no_data == 1:
            return self.sync_activities()
        try:
            if a == 1:
                return self.generate_weekly_review()
            elif a == 5:
                return self.generate_weekend_response()
            else:
                return self.generate_daily_response()
        except Exception as e:
            logging.error("Exception in define_message: %s", e)
            return self.error_message()

    def sync_activities(self):
        response = "Please sync your watch by 9am so that you can recieve notifications"
        logging.info("User requested to sync their device")
        return response, "Sync Your Watch"

    def error_message(self):
        response = (
            "An error occurred while processing your activity data. "
            "Please contact the administrator and ask them to check the logs for more details."
        )
        logging.error("Error message generated: %s", response)
        return response, "An Error Occurred"

        # Suggest activities that meet or exceed a target step count

    def suggest_activities(self, target_steps):
        response = []
        for activity, steps in activity_steps.items():
            if target_steps >= steps:
                response.append(f"- {activity} (~{steps} steps per 10 min)")
                target_steps -= steps
        return response

        # Response generators

    def generate_daily_response(self):
        if self.steps >= self.goal:
            return template_over_daily.substitute(steps=self.steps, goal=self.goal), "Daily Update"
        else:
            suggestions = "\n".join(self.suggest_activities(self.goal - self.steps))
            return template_under_daily.substitute(
                steps=self.steps, goal=self.goal, suggestions=suggestions
            ), "Daily Update"

    def generate_weekend_response(self):
        daily_remaining = self.daily_goal - self.average_steps
        if daily_remaining > 310:
            suggestions = "\n".join(self.suggest_activities(daily_remaining))

            return template_weekend.substitute(
                week_steps=self.steps,
                daily_remaining=daily_remaining,
                suggestions=suggestions,
            ), "Get ready for the weekend"
        else:
            suggestions = "Keep doing what you are doing"
            return template_on_track_weekly.substitute(
                goal=(self.daily_goal * 7)
            ), "On Track for the weekend"

    def generate_weekly_review(self):
        if self.steps > self.goal:
            return template_over_weekly.substitute(
                total=self.steps, goal=self.goal
            ), "Over Achieved"
        elif self.steps == self.goal:
            return template_met_weekly.substitute(total=self.steps, goal=self.goal), "On Track"
        else:
            suggestions = "\n".join(self.suggest_activities(self.goal - self.steps))
            return template_under_weekly.substitute(
                total=self.steps, goal=self.goal, suggestions=suggestions
            ), "Keep Progressing"
