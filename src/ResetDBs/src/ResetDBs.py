import json
import os
import re
import boto3
import logging
from decimal import Decimal
from typing import Any
from botocore.exceptions import ClientError
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response
from aws_lambda_powertools.event_handler.api_gateway import CORSConfig
from fbplib.fbpLog import fbpLog
from fbplib.getCurrentWeek import getCurrentWeek


'''
This function resets the DynamboDB tables during testing.
'''

logging.basicConfig(format='%(levelname)s %(message)s')
logger = logging.getLogger()
logger.info("Initializing ResetDBs Lambda function")  # Log initialization message
logger.setLevel(logging.INFO)

cors_config = CORSConfig(
    allow_origin="*",
    allow_headers=[
        "Content-Type",
        "X-Amz-Date",
        "Authorization",
        "X-Api-Key",
        "X-Amz-Security-Token",
    ],
    max_age=86400,
    allow_credentials=False,
)

app = APIGatewayHttpResolver(cors=cors_config)

FBP_USERS_TABLE_NAME = os.environ.get('FBPUsersTableName', 'FBP-Users')
logger.info(f"Using FBP Picks DynamoDB table: {FBP_USERS_TABLE_NAME}")

FBP_WEEKLY_RESULTS_TABLE = os.environ.get('FBPWeeklyResultsTable', 'FBP-Weekly-Results')
logger.info(f"Using FBP Weekly Results DynamoDB table: {FBP_WEEKLY_RESULTS_TABLE}")

@app.get("/resetDBs")
def resetDBs():
    fbpLog("fbpadmin@my-fbp.com", "ResetDBs", "Resetting DynamoDB tables", "INFO")

    usersTable = boto3.resource('dynamodb').Table(FBP_USERS_TABLE_NAME)
    # Set totalCorrectPicks and totalIncorrectPicks to 0 for all users in the FBP-Users table
    response = usersTable.scan()
    for item in response.get('Items', []):
        email = item['email']
        try:
            usersTable.update_item(
                Key={'email': email},
                UpdateExpression="SET #totalCorrectPicks = :zero, #totalIncorrectPicks = :zero",
                ExpressionAttributeNames={'#totalCorrectPicks': 'totalCorrectPicks', '#totalIncorrectPicks': 'totalIncorrectPicks'},
                ExpressionAttributeValues={':zero': 0}
            )
        except ClientError as e:
            logger.error(f"DynamoDB Error: {e}")
            fbpLog("fbpadmin@my-fbp.com", "ResetDBs", f"DynamoDB Error: {e}", "ERROR")
    # Set correctPicks and incorrectPicks to 0 for all users in the FBP-Weekly-Results table
    # unset Boolean Winner Field.
    resultsTable = boto3.resource('dynamodb').Table(FBP_WEEKLY_RESULTS_TABLE)
    response = resultsTable.scan()
    for item in response.get('Items', []):
        email = item['email']
        try:
            resultsTable.update_item(
                Key={'email': email},
                UpdateExpression="SET #correctPicks = :zero, #incorrectPicks = :zero, #winner = :false",
                ExpressionAttributeNames={
                    '#correctPicks': 'correctPicks', 
                    '#incorrectPicks': 'incorrectPicks',
                    '#winner': 'Winner'
                },
                ExpressionAttributeValues={':zero': 0, ':false': False}

            )
        except ClientError as e:
            logger.error(f"DynamoDB Error: {e}")
            fbpLog("fbpadmin@my-fbp.com", "ResetDBs", f"DynamoDB Error: {e}", "ERROR")
    return {"message": "DynamoDB tables FBP-Users and FBP-Weekly-Results reset successfully"}

def lambda_handler(event, context):
    return app.resolve(event, context)