import json
from decimal import Decimal
import os
from typing import Any, List, Dict
import boto3
import logging
import csv
import io
from botocore.exceptions import ClientError
from fbplib.fbpLog import fbpLog
from fbplib.getCurrentWeek import getCurrentWeek
##
# Import json data from s3 bucket and update 2025-Schedule dynamoDb table
##


logging.basicConfig(format='%(levelname)s %(message)s')
logger = logging.getLogger()
logger.info("Initializing ImportSpreads Lambda function")  # Log initialization message
logger.setLevel(logging.INFO)

def importSpreadsAndFinalScores(event, context):
    # return app.resolve(event, context)
    FBP_SCHEDULE_TABLE = os.environ.get('FBPSchedule2025TableName', 'FBP-Schedule-2025')
    logger.info(f"Using DynamoDB table: {FBP_SCHEDULE_TABLE}")  # Log the table name being used
    fbpLog("fbpadmin@my-fbp.com", "ImportSpreads", "Lambda function initialized", "INFO")
    s3 = boto3.client('s3')
    bucket_name = os.environ.get('S3BucketName', 'my-fbp.com')
    logger.info(f"Using S3 bucket: {bucket_name}")  # Log the bucket name being used
    week=getCurrentWeek()
    csvKey = f"schedule/2025-Schedule/week{week}-schedule.csv"
    try:
        response = s3.get_object(Bucket=bucket_name, Key=csvKey)

        dynamodb = boto3.resource('dynamodb')
        FBP_SCHEDULE_TABLE = os.environ.get('FBPSchedule2025TableName', '2025-Schedule')
        table = dynamodb.Table(FBP_SCHEDULE_TABLE)

        logger.info(f"Processing file: {csvKey} from bucket: {bucket_name}")  # Log the file being processed
        logger.info("Starting to process spreads data and update DynamoDB")
        fbpLog("fbpadmin@my-fbp.com", "ImportSpreads", f"Starting to process spreads data from {csvKey} and update DynamoDB", "INFO")
        fbpLog("fbpadmin@my-fbp.com", "ImportSpreads", f"Retrieved spreads data from {csvKey}", "INFO")
        fbpLog("fbpadmin@my-fbp.com", "ImportSpreads", f"Starting to process spreads data from {csvKey} and update DynamoDB", "INFO")


        content = response['Body'].read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        spreads_data = list(reader)

        logger.info(f"Retrieved {len(spreads_data)} objects from bucket: {bucket_name}")
        week = getCurrentWeek()
        for spread in spreads_data:
            game_id = spread.pop('GameId', None)  # save before popping
            spread['Week'] = week
            spread['Spread'] = Decimal(str(spread['Spread']))
            try:     
                table.update_item(
                    Key={
                        'Week': week,
                        'GameId': game_id
                    },
                    UpdateExpression="SET #spread = :spread",
                    ExpressionAttributeNames={"#spread": "Spread"},
                    ExpressionAttributeValues={":spread": spread['Spread']}
                )
            except ClientError as e:
                error_msg = e.response.get('Error', {}).get('Message', str(e))
                logger.exception(f"Failed to insert spread data into DynamoDB for game: {spread['homeTeam']} vs {spread['awayTeam']}. Error: {error_msg}")
                fbpLog("fbpadmin@my-fbp.com", "ImportSpreads", f"Failed to insert spread data into DynamoDB for game: {spread['homeTeam']} vs {spread['awayTeam']}. Error: {error_msg}", "ERROR")
            except Exception as e:
                logger.exception(f"Unexpected error while processing spread data for game: {spread['homeTeam']} vs {spread['awayTeam']}. Error: {str(e)}")
                fbpLog("fbpadmin@my-fbp.com", "ImportSpreads", f"Unexpected error while processing spread data for game: {spread['homeTeam']} vs {spread['awayTeam']}. Error: {str(e)}", "ERROR")
        logger.info(f"Finished processing spreads data from {csvKey} and updating DynamoDB")
        fbpLog("fbpadmin@my-fbp.com", "ImportSpreads", f"Finished processing spreads data from {csvKey} and updating DynamoDB", "INFO")
    except ClientError as e:
        logger.exception(f"Failed to list objects in S3 bucket: {bucket_name}. Error: {e.response['Error']['Message']}")
        fbpLog("fbpadmin@my-fbp.com", "ImportSpreads", f"Failed to list objects in S3 bucket: {bucket_name}. Error: {e.response['Error']['Message']}", "ERROR")
