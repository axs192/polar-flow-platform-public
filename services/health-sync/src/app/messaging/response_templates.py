"""
Used for storing templates
"""

from string import Template

# Activity dictionary: estimated steps per 10 minutes
"""
For more information visit: https://wellness.osu.edu/sites/default/files/documents/2021/02/2021.02.-%20HLS%20Step%20Conversion%20Chart.pdf
"""
activity_steps = {
    "Jogging": 2000,
    "Jump Rope": 1780,
    "Brisk walking": 1500,
    "Aerobics": 1300,
    "Swimming": 1200,
    "Dancing": 1090,
    "Cycling (moderate pace)": 1000,
    "Stair climbing": 900,
    "Casual walking": 800,
    "Yoga": 400,
}

# Templates
template_over_daily = Template(
    "Great job! You completed $steps steps yesterday, which is over your goal of $goal"
    " steps. Keep up the momentum!"
)

template_under_daily = Template(
    "You completed $steps steps yesterday, which is below your goal of $goal steps."
    "Here are a few easy ways to close the gap today: $suggestions"
)

template_weekend = Template(
    "It's Friday! You've completed $week_steps steps so far this week (Mon–Thurs)."
    "To hit your goal, aim for an additional $daily_remaining steps per day over the "
    "weekend. Here are some activities that can help:\n$suggestions"
)
template_friday_met_weekly = Template(
    "Happy Friday! You've already met your weekly goal with $total steps—amazing work!"
    "Why not celebrate by enjoying a healthy activity this weekend, like a walk in nature"
    " or a fun group class? Keep prioritizing your wellbeing and have a fantastic weekend!"
)

template_on_track_weekly = Template(
    "You're on track to meet your weekly goal! Keep up the great work—just a little more effort and you'll reach $goal steps."
    "Stay active and consider adding a healthy activity to your routine, like a brisk walk or a yoga session. You've got this!"
)

template_met_weekly = Template(
    "You met your weekly goal with $total steps! Goal was $goal steps. Well done!"
)

template_over_weekly = Template(
    "Fantastic! You exceeded your weekly goal with $total steps. Your goal was $goal steps. Keep it going!"
)

template_under_weekly = Template(
    "You reached $total steps this week, which is below your goal of $goal steps."
    "Consider these activities next week to help you reach your goal: $suggestions"
)
