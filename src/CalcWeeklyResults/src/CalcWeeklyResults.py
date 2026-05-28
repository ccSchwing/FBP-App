from calendar import c
import json
import os
from typing import Any
import boto3
import logging
from botocore.exceptions import ClientError
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver
from aws_lambda_powertools.event_handler.api_gateway import CORSConfig
from fbplib.fbpLog import fbpLog
from fbplib import getCurrentWeek


'''
This function calculates the weekly results for each game based on the actual game results for the week.
It queries the FBP-Schedule table for the current week and updates the Winner field for each
game based on the HomeScore, AwayScore, Spread, and Underdog fields. This is used by the UpdateWeeklyResults function
to determine the number of correct and incorrect picks for each user for the week.
'''
logging.basicConfig(format='%(levelname)s %(message)s')
logger = logging.getLogger()
logger.info("Initializing CalcWeeklyResultsPython Lambda function")  # Log initialization message
logger.setLevel(level=logging.INFO)

USERS_TABLE_NAME = os.environ.get('FBPUsersTableName', 'FBP-Users')
logger.info(f"Using DynamoDB table: {USERS_TABLE_NAME}")  # Log the table name being used
fbpLog("fbpadmin@my-fbp.com", "CalcWeeklyResultsPython", "Lambda function initialized", "INFO")

cors_config = CORSConfig(
    allow_origin="*",  # Or specify your domain like "https://yourdomain.com"
    allow_headers=["Content-Type", "X-Amz-Date", "Authorization", "X-Api-Key", "X-Amz-Security-Token"],
    max_age=86400,  # Cache preflight for 24 hours
    allow_credentials=False
)

app=APIGatewayHttpResolver(cors=cors_config)

@app.get("/calcWeeklyResults")
def calcWeeklyResults():
    fbpLog("fbpadmin@my-fbp.com", "CalcWeeklyResultsPython", "Calculating weekly results", "INFO")
   
    FBP_SCHEDULE_TABLE_NAME = os.environ.get('FBPScheduleTableName', 'FBP-Schedule')
    logger.info(f"Using FBP Schedule DynamoDB table: {FBP_SCHEDULE_TABLE_NAME}")
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(FBP_SCHEDULE_TABLE_NAME) 

    FBP_CONFIG_TABLE_NAME = os.environ.get('FBPConfigTableName', 'FBP-Config')
    logger.info(f"Using FBP Config DynamoDB table: {FBP_CONFIG_TABLE_NAME}")
    config_table = dynamodb.Table(FBP_CONFIG_TABLE_NAME)

    week=getCurrentWeek.getCurrentWeek()
    if week is None:
        fbpLog("fbpadmin@my-fbp.com", "CalcWeeklyResultsPython", "Could not determine current week", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Could not determine current week'}),
        }

    # Before you do antything, check to see if this method has already
    # been run for the current week.
    # This is done by checking the FBP-Config table for the curren week.
    # In addition the Pool must be closed when you run this method.
    # If you run it and poolOpen is true or resultsCalculated is true
    # a return of 202 will be returned and the method will not run.
    config_response = config_table.get_item(Key={'Week': week })
    if 'Item' in config_response:
        current_week_config = config_response['Item']
        if current_week_config.get('Week') == week:
            if current_week_config.get('poolOpen', True):
                fbpLog("fbpadmin@my-fbp.com", "CalcWeeklyResultsPython", "Pool is still open for the current week", "WARNING")
                return {
                    'statusCode': 202,
                    'body': json.dumps({'message': 'Pool is still open for the current week.  Cannot calculate results until pool is closed'}),
                }
            if current_week_config.get('resultsCalculated', False):
                fbpLog("fbpadmin@my-fbp.com", "CalcWeeklyResultsPython", "Results have already been calculated for the current week", "WARNING")
                return {
                    'statusCode': 202,
                    'body': json.dumps({'message': 'Results have already been calculated for the current week'}),
                }
    # If we get here, we can proceed with calculating the results for the week.
    logger.info(f"Calculating results for week: {week}")
    try:
        response = table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr('Week').eq(week)
        )
        games = response.get('Items', [])

        if not games:
            logger.warning(f"No games found for week {week}")
            fbpLog("fbpadmin@my-fbp.com", "CalcWeeklyResults", f"No games found for week {week}", "WARNING")
            return {
                'statusCode': 404,
                'body': json.dumps({'error': f'No games found for week {week}'}),
            }
        else:
            logger.info(f"Retrieved {len(games)} games for week {week}")
            fbpLog("fbpadmin@my-fbp.com", "CalcWeeklyResults", f"Retrieved {len(games)} games for week {week}", "INFO")
            for game in games:
                row=calculateWeeklyResults(game)
                table.update_item(
                    Key={'Week': row['Week'], 'GameId': row['GameId']},
                    UpdateExpression="SET #winner = :w",
                    ExpressionAttributeNames={'#winner': 'Winner'},
                    ExpressionAttributeValues={':w': row['Winner']}
                )
            # # After we have updated all the games for the week, we need to update the FBP-Config table 
            # # to set resultsCalculated to true for the current week.
            # # This will prevent this method from being run again for the current week.
            # try:
            #     config_table.update_item(
            #         Key={'Week': week},
            #         UpdateExpression="SET #resultsCalculated = :rc",
            #         ExpressionAttributeNames={'#resultsCalculated': 'resultsCalculated'},
            #         ExpressionAttributeValues={':rc': True}
            #     )
            # except ClientError as e:
            #     logger.error(f"Error updating FBP-Config table: {e}")
            #     fbpLog("fbpadmin@my-fbp.com", "CalcWeeklyResults", f"Error updating FBP-Config table: {e}", "ERROR")
            #     return {
            #         'statusCode': 500,
            #         'body': json.dumps({'error': 'Error updating FBP-Config table'}),
            #     }
            # logger.info(f"Calculated results for week {week}: {len(games)} games updated")
            # fbpLog("fbpadmin@my-fbp.com", "CalcWeeklyResults", f"Calculated results for week {week}", "INFO")
    except ClientError as e:
        logger.error(f"DynamoDB Error: {e}")
        fbpLog("fbpadmin@my-fbp.com", "CalcWeeklyResults", f"DynamoDB Error: {e}", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'DynamoDB Error'}),
        }
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        fbpLog("fbpadmin@my-fbp.com", "CalcWeeklyResults", f"Unexpected error: {e}", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Unexpected error'}),
        }
    return {
        'statusCode': 200,
        'body': json.dumps({'message': f'Weekly results calculated for week {week}'}),
    }


def calculateWeeklyResults(game):
    homeScore = game.get('HomeScore', 0)
    awayScore = game.get('AwayScore', 0)
    underDog = game.get('Underdog', 'Unknown')
    homeTeam: Any =  game.get('Home', 'Unknown')
    awayTeam: Any =  game.get('Away', 'Unknown')
    spread: Any  = game.get('Spread', 0)
    HorA: Any

    if underDog == 'H':
        homeScore += spread
    elif underDog == 'A':
        awayScore += spread
    if homeScore > awayScore:
        HorA = 'H'
    elif awayScore > homeScore:
        HorA = 'A'

        
    game['Winner'] = HorA
        
    return game

def lambda_handler(event, context):
    return app.resolve(event, context)  