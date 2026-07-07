import decimal
import json
from decimal import Decimal
import os
from typing import Any, Dict, cast
import boto3
import logging
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Attr, Key
from aws_lambda_powertools import Tracer
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response
from aws_lambda_powertools.event_handler.api_gateway import CORSConfig
from fbplib.decimalDefault import decimal_default
from fbplib.fbpLog import fbpLog
from fbplib.getCurrentWeek import getCurrentWeek

tracer = Tracer()
logger = logging.getLogger()
logger.setLevel(logging.INFO)

cors_config = CORSConfig(
    allow_origin="*",  # Or specify your domain like "https://yourdomain.com"
    allow_headers=["Content-Type", "X-Amz-Date", "Authorization", "X-Api-Key", "X-Amz-Security-Token"],
    max_age=86400,  # Cache preflight for 24 hours
    allow_credentials=False
)

app=APIGatewayHttpResolver(cors=cors_config)

@tracer.capture_method
@app.get(r"/getTeamRecord")
def getTeamRecord() -> Response:
    logger.info("Fetching team records")
    # TEAM_RECORD_TABLE = os.environ.get('FBPTeamRecordsTableName', '2025-Record')
    try:
        dynamodb = boto3.resource('dynamodb')
        recordTable = dynamodb.Table(os.environ['FBPTeamRecordsTableName'])
        scheduleTable = dynamodb.Table(os.environ['FBPScheduleTableName'])
        current_week = getCurrentWeek() or 1
        weeksResponse = scheduleTable.scan(
            FilterExpression=Attr('Week').between(1, (current_week - 1))
        )
        items = weeksResponse.get('Items', [])
        items.sort(key=lambda x: x['Week'])

        ##
        # Only keep track of the wins for each team vs the spread.
        ##
        for item in items:
            logger.info(f"Fetched schedule item: {item}")
            underdog= item.get('Underdog').strip()
            winner = item.get('Winner').strip()
            if winner == "H" and underdog == "H":
                teamName = item.get('Home')
                recordTable.update_item(
                    Key={'TeamName': teamName},
                    UpdateExpression="ADD UnderdogWins :inc",
                    ExpressionAttributeValues={':inc': Decimal(1)}
                )
            if winner == "A" and underdog == "A":
                teamName = item.get('Away')
                recordTable.update_item(
                    Key={'TeamName': teamName},
                    UpdateExpression="ADD UnderdogWins :inc",
                    ExpressionAttributeValues={':inc': Decimal(1)}
                )
            ##
            # if the favorite wins, we want to track the losses for the underdog team.
            ##
            if winner == "H" and underdog == "A":
                teamName = item.get('Home')
                recordTable.update_item(
                    Key={'TeamName': teamName},
                    UpdateExpression="ADD FavoriteWins :inc",
                    ExpressionAttributeValues={':inc': Decimal(1)}
                )
            if winner == "A" and underdog == "H":
                teamName = item.get('Away')
                recordTable.update_item(
                    Key={'TeamName': teamName},
                    UpdateExpression="ADD FavoriteWins :inc",
                    ExpressionAttributeValues={':inc': Decimal(1)}
                )
        return Response(
            body=json.dumps(items, default=decimal_default),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )
    except ClientError as e:
        error_message = e.response.get('Error', {}).get('Message', str(e))
        logger.error(f"Error fetching team records: {error_message}")
        return Response(
            body=json.dumps({"error": "Could not fetch team records"}),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )





@tracer.capture_lambda_handler
def lambda_handler(event, context):
    return app.resolve(event, context)