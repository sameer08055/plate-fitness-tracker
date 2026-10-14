"""
Scheduled jobs, triggered by EventBridge Scheduler (see infra/schedules.tf):

- evening_reminder: emails you if you're short on protein or haven't logged sleep.
- weekly_summary:   emails your week's protein, sleep, and training stats.

Users come from Cognito, so there's no separate user list to keep in sync.
"""
import logging
import os
from datetime import date, timedelta

import boto3

import db
from logic import build_insights, build_reminder, format_weekly_email, local_date, summarize_day, utc_now

logger = logging.getLogger()
logger.setLevel(logging.INFO)

cognito = boto3.client("cognito-idp")
ses = boto3.client("ses")


def list_users():
    """Yield (user_id, email) for every enabled user in the pool."""
    paginator = cognito.get_paginator("list_users")
    for page in paginator.paginate(UserPoolId=os.environ["USER_POOL_ID"]):
        for user in page["Users"]:
            attributes = {a["Name"]: a["Value"] for a in user["Attributes"]}
            if user["Enabled"] and "email" in attributes:
                yield attributes["sub"], attributes["email"]


def send_email(to, subject, body):
    ses.send_email(
        Source=os.environ["SENDER_EMAIL"],
        Destination={"ToAddresses": [to]},
        Message={
            "Subject": {"Data": subject},
            "Body": {"Text": {"Data": f"{body}\n\nOpen the app: {os.environ['APP_URL']}"}},
        },
    )


def evening_reminder(user_id, email, goals):
    today = local_date(utc_now(), int(goals.get("utc_offset_minutes", 0)))
    entries = db.get_day(user_id, today)
    summary = summarize_day(entries["meals"], entries["sleep"], goals)
    message = build_reminder(summary, sleep_logged=entries["sleep"] is not None)
    if message:
        send_email(email, "Your evening check-in", message)
    return bool(message)


def weekly_summary(user_id, email, goals):
    end = local_date(utc_now(), int(goals.get("utc_offset_minutes", 0)))
    start = (date.fromisoformat(end) - timedelta(days=6)).isoformat()
    insights = build_insights(db.get_range(user_id, start, end), goals, start, end)
    send_email(email, "Your week in training", format_weekly_email(insights))
    return True


JOBS = {"evening_reminder": evening_reminder, "weekly_summary": weekly_summary}


def lambda_handler(event, context):
    job = JOBS[event["job"]]
    sent = 0
    for user_id, email in list_users():
        goals = db.get_goals(user_id)
        if not goals or not goals.get("reminders", True):
            continue  # no goals yet, or the user turned emails off
        try:
            sent += job(user_id, email, goals)
        except Exception:
            # One user's failure (e.g. an unverified email) shouldn't stop the rest.
            logger.exception("Job %s failed for user %s", event["job"], user_id)
    logger.info("Job %s sent %d emails", event["job"], sent)
    return {"sent": sent}
