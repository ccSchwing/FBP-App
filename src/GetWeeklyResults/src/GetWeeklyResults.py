from calendar import c
import email
import json
from math import pi
from operator import index
import os
import re
from typing import Any, List, Dict
import boto3
import logging
from botocore.exceptions import ClientError
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver
from aws_lambda_powertools.event_handler.api_gateway import CORSConfig
from fbplib.fbpLog import fbpLog
from fbplib import getCurrentWeek


'''
This function retrieves the weekly results for each user based on their picks and the actual game results for the week.
It queries the FBPWeeklyResults table for the current week and returns the results sorted by the
number of correct picks. It also updates the winner field for the user with the most correct picks.
This is used by the front end to display the weekly results sheet for each user.
'''

logger = logging.getLogger()
logger.info("Initializing GetWeeklyResults Lambda function")  # Log initialization message
logger.setLevel(logging.INFO)

cors_config = CORSConfig(
    allow_origin="*",  # Or specify your domain like "https://yourdomain.com"
    allow_headers=["Content-Type", "X-Amz-Date", "Authorization", "X-Api-Key", "X-Amz-Security-Token"],
    max_age=86400,  # Cache preflight for 24 hours
    allow_credentials=False
)

app=APIGatewayHttpResolver(cors=cors_config)

@app.get("/getWeeklyResults")
def getWeeklyResults():
    FBP_WEEKLY_RESULTS_TABLE = os.environ.get('FBPWeeklyResultsTable', 'FBP-Weekly-Results')
    logger.info(f"Using DynamoDB table: {FBP_WEEKLY_RESULTS_TABLE}")  # Log the table name being used
    fbpLog("fbpadmin@my-fbp.com", "GetWeeklyResults", "Lambda function initialized", "INFO")
    fbpLog("fbpadmin@my-fbp.com", "GetWeeklyResults", "Retrieving weekly results", "INFO")
   
    FBP_USERS_TABLE_NAME = os.environ.get('FBPUsersTableName', 'FBP-Users')
    logger.info(f"Using FBP Users DynamoDB table: {FBP_USERS_TABLE_NAME}")
    dynamodb = boto3.resource('dynamodb')
    resultsTable = dynamodb.Table(FBP_WEEKLY_RESULTS_TABLE) 
    usersTable = dynamodb.Table(FBP_USERS_TABLE_NAME)

    week=getCurrentWeek.getCurrentWeek()
    if week is None:
        fbpLog("fbpadmin@my-fbp.com", "GetWeeklyResults", "Could not determine current week", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Could not determine current week'}),
        }
    logger.info(f"Retrieving results for week: {week}")
    fbpLog("fbpadmin@my-fbp.com", "GetWeeklyResults", f"Retrieving results for week: {week}", "INFO")
    try:
        response = resultsTable.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr('Week').eq(week)
        )
        allUserPicks  = response.get('Items', [])

        if not allUserPicks:
            logger.warning(f"No picks found for week {week}")
            fbpLog("fbpadmin@my-fbp.com", "GetWeeklyResults", f"No picks found for week {week}", "WARNING")
            return {
                'statusCode': 404,
                'body': json.dumps({'error': f'No picks found for week {week}'}),
            }
        else:
            logger.info(f"Retrieved {len(allUserPicks)} picks for week {week}")
            fbpLog("fbpadmin@my-fbp.com", "GetWeeklyResults", f"Retrieved {len(allUserPicks)} picks for week {week}", "INFO")
            sortedPicks=sortWeeklyResults(picks=allUserPicks)
            winner=sortedPicks[0]['CorrectPicks']
            email=sortedPicks[0]['email']
            resultsTable.update_item(
                Key={'email': email},
                UpdateExpression="SET #Winner = :w",
                ExpressionAttributeNames={'#Winner': 'Winner'},
                ExpressionAttributeValues={':w': bool(winner)}
                )
            fbpLog("fbpadmin@my-fbp.com", "GetWeeklyResults", f"Updated winner for week {week}: {email}", "INFO")
            # If this were a big table, I'd batch this.
            for picks in sortedPicks:
                if sortedPicks.index(picks) == 0:
                    picks['Winner'] = True
                    resultsTable.update_item(
                        Key={'email': picks['email']},
                        UpdateExpression="SET #Winner = :w",
                        ExpressionAttributeNames={'#Winner': 'Winner'},
                        ExpressionAttributeValues={':w': True}
                    )
                else:
                    picks['Winner'] = False
                    resultsTable.update_item(
                        Key={'email': picks['email']},
                        UpdateExpression="SET #Winner = :w",
                        ExpressionAttributeNames={'#Winner': 'Winner'},
                        ExpressionAttributeValues={':w': False}
                    )
            # Why are we updating this table??
            # That's the job of the UpdateWeeklyResults function.
            # This is just to return the results to the front end.
            #       
            # for picks in allUserPicks:
            #     userEmail=picks['email']
            #     correctPicks=picks['CorrectPicks']
            #     incorrectPicks=picks['IncorrectPicks']
            #     usersTable.update_item(
            #         Key={'email': userEmail},
            #         UpdateExpression="SET #totalCorrectPicks = if_not_exists(#totalCorrectPicks, :zero) + :c, #totalIncorrectPicks = if_not_exists(#totalIncorrectPicks, :zero) + :i",
            #         ExpressionAttributeNames={'#totalCorrectPicks': 'totalCorrectPicks', '#totalIncorrectPicks': 'totalIncorrectPicks'},
            #         ExpressionAttributeValues={':zero': 0, ':c': correctPicks, ':i': incorrectPicks}
            #     )
            # fbpLog("fbpadmin@my-fbp.com", "GetWeeklyResults", f"Updated user picks for week {week}", "INFO")
            # logger.info(f"Calculated results for week {week}: {len(allUserPicks)} allUserPicks updated")
            # fbpLog("fbpadmin@my-fbp.com", "GetWeeklyResults", f"Calculated results for week {week}", "INFO")
    except ClientError as e:
        logger.error(f"DynamoDB Error: {e}")
        fbpLog("fbpadmin@my-fbp.com", "GetWeeklyResults", f"DynamoDB Error: {e}", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'DynamoDB Error'}),
        }
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        fbpLog("fbpadmin@my-fbp.com", "GetWeeklyResults", f"Unexpected error: {e}", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Unexpected error'}),
        }
    return {
        'statusCode': 200,
        'body': json.dumps({'message': f'Weekly results calculated for week {week}'}),
    }


def sortWeeklyResults(picks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(picks, key=lambda x: x['CorrectPicks'], reverse=True)

def lambda_handler(event, context):
    return app.resolve(event, context)  